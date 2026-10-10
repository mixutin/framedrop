"""Upgrade isolation: fake HOME, real files, and mocked process integrations."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from montage_studio import __version__
from montage_studio.config import Config


_SPEC = importlib.util.spec_from_file_location("framedrop_installer", Path(__file__).resolve().parents[1]/"install.py")
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)


class InstallMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="framedrop-install-")
        self.addCleanup(self.temp.cleanup)
        self.fake_home = Path(self.temp.name)/"isolated home"
        self.fake_home.mkdir()
        self.media = self.fake_home/"Editing"
        self.media.mkdir()
        self.processes = []
        self.servers = []
        self.environment = {"HOME": str(self.fake_home), "PATH": os.environ.get("PATH", "")}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, self.environment, clear=True))
        self.stack.enter_context(patch.object(Path, "home", return_value=self.fake_home))

    def write(self, relative, content):
        path = self.fake_home/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def config(self, *, legacy=True, media=None):
        media = media or self.media
        values = {"media_root": str(media), "workspace": str(media/"MontageStudio"),
                  "state_dir": str(self.fake_home/".local/share/montage-studio"),
                  "port": 9123, "threads": 2, "ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}
        relative = ".config/montage-studio/config.json" if legacy else ".config/framedrop/config.json"
        path = self.write(relative, json.dumps(values))
        return path, values

    def process(self, argv, **kwargs):
        self.processes.append(list(argv))
        stdout = json.dumps(self.servers) if argv[1:] == ["mcp", "list", "--json"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def install(self, *arguments):
        output = io.StringIO()
        with patch.object(sys, "argv", ["install.py", *arguments]), \
             patch.object(installer.shutil, "which", side_effect=lambda name: "/fake/bin/"+name), \
             patch.object(installer.subprocess, "run", side_effect=self.process), redirect_stdout(output):
            installer.main()
        return json.loads(output.getvalue())

    def test_fresh_install_creates_new_paths_and_working_legacy_alias(self):
        result = self.install()
        config = json.loads(Path(result["config"]).read_text())
        self.assertEqual(config["workspace"], str(self.media/"Framedrop"))
        self.assertEqual(config["state_dir"], str(self.fake_home/".local/share/framedrop"))
        self.assertEqual(Path(result["config"]).stat().st_mode & 0o777, 0o600)
        for name in ("framedrop", "montage"):
            command = self.fake_home/".local/bin"/name
            # Execute both real generated shell launchers, including a HOME with
            # a space; no editor workspace is opened by --version.
            finished = subprocess.run([str(command), "--version"], capture_output=True, text=True,
                                      env=self.environment, timeout=10, check=True)
            self.assertIn(f"Framedrop {__version__}", finished.stdout)
        self.assertEqual(self.processes, [])

    def test_upgrade_reuses_legacy_config_and_preserves_projects_history_models(self):
        legacy_path, values = self.config()
        legacy_before = legacy_path.read_bytes()
        fixtures = [self.write("Editing/MontageStudio/projects/p_saved.json", '{"revision":7}'),
                    self.write("Editing/MontageStudio/history/p_saved/6.json", '{"revision":6}'),
                    self.write(".local/share/montage-studio/models/model.bin", "cached-model")]
        before = {path: path.read_bytes() for path in fixtures}
        self.write(".local/bin/montage", "#!/bin/sh\n# Montage Studio launcher\nold-command\n")
        result = self.install()
        self.assertEqual(json.loads(Path(result["config"]).read_text()), values)
        self.assertEqual(legacy_path.read_bytes(), legacy_before)
        self.assertEqual({path: path.read_bytes() for path in fixtures}, before)
        loaded = Config.load()
        self.assertEqual(loaded.workspace, Path(values["workspace"]))
        self.assertEqual(loaded.state_dir, Path(values["state_dir"]))
        self.assertIn("# Framedrop launcher", (self.fake_home/".local/bin/montage").read_text())

    def test_upgrade_without_media_flag_reuses_existing_custom_library(self):
        custom = self.fake_home/"Videos"/"My edits"
        custom.mkdir(parents=True)
        _, values = self.config(media=custom)
        result = self.install()
        self.assertEqual(json.loads(Path(result["config"]).read_text()), values)

    def test_config_load_falls_back_to_legacy_then_prefers_new_configuration(self):
        _, legacy = self.config()
        self.assertEqual(Config.load().workspace, Path(legacy["workspace"]))
        preferred = {**legacy, "workspace": str(self.fake_home/"another-workspace"), "port": 9345}
        self.write(".config/framedrop/config.json", json.dumps(preferred))
        self.assertEqual(Config.load().workspace, Path(preferred["workspace"]))
        self.assertEqual(Config.load().port, 9345)

    def test_unrelated_legacy_files_and_mcp_entry_are_preserved(self):
        binary = self.write(".local/bin/montage", "#!/bin/sh\n# Unrelated application\nexit 0\n")
        desktop = self.write(".local/share/applications/montage-studio.desktop", "[Desktop Entry]\nName=Other tool\n")
        service = self.write(".config/systemd/user/montage-studio.service", "[Unit]\nDescription=Other tool\n")
        before = {path: path.read_bytes() for path in (binary, desktop, service)}
        # The name and path alone are insufficient proof of ownership: the
        # existing command was deliberately preserved as an unrelated program.
        self.servers = [{"name": "montage-studio", "transport": {"command": str(binary), "args": ["mcp"]}}]
        self.install("--register-mcp", "--start")
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse(any(call[1:3] == ["mcp", "remove"] for call in self.processes))
        self.assertFalse(any("disable" in call for call in self.processes))

    def test_owned_legacy_mcp_desktop_and_service_are_migrated(self):
        _, values = self.config()
        binary = self.write(".local/bin/montage", "#!/bin/sh\n# Montage Studio launcher\n")
        desktop = self.write(".local/share/applications/montage-studio.desktop", "[Desktop Entry]\nName=Montage Studio\nIcon=/source/montage_studio/static/icon.svg\n")
        self.write(".config/systemd/user/montage-studio.service", f"[Unit]\nDescription=Montage Studio local editor\n[Service]\nExecStart={binary} ui\n")
        self.servers = [{"name": "montage-studio", "transport": {"command": str(binary), "args": ["mcp"]}},
                        {"name": "unrelated", "transport": {"command": "other", "args": []}}]
        result = self.install("--register-mcp", "--start")
        self.assertTrue(result["mcp_registered"])
        self.assertTrue(result["service_started"])
        self.assertFalse(desktop.exists())
        self.assertIn(["/fake/bin/codex", "mcp", "remove", "montage-studio"], self.processes)
        self.assertIn(["systemctl", "--user", "disable", "--now", "montage-studio.service"], self.processes)
        self.assertFalse(any("unrelated" in call for call in self.processes))
        self.assertEqual(json.loads(Path(result["config"]).read_text()), values)

    def test_unrelated_framedrop_registration_is_not_overwritten(self):
        self.servers = [{"name": "framedrop", "transport": {"command": "/other/app", "args": ["mcp"]}}]
        with self.assertRaisesRegex(SystemExit, "unrelated framedrop MCP"):
            self.install("--register-mcp")
        self.assertEqual(self.processes, [["/fake/bin/codex", "mcp", "list", "--json"]])

    def test_unrelated_new_launcher_is_not_overwritten(self):
        command = self.write(".local/bin/framedrop", "#!/bin/sh\n# Another application\n")
        before = command.read_bytes()
        with self.assertRaisesRegex(SystemExit, "unrelated existing file"):
            self.install()
        self.assertEqual(command.read_bytes(), before)

    def test_explicit_cli_config_beats_inherited_framedrop_config(self):
        from montage_studio import cli
        first = self.write("inherited.json", json.dumps({"media_root": str(self.media), "port": 9123}))
        chosen = self.write("chosen.json", json.dumps({"media_root": str(self.media), "port": 9234}))
        os.environ["FRAMEDROP_CONFIG"] = str(first)
        class FakeService:
            def call(self, *args):
                return {"port": Config.load().port}
        output = io.StringIO()
        with patch("montage_studio.service.Service", FakeService), redirect_stdout(output):
            self.assertEqual(cli.main(["--config", str(chosen), "status"]), 0)
        self.assertEqual(json.loads(output.getvalue())["port"], 9234)


if __name__ == "__main__":
    unittest.main()
