"""Storage regressions: file containment, imports and revision transactions.

These tests use tiny local files and substitute only FFmpeg probing/validation;
the actual SQLite catalog, ZIP reader, project locks and JSON writes run normally.
The final test also exercises the real engine's empty-project contract.
"""

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import importlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from montage_studio.assets import AssetLibrary
from montage_studio.config import Config, StudioError
from montage_studio.projects import ProjectStore


class StorageCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        media = self.base / "Editing"
        media.mkdir()
        self.config = Config(media, media / "MontageStudio", self.base / "state")
        self.config.ensure()
        self.metadata = {}
        self.engine = types.ModuleType("montage_studio.engine")
        self.engine.probe = lambda path: copy.deepcopy(
            self.metadata.get(str(path), {"duration": 8, "has_audio": True, "has_video": True, "width": 320, "height": 180, "fps": 30})
        )
        self.engine.validate_project = lambda project, resolver: {"valid": True, "errors": [], "warnings": [], "duration": self.engine.project_duration(project)}
        self.engine.project_duration = lambda project: sum((clip["out"] - clip["in"]) / clip.get("speed", 1) for clip in project.get("clips", []))
        mocked = patch.dict(sys.modules, {"montage_studio.engine": self.engine})
        mocked.start()
        self.addCleanup(mocked.stop)
        self.library = AssetLibrary(self.config)
        self.projects = ProjectStore(self.config, self.library)

    def make_file(self, relative, content=b"test-media", metadata=None):
        path = self.config.media_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if metadata is not None:
            self.metadata[str(path)] = metadata
        return path

    def asset(self, relative, content=b"test-media", metadata=None):
        self.make_file(relative, content, metadata)
        self.library.scan()
        asset_id = hashlib.sha256(relative.encode()).hexdigest()[:24]
        return self.library.get(asset_id)

    def archive(self, members, relative="Pack.zip"):
        path = self.config.media_root / relative
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members:
                archive.writestr(name, data)
        self.library.scan()
        return self.library.get(hashlib.sha256(relative.encode()).hexdigest()[:24])

    def import_path(self, archive, member):
        return self.config.media_root / "MontageImports" / archive["id"] / member

    def snapshot(self):
        return {str(path.relative_to(self.config.workspace)): path.read_bytes() for path in self.config.workspace.rglob("*.json")}


class AssetStorageTests(StorageCase):
    def test_scan_excludes_workspace_hidden_paths_and_external_symlinks(self):
        self.make_file("Footage/real.mp4")
        self.make_file(".hidden.mp4")
        self.make_file(".cache/cached.mp4")
        self.make_file("__pycache__/cached.mp4")
        self.make_file("MontageStudio/renders/output.mp4")
        external = self.base / "outside.mp4"
        external.write_bytes(b"outside")
        (self.config.media_root / "outside.mp4").symlink_to(external)
        external_folder = self.base / "external"
        external_folder.mkdir()
        (external_folder / "video.mp4").write_bytes(b"outside")
        (self.config.media_root / "external-folder").symlink_to(external_folder, target_is_directory=True)
        scanned = self.library.scan()
        self.assertEqual(scanned["total"], 1)
        self.assertEqual(self.library.list()["items"][0]["relative_path"], "Footage/real.mp4")

    def test_asset_symlink_changed_after_scan_cannot_escape_root(self):
        asset = self.asset("clip.mp4")
        path = Path(asset["path"])
        outside = self.base / "private.mp4"
        outside.write_bytes(b"outside")
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(StudioError) as caught:
            self.library.get(asset["id"])
        self.assertEqual(caught.exception.code, "path_not_allowed")

    def test_search_treats_sql_wildcards_and_backslashes_literally(self):
        for name in ("one%clip.mp4", "one_clip.mp4", "oneXclip.mp4", "one\\clip.mp4"):
            self.make_file(name)
        self.library.scan()
        for query, expected in (("%", "one%clip.mp4"), ("_", "one_clip.mp4"), ("\\", "one\\clip.mp4"), ("ONEX", "oneXclip.mp4")):
            with self.subTest(query=query):
                found = self.library.list(query=query)
                self.assertEqual(found["total"], 1)
                self.assertEqual(found["items"][0]["name"], expected)

    def test_disappearing_media_reports_missing_then_rescan_removes_catalog_entry(self):
        asset = self.asset("clip.mp4")
        Path(asset["path"]).unlink()
        with self.assertRaises(StudioError) as caught:
            self.library.get(asset["id"])
        self.assertEqual(caught.exception.code, "asset_missing")
        summary = self.library.scan()
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(self.library.list()["total"], 0)
        with self.assertRaises(StudioError) as caught:
            self.library.get(asset["id"])
        self.assertEqual(caught.exception.code, "asset_not_found")

    def test_archive_traversal_is_rejected_before_any_requested_media_is_written(self):
        for name in ("../escape.mp4", "/escape.mp4", "C:/escape.mp4", "folder\\escape.mp4"):
            with self.subTest(name=name):
                archive = self.archive([("safe.mp4", b"safe"), (name, b"bad")])
                with self.assertRaises(StudioError):
                    self.library.archive_extract(archive["id"], ["safe.mp4", name])
                self.assertFalse(self.import_path(archive, "safe.mp4").exists())
                self.assertFalse((self.base / "escape.mp4").exists())

    def test_archive_symlinks_and_external_presets_are_not_executed_or_imported(self):
        symlink = zipfile.ZipInfo("link.mp4")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.archive([(symlink, b"/outside.mp4"), ("preset.ffx", b"external-effect")])
        for member in ("link.mp4", "preset.ffx"):
            with self.subTest(member=member), self.assertRaises(StudioError):
                self.library.archive_extract(archive["id"], [member])
        self.assertFalse(self.import_path(archive, "link.mp4").exists())

    def test_archive_destination_symlink_cannot_write_outside_media_root(self):
        archive = self.archive([("clip.mp4", b"video")])
        external = self.base / "external"
        external.mkdir()
        (self.config.media_root / "MontageImports").symlink_to(external, target_is_directory=True)
        with self.assertRaises(StudioError):
            self.library.archive_extract(archive["id"], ["clip.mp4"])
        self.assertEqual(list(external.iterdir()), [])

    def test_same_size_different_archive_destination_is_not_silently_accepted(self):
        archive = self.archive([("clip.mp4", b"ARCHIVE")])
        target = self.import_path(archive, "clip.mp4")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"CHANGED")
        with self.assertRaises(StudioError):
            self.library.archive_extract(archive["id"], ["clip.mp4"])
        self.assertEqual(target.read_bytes(), b"CHANGED")

    def test_import_never_deletes_preexisting_staging_filename(self):
        archive = self.archive([("clip.mp4", b"ARCHIVE")])
        target = self.import_path(archive, "clip.mp4")
        target.parent.mkdir(parents=True)
        staging = target.with_name(target.name + ".importing")
        staging.write_bytes(b"A preexisting user file")
        try:
            imported = self.library.archive_extract(archive["id"], ["clip.mp4"])
        finally:
            self.assertTrue(staging.exists(), "Import deleted a file it did not create")
            self.assertEqual(staging.read_bytes(), b"A preexisting user file")
        self.assertEqual(len(imported["assets"]), 1)
        self.assertEqual(target.read_bytes(), b"ARCHIVE")

    def test_identical_archive_reimport_preserves_content_and_identity(self):
        archive = self.archive([("Subfolder/clip.mp4", b"ARCHIVE")])
        first = self.library.archive_extract(archive["id"], ["Subfolder/clip.mp4"])
        second = self.library.archive_extract(archive["id"], ["Subfolder/clip.mp4"])
        self.assertEqual(first["assets"][0]["id"], second["assets"][0]["id"])
        self.assertEqual(Path(second["assets"][0]["path"]).read_bytes(), b"ARCHIVE")

    def test_destination_created_during_import_is_not_overwritten(self):
        from montage_studio import assets as assets_module

        archive = self.archive([("clip.mp4", b"ARCHIVE")])
        target = self.import_path(archive, "clip.mp4")
        real_link = assets_module.os.link

        def publish(source, destination):
            Path(destination).write_bytes(b"CHANGED")
            return real_link(source, destination)

        with patch.object(assets_module.os, "link", side_effect=publish), self.assertRaises(StudioError):
            self.library.archive_extract(archive["id"], ["clip.mp4"])
        self.assertEqual(target.read_bytes(), b"CHANGED")
        self.assertEqual(list(target.parent.glob(".montage-import-*")), [])


class ProjectStorageTests(StorageCase):
    def test_revision_conflict_history_and_restore_preserve_previous_documents(self):
        original = self.projects.create("Original")
        edited = copy.deepcopy(original)
        edited["name"] = "Changed"
        edited["created_at"] = "spoofed"
        saved = self.projects.save(edited, 0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["created_at"], original["created_at"])
        snapshot = self.snapshot()
        with self.assertRaises(StudioError) as caught:
            self.projects.save(original, 0)
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.snapshot(), snapshot)
        restored = self.projects.restore(original["id"], 0, 1)
        self.assertEqual(restored["revision"], 2)
        self.assertEqual(restored["name"], "Original")
        history = self.projects.history(original["id"])["revisions"]
        self.assertEqual([entry["revision"] for entry in history], [2, 1, 0])
        old = self.config.history_dir / original["id"] / "1.json"
        self.assertEqual(json.loads(old.read_text())["name"], "Changed")

    def test_concurrent_editors_cannot_silently_overwrite_each_other(self):
        original = self.projects.create("Original")

        def save(name):
            draft = copy.deepcopy(original)
            draft["name"] = name
            try:
                return self.projects.save(draft, 0)
            except StudioError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ("Editor A", "Editor B")))
        successes = [value for value in results if isinstance(value, dict)]
        failures = [value for value in results if isinstance(value, StudioError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, "revision_conflict")
        self.assertEqual(self.projects.get(original["id"])["name"], successes[0]["name"])

    def test_failing_multi_operation_edit_has_no_partial_persistent_write(self):
        original = self.projects.create("Original")
        before = self.snapshot()
        with self.assertRaises(StudioError):
            self.projects.edit(original["id"], 0, [{"op": "rename", "name": "Partial"}, {"op": "unknown-action"}])
        self.assertEqual(self.snapshot(), before)

    def test_invalid_documents_and_identifiers_preserve_current_project(self):
        original = self.projects.create("Original")
        before = self.snapshot()
        for changes in ({"name": ""}, {"canvas": {"width": 301}}, {"markers": [{"time": float("nan")}]}, {"titles": [{"id": "t"}, {"id": "t"}]}):
            with self.subTest(changes=changes), self.assertRaises(StudioError):
                self.projects.save(original | changes, 0)
        with self.assertRaises(StudioError):
            self.projects.get("../escape")
        self.assertEqual(self.snapshot(), before)

    def test_montage_failures_do_not_leave_empty_projects(self):
        footage = self.asset("footage.mp4")
        too_short = self.asset("short.mp4", metadata={"duration": 0.01, "has_audio": True, "has_video": True})
        music = self.asset("music.wav", metadata={"duration": 3, "has_audio": True, "has_video": False})
        image = self.asset("overlay.png", metadata={"duration": 0, "has_audio": False, "has_video": True})
        preset = self.asset("preset.ffx")
        invalid = [
            {"asset_ids": [footage["id"]], "music_asset_id": music["id"], "beat_offset": 4},
            {"asset_ids": [footage["id"]], "duration": 60, "bpm": 300, "beats_per_cut": 0.25},
            {"asset_ids": [too_short["id"]]},
            {"asset_ids": [footage["id"]], "music_asset_id": image["id"]},
            {"asset_ids": [footage["id"]], "music_asset_id": "missing"},
            {"asset_ids": [preset["id"]]},
            {"asset_ids": [music["id"]]},
        ]
        for args in invalid:
            with self.subTest(args=args):
                before = self.snapshot()
                with self.assertRaises(StudioError):
                    self.projects.montage("Invalid montage", **args)
                self.assertEqual(self.snapshot(), before, "A failed montage created a persistent partial project")

    def test_montage_validates_assembled_project_before_first_write(self):
        footage = self.asset("footage.mp4")
        self.engine.validate_project = lambda *args: {"valid": False, "errors": ["Unsupported render setting"], "warnings": []}
        before = self.snapshot()
        with self.assertRaises(StudioError):
            self.projects.montage("Rejected", [footage["id"]], duration=4)
        self.assertEqual(self.snapshot(), before)

    def test_valid_montage_persists_full_timeline_and_looped_audio(self):
        footage = self.asset("footage.mp4")
        music = self.asset("music.wav", metadata={"duration": 3, "has_audio": True, "has_video": False})
        project = self.projects.montage("Montage", [footage["id"]], music_asset_id=music["id"], duration=8, bpm=120, beats_per_cut=4)
        saved = self.projects.get(project["id"])
        self.assertEqual(saved, project)
        self.assertEqual(len(project["clips"]), 4)
        self.assertAlmostEqual(self.engine.project_duration(project), 8)
        self.assertTrue(project["audio"][0]["loop"])
        self.assertEqual(project["audio"][0]["duration"], 8)
        self.assertTrue(all(clip["volume"] == 0 for clip in project["clips"]))


class EngineStorageContractTests(unittest.TestCase):
    def test_real_engine_allows_saving_empty_projects(self):
        try:
            engine = importlib.import_module("montage_studio.engine")
        except ModuleNotFoundError:
            self.skipTest("Render engine is not installed yet")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            media = base / "Editing"
            media.mkdir()
            config = Config(media, media / "MontageStudio", base / "state")
            config.ensure()
            library = AssetLibrary(config)
            projects = ProjectStore(config, library)
            project = projects.create("Empty")
            validation = engine.validate_project(project, library.get)
            self.assertTrue(validation["valid"], validation)
            self.assertEqual(projects.save(project, 0)["revision"], 1)


if __name__ == "__main__":
    unittest.main()
