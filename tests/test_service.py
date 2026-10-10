"""Focused end-to-end checks of HTTP, CLI/MCP and real render workers."""

from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from montage_studio.config import Config, StudioError, atomic_json, utcnow
from montage_studio.engine import probe
from montage_studio.service import Service
from montage_studio.web import StudioHTTPServer, StudioHandler


SOURCE = Path(__file__).resolve().parents[1]


def process_state(pid):
    try:
        return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


try:
    NATIVE_PROC = int(Path("/proc/self/stat").read_text().split(" ", 1)[0]) == os.getpid()
except (OSError, ValueError):
    NATIVE_PROC = False


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe are required")
class ServiceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.video_fixture = Path(cls.fixture_directory.name) / "source.mp4"
        cls.image_fixture = Path(cls.fixture_directory.name) / "still.png"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
             "-ac", "2", "-shortest", "-threads", "1", "-y", str(cls.video_fixture)],
            check=True, capture_output=True, timeout=20,
        )
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(cls.video_fixture), "-frames:v", "1", "-threads", "1", "-y", str(cls.image_fixture)],
            check=True, capture_output=True, timeout=15,
        )

    @classmethod
    def tearDownClass(cls):
        cls.fixture_directory.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        media = self.base / "Editing"
        media.mkdir()
        shutil.copyfile(self.video_fixture, media / "source.mp4")
        shutil.copyfile(self.image_fixture, media / "still.png")
        self.config = Config(media, media / "MontageStudio", self.base / "state", threads=2)
        self.service = Service(self.config)
        self.service.call("library_scan", {})
        assets = self.service.call("assets_list", {})["items"]
        self.video = next(asset for asset in assets if asset["name"] == "source.mp4")
        self.still = next(asset for asset in assets if asset["name"] == "still.png")
        self.workers = set()
        self.log_patch = patch.object(StudioHandler, "log_message", return_value=None)
        self.log_patch.start()
        self.server = StudioHTTPServer(("127.0.0.1", 0), self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        status, _, body = self.http("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.bootstrap = json.loads(body)
        self.token = self.bootstrap["csrf_token"]
        self.config_path = self.base / "config.json"
        atomic_json(self.config_path, self.config.as_dict())
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith("MONTAGE_")}
        self.environment["MONTAGE_CONFIG"] = str(self.config_path)
        self.environment["PYTHONPATH"] = str(SOURCE) + os.pathsep + self.environment.get("PYTHONPATH", "")
        # Some executors expose host /proc with virtualized child PIDs. Record
        # the actual child PID before exec so cancellation checks remain real
        # process tests without relying on a matching /proc namespace.
        self.ffmpeg_pids = self.base/"ffmpeg-pids.jsonl"
        self.ffmpeg_wrapper = self.base/"tracked-ffmpeg"
        ffmpeg = shutil.which("ffmpeg")
        self.ffmpeg_wrapper.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            f"with open({str(self.ffmpeg_pids)!r}, 'a') as log:\n"
            "    log.write(json.dumps({'pid': os.getpid(), 'parent': os.getppid()})+'\\n')\n"
            f"os.execv({ffmpeg!r}, [{ffmpeg!r}]+sys.argv[1:])\n"
        )
        self.ffmpeg_wrapper.chmod(0o755)
        self.environment["MONTAGE_FFMPEG"] = str(self.ffmpeg_wrapper)

    def tearDown(self):
        # Only process groups created by this test are touched. A failed
        # assertion must not leave its long synthetic export running.
        for pid in self.workers:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 4
        waiting = set(self.workers)
        while waiting and time.monotonic() < deadline:
            for pid in tuple(waiting):
                try:
                    reaped, _ = os.waitpid(pid, os.WNOHANG)
                    if reaped: waiting.remove(pid)
                except ChildProcessError:
                    waiting.remove(pid)
            if waiting: time.sleep(.05)
        for pid in waiting:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.log_patch.stop()
        self.temporary.cleanup()

    def http(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
        finally:
            connection.close()

    def api(self, tool, arguments=None, headers=None):
        request_headers = {"Content-Type": "application/json", "X-Montage-Token": self.token, "Origin": self.origin}
        request_headers.update(headers or {})
        status, _, data = self.http("POST", "/api/call", json.dumps({"tool": tool, "arguments": arguments or {}}), request_headers)
        return status, json.loads(data)

    def cli(self, *arguments, input=None, timeout=20):
        return subprocess.run(
            [sys.executable, "-m", "montage_studio", *arguments], cwd=SOURCE, env=self.environment,
            input=input, capture_output=True, text=True, timeout=timeout,
        )

    def project(self, name="Fixture edit", long=False):
        project = self.service.call("project_create", {"name": name, "width": 1280 if long else 320, "height": 720 if long else 180, "fps": 30 if long else 15})
        return self.service.call("project_edit", {
            "project_id": project["id"], "expected_revision": project["revision"],
            "operations": [{"op": "add_clip", "clip": {"asset_id": (self.still if long else self.video)["id"], "in": 0, "out": 120 if long else 1.6}}],
        })

    def start(self, project, quality="preview"):
        with patch.dict(os.environ, {"MONTAGE_FFMPEG": str(self.ffmpeg_wrapper)}):
            status, body = self.api("render_start", {"project_id": project["id"], "quality": quality})
        self.assertEqual(status, 200, body)
        job = body["result"]
        self.workers.add(job["pid"])
        return job

    def wait_job(self, job_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, body = self.api("job_status", {"job_id": job_id})
            self.assertEqual(status, 200, body)
            job = body["result"]
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(.1)
        self.fail(f"Worker did not finish: {self.service.jobs.get(job_id)}")

    def wait_ffmpeg(self, job, timeout=12):
        deadline = time.monotonic() + timeout
        pid = job["pid"]
        while time.monotonic() < deadline:
            current = self.service.jobs.get(job["id"])
            self.assertIn(current["status"], {"queued", "running"}, current)
            if self.ffmpeg_pids.exists() and current["progress"] > 0:
                for line in self.ffmpeg_pids.read_text().splitlines():
                    child = json.loads(line)
                    if child["parent"] == pid and process_exists(child["pid"]):
                        return child["pid"]
            time.sleep(.03)
        self.fail("The real render worker never launched FFmpeg")

    def test_http_bootstrap_access_guards_and_actionable_api_errors(self):
        self.assertGreater(len(self.token), 30)
        self.assertEqual(self.bootstrap["status"]["app"], "Framedrop")
        self.assertEqual(self.bootstrap["assets"]["total"], 2)
        self.assertGreater(len(self.bootstrap["effects"]), 10)
        for headers, expected_status, code in (
            ({"X-Montage-Token": ""}, 403, "invalid_token"),
            ({"Origin": "https://external.example"}, 403, "invalid_origin"),
            ({"Host": f"external.example:{self.port}"}, 421, "invalid_host"),
            ({"Content-Type": "text/plain"}, 415, "invalid_content_type"),
        ):
            with self.subTest(code=code):
                status, response = self.api("project_create", {"name": "Blocked"}, headers)
                self.assertEqual(status, expected_status)
                self.assertEqual(response["code"], code)
        self.assertEqual(self.service.projects.list(), [])
        status, response = self.api("project_create", {})
        self.assertEqual(status, 400)
        self.assertIn("Missing required field", response["error"])
        status, response = self.api("no_such_tool", {})
        self.assertEqual(status, 404)
        self.assertEqual(response["code"], "unknown_tool")
        status, response = self.api("project_create", {"name": "Allowed"})
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        status, headers, body = self.http("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn(b"<html", body.lower())
        status, _, _ = self.http("GET", "/api/bootstrap", headers={"Host": "outside.example"})
        self.assertEqual(status, 421)

    def test_http_media_byte_ranges_suffix_invalid_and_head(self):
        source = Path(self.video["path"]).read_bytes()
        path = "/api/media?id=" + self.video["id"]
        cases = (("bytes=0-9", source[:10], 0, 9), ("bytes=10-", source[10:], 10, len(source)-1), ("bytes=-7", source[-7:], len(source)-7, len(source)-1), (f"bytes=-{len(source)+100}", source, 0, len(source)-1))
        for byte_range, expected, start, end in cases:
            with self.subTest(byte_range=byte_range):
                status, headers, body = self.http("GET", path, headers={"Range": byte_range})
                self.assertEqual(status, 206)
                self.assertEqual(body, expected)
                self.assertEqual(headers["content-range"], f"bytes {start}-{end}/{len(source)}")
                self.assertEqual(int(headers["content-length"]), len(expected))
        for byte_range in ("bytes=-0", "bytes=9-2", f"bytes={len(source)}-", "bytes=", "bytes=0-1,4-5", "invalid"):
            with self.subTest(byte_range=byte_range):
                status, headers, body = self.http("GET", path, headers={"Range": byte_range})
                self.assertEqual(status, 416)
                self.assertEqual(headers["content-range"], f"bytes */{len(source)}")
                self.assertEqual(body, b"")
        status, headers, body = self.http("HEAD", path)
        self.assertEqual(status, 200)
        self.assertEqual(int(headers["content-length"]), len(source))
        self.assertEqual(body, b"")
        Path(self.video["path"]).unlink()
        status, _, body = self.http("GET", path)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["code"], "asset_missing")

    def test_cli_and_mcp_subprocesses_emit_parseable_json_and_real_tools(self):
        cli_tools = self.cli("tools")
        self.assertEqual(cli_tools.returncode, 0, cli_tools.stderr)
        tool_names = {tool["name"] for tool in json.loads(cli_tools.stdout)["tools"]}
        self.assertIn("render_start", tool_names)
        created = self.cli("call", "project_create", "--json", json.dumps({"name": "CLI project"}))
        self.assertEqual(created.returncode, 0, created.stderr)
        project = json.loads(created.stdout)
        self.assertEqual(project["name"], "CLI project")
        invalid = self.cli("call", "project_create", "--json", "{}")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse(json.loads(invalid.stdout)["ok"])
        transcript = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "integration", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_get", "arguments": {"project_id": project["id"]}}},
        ]
        completed = self.cli("mcp", input="".join(json.dumps(message)+"\n" for message in transcript))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([value["id"] for value in responses], [1, 2, 3])
        self.assertEqual({tool["name"] for tool in responses[1]["result"]["tools"]}, tool_names)
        self.assertEqual(responses[2]["result"]["structuredContent"], project)

    def test_async_export_survives_cli_exit_uses_snapshot_and_preserves_source(self):
        project = self.project()
        original_hash = hashlib.sha256(Path(self.video["path"]).read_bytes()).hexdigest()
        status, response = self.api("render_plan", {"project_id": project["id"]})
        self.assertEqual(status, 200, response)
        self.assertAlmostEqual(response["result"]["duration"], 1.6, places=2)
        self.assertEqual(self.service.jobs.list(), [])
        started = self.cli("call", "render_start", "--json", json.dumps({"project_id": project["id"]}))
        self.assertEqual(started.returncode, 0, started.stderr)
        job = json.loads(started.stdout)
        self.workers.add(job["pid"])
        self.assertIn(job["status"], {"queued", "running"})
        self.assertNotEqual(job["pid"], os.getpid())
        self.service.call("project_edit", {"project_id": project["id"], "expected_revision": project["revision"], "operations": [{"op": "rename", "name": "Later unsnapshotted edit"}]})
        finished = self.wait_job(job["id"])
        self.assertEqual(finished["status"], "completed", finished)
        self.assertEqual(finished["revision"], project["revision"])
        self.assertEqual(finished["project_name"], project["name"])
        output = Path(finished["output_path"])
        self.assertTrue(output.is_file())
        self.assertNotEqual(output, Path(self.video["path"]))
        result = probe(str(output))
        self.assertEqual(result["video_codec"], "h264")
        self.assertEqual(result["audio_codec"], "aac")
        self.assertAlmostEqual(result["duration"], 1.6, delta=.15)
        self.assertEqual(hashlib.sha256(Path(self.video["path"]).read_bytes()).hexdigest(), original_hash)
        status, headers, body = self.http("GET", "/api/output?job="+job["id"], headers={"Range": "bytes=0-31"})
        self.assertEqual(status, 206)
        self.assertEqual(body, output.read_bytes()[:32])
        self.assertEqual(headers["content-type"], "video/mp4")
        deadline = time.monotonic() + 5
        log_manifest = self.service.jobs.directory(job["id"])/"render-logs"/"commands.jsonl"
        while not log_manifest.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertTrue(log_manifest.exists(), "Export command manifest was lost during cleanup")

    def test_cancelling_live_ffmpeg_stops_children_and_removes_partial_output(self):
        project = self.project("Cancel fixture", long=True)
        job = self.start(project, "final")
        child_pid = self.wait_ffmpeg(job)
        status, response = self.api("render_start", {"project_id": project["id"]})
        self.assertEqual(status, 409)
        self.assertEqual(response["code"], "render_busy")
        status, response = self.api("job_cancel", {"job_id": job["id"]})
        self.assertEqual(status, 200, response)
        finished = self.wait_job(job["id"], timeout=15)
        self.assertEqual(finished["status"], "cancelled", finished)
        self.assertFalse(Path(finished["output_path"]).exists())
        deadline = time.monotonic() + 5
        intermediate = self.config.cache_dir/"renders"/job["id"]
        while (intermediate.exists() or process_exists(child_pid)) and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(intermediate.exists(), "Cancelled render retained intermediate media")
        self.assertFalse(process_exists(child_pid), "Cancelled FFmpeg child is still alive")
        status, _, body = self.http("GET", "/api/output?job="+job["id"])
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "output_not_ready")
        self.assertTrue(Path(self.still["path"]).is_file())

    def test_crashed_worker_zombie_is_failed_and_does_not_block_next_export(self):
        project = self.project("Crash fixture", long=True)
        job = self.start(project, "final")
        self.wait_ffmpeg(job)
        os.killpg(job["pid"], signal.SIGKILL)
        if NATIVE_PROC:
            deadline = time.monotonic() + 5
            while process_state(job["pid"]) not in (None, "Z", "X") and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertIn(process_state(job["pid"]), (None, "Z", "X"))
            # A native Linux /proc lets this cover the unreaped zombie case.
        else:
            # Executor /proc PID namespaces can differ. Reap here; the separate
            # deterministic state tests cover zombie detection and its race.
            os.waitpid(job["pid"], 0)
        reconciled = self.service.call("job_status", {"job_id": job["id"]})
        self.assertEqual(reconciled["status"], "failed", reconciled)
        next_job = self.start(project, "final")
        self.assertNotEqual(next_job["id"], job["id"])
        self.service.call("job_cancel", {"job_id": next_job["id"]})
        self.assertEqual(self.wait_job(next_job["id"])["status"], "cancelled")

    def test_stale_reconciliation_preserves_a_concurrent_completed_status(self):
        from montage_studio import jobs as jobs_module

        jid = "job_race_fixture"
        directory = self.service.jobs.directory(jid)
        atomic_json(directory/"job.json", {"id": jid, "status": "running", "pid": os.getpid(), "created_at": utcnow(), "updated_at": utcnow(), "progress": .9})

        def completes_before_liveness_returns(pid):
            self.service.jobs.update(jid, status="completed", progress=1, message="Render complete")
            return "Z", None

        with patch.object(jobs_module, "process_identity", side_effect=completes_before_liveness_returns):
            job = self.service.jobs.get(jid)
        self.assertEqual(job["status"], "completed", "Stale detection overwrote a newer successful completion")

    def test_abandoned_queued_job_without_pid_recovers_after_startup_grace(self):
        jid = "job_abandoned_fixture"
        created = (datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
        atomic_json(self.service.jobs.directory(jid)/"job.json", {"id": jid, "status": "queued", "created_at": created, "updated_at": created, "progress": 0})
        self.assertEqual(self.service.jobs.get(jid)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
