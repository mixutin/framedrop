"""Import preservation, optional cutout lifecycle, and cached model selection.

Media decoding/indexing and persistent job files are real. Neural inference and
process launch are substituted so this suite never downloads models or needs
optional packages; live inference is a separate installation smoke check.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from montage_studio import media_tools, shapes, transcription
from montage_studio.config import Config, StudioError, atomic_json, utcnow
from montage_studio.projects import new_id
from montage_studio.service import Service


class MediaToolsCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="framedrop-media-tests-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        media = self.base/"media"
        media.mkdir()
        self.config = Config(media, media/"workspace", self.base/"state", threads=1)
        self.service = Service(self.config)
        self.source = shapes.render_shape({"kind":"arrow", "duration":1, "x":.1, "y":.1, "x2":.9, "y2":.9},
                                          64, 64, self.base/"source.png")
        self.source_bytes = self.source.read_bytes()

    def import_source(self):
        return self.service.call("asset_import", {"path":str(self.source)})

    def cutout_ready(self):
        root = self.base/"cutout-models"
        model = root/"isnet-general-use"/"isnet-general-use.onnx"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"Inference is replaced in this test.")
        settings = {"python":sys.executable, "model_dir":str(root), "model":"isnet-general-use"}
        atomic_json(self.config.state_dir/"background-removal.json", settings)
        return settings

    def queue_cutout(self, asset):
        self.service.library.probe(asset["id"])
        process = SimpleNamespace(pid=os.getpid(), wait=lambda:0)
        with patch.object(media_tools.subprocess, "Popen", return_value=process), patch.object(media_tools.threading, "Thread"):
            return self.service.call("image_background_remove", {"asset_id":asset["id"]})

    def model_modules(self):
        image = SimpleNamespace(width=64, height=64)
        image.convert = Mock(return_value=image)
        image.close = Mock()
        image.__enter__ = Mock(return_value=image)
        image.__exit__ = Mock(return_value=False)
        cutout = SimpleNamespace(save=lambda handle, format: handle.write(self.source_bytes))
        rembg = SimpleNamespace(new_session=Mock(return_value="local session"), remove=Mock(return_value=cutout))
        pil = SimpleNamespace(Image=SimpleNamespace(open=Mock(return_value=image)))
        return {"rembg":rembg, "PIL":pil}, rembg


class AssetImportTests(MediaToolsCase):
    def test_import_preserves_original_and_indexes_copy(self):
        before = self.source.stat()
        result = self.import_source()
        target = Path(result["path"])
        self.assertTrue(target.is_relative_to(self.config.media_root))
        self.assertNotEqual(target, self.source)
        self.assertEqual(target.read_bytes(), self.source_bytes)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertEqual(self.source.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(result["kind"], "image")
        self.assertEqual(self.service.library.get(result["id"])["path"], str(target))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_extensionless_jpeg_is_detected_and_decodes_after_import(self):
        source = self.base/"jpeg"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.source), "-frames:v", "1", "-threads", "1",
                        "-f", "image2", "-c:v", "mjpeg", str(source)], check=True, capture_output=True, timeout=15)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        result = media_tools.import_asset(self.service.library, str(source))
        self.assertEqual(result["extension"], ".jpg")
        metadata = self.service.library.probe(result["id"])["metadata"]
        self.assertEqual((metadata["width"], metadata["height"]), (64, 64))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)

    def test_extensionless_png_and_existing_library_file(self):
        extensionless = self.base/"overlay"
        extensionless.write_bytes(self.source_bytes)
        result = media_tools.import_asset(self.service.library, str(extensionless))
        self.assertEqual(result["extension"], ".png")
        second = media_tools.import_asset(self.service.library, result["path"])
        self.assertEqual(second["id"], result["id"])
        self.assertEqual(self.service.library.list()["total"], 1)

    def test_invalid_paths_and_formats_are_rejected_without_imports(self):
        unknown = self.base/"script.py"
        unknown.write_text("print('This is not media')")
        empty = self.base/"empty.png"
        empty.touch()
        for path in ("relative.png", str(self.base), str(unknown), str(empty)):
            with self.subTest(path=path), self.assertRaises(StudioError):
                media_tools.import_asset(self.service.library, path)
        self.assertEqual(self.service.library.list()["total"], 0)

    def test_destination_collision_does_not_delete_existing_file(self):
        directory = self.config.media_root/"MontageImports"/"media"
        directory.mkdir(parents=True)
        collision = directory/"source-import_collision.png"
        collision.write_bytes(b"A user's existing file")
        with patch.object(media_tools, "new_id", return_value="import_collision"):
            with self.assertRaises((FileExistsError, StudioError)):
                self.import_source()
        self.assertTrue(collision.exists(), "Exclusive create failure must not delete a pre-existing file")
        self.assertEqual(collision.read_bytes(), b"A user's existing file")

    def test_import_symlink_escape_is_rejected_before_creating_directories(self):
        outside = self.base/"outside"
        outside.mkdir()
        (self.config.media_root/"MontageImports").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(StudioError) as caught:
            self.import_source()
        self.assertEqual(caught.exception.code, "path_not_allowed")
        self.assertEqual(list(outside.iterdir()), [], "Containment must be checked before mkdir")


@unittest.skipUnless(shutil.which("ffprobe"), "ffprobe required")
class CutoutLifecycleTests(MediaToolsCase):
    def test_unavailable_and_nested_model_status(self):
        self.assertFalse(media_tools.background_status(self.config)["model_ready"])
        with self.assertRaises(StudioError) as caught:
            media_tools.background_remove(self.service, "unknown")
        self.assertEqual(caught.exception.code, "cutout_unavailable")
        settings = self.cutout_ready()
        self.assertTrue(media_tools.background_status(self.config)["model_ready"])
        Path(settings["model_dir"], "isnet-general-use", "isnet-general-use.onnx").unlink()
        self.assertFalse(media_tools.background_status(self.config)["model_ready"])

    def test_queue_success_preserves_original_and_registers_new_png(self):
        self.cutout_ready()
        asset = self.import_source()
        job = self.queue_cutout(asset)
        self.assertEqual(job["kind"], "background_removal")
        self.assertEqual(job["status"], "queued")
        modules, rembg = self.model_modules()
        with patch.dict(sys.modules, modules), patch.dict(os.environ), patch.object(media_tools.traceback, "print_exc"):
            self.assertEqual(media_tools.run_cutout_worker(str(self.service.jobs.directory(job["id"]))), 0)
        result = self.service.jobs.get(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["progress"], 1)
        output = result["result"]["asset"]
        self.assertEqual(output["extension"], ".png")
        self.assertNotEqual(output["id"], asset["id"])
        self.assertEqual(Path(output["path"]).read_bytes(), self.source_bytes)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertEqual(Path(asset["path"]).read_bytes(), self.source_bytes)
        rembg.new_session.assert_called_once_with("isnet-general-use", providers=["CPUExecutionProvider"])

    def test_prelaunch_cancellation_never_loads_model_or_creates_output(self):
        self.cutout_ready()
        asset = self.import_source()
        job = self.queue_cutout(asset)
        self.service.jobs.cancel(job["id"])
        modules, rembg = self.model_modules()
        with patch.dict(sys.modules, modules), patch.dict(os.environ), patch.object(media_tools.traceback, "print_exc"):
            self.assertEqual(media_tools.run_cutout_worker(str(self.service.jobs.directory(job["id"]))), 0)
        self.assertEqual(self.service.jobs.get(job["id"])["status"], "cancelled")
        rembg.new_session.assert_not_called()
        self.assertEqual(self.service.library.list()["total"], 1)

    def test_cutout_collision_fails_without_deleting_existing_output(self):
        self.cutout_ready()
        job = self.queue_cutout(self.import_source())
        destination = self.config.media_root/"MontageImports"/"overlays"/f"cutout-{job['id']}.png"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"Existing user cutout")
        modules, _ = self.model_modules()
        with patch.dict(sys.modules, modules), patch.dict(os.environ), patch.object(media_tools.traceback, "print_exc"):
            self.assertEqual(media_tools.run_cutout_worker(str(self.service.jobs.directory(job["id"]))), 1)
        self.assertEqual(self.service.jobs.get(job["id"])["status"], "failed")
        self.assertTrue(destination.exists(), "Failed exclusive create must preserve the existing cutout")
        self.assertEqual(destination.read_bytes(), b"Existing user cutout")

    def test_active_job_blocks_another_cutout(self):
        self.cutout_ready()
        asset = self.import_source()
        first = self.queue_cutout(asset)
        with self.assertRaises(StudioError) as caught:
            self.queue_cutout(asset)
        self.assertEqual(caught.exception.code, "render_busy")
        self.assertEqual(len(self.service.jobs.list()), 1)
        self.service.jobs.update(first["id"], status="cancelled")


class TranscriptionModelSelectionTests(MediaToolsCase):
    def model_ready(self, default="base", models=("base", "small")):
        root = self.base/"speech-models"
        for model in models:
            snapshot = root/f"models--Systran--faster-whisper-{model}"/"snapshots"/"fixture"
            snapshot.mkdir(parents=True, exist_ok=True)
            for name in ("model.bin", "config.json", "tokenizer.json"):
                (snapshot/name).write_bytes(b"Cached fixture only")
        settings = {"python":sys.executable, "download_root":str(root), "installed":True,
                    "model_ready":True, "model":default}
        atomic_json(self.config.state_dir/"transcription.json", settings)
        return root

    def completed_preview(self):
        project = self.service.projects.create("Caption model test", 96, 64, 12)
        jid = new_id("job")
        directory = self.service.jobs.directory(jid)
        directory.mkdir()
        output = self.config.renders_dir/"preview.mp4"
        output.write_bytes(b"The inference worker is not launched by this test")
        job = {"id":jid, "kind":"render", "project_id":project["id"], "project_name":project["name"],
               "status":"completed", "created_at":utcnow(), "updated_at":utcnow(), "progress":1,
               "output_path":str(output), "quality":"preview"}
        atomic_json(directory/"job.json", job)
        atomic_json(directory/"project.json", project)
        return project, job

    def test_status_requires_all_selected_model_files_and_resolves_broken_links(self):
        root = self.model_ready()
        status = transcription.status(self.config)
        self.assertTrue(status["model_ready"])
        self.assertEqual(set(status["models"]), {"base", "small"})
        tokenizer = root/"models--Systran--faster-whisper-base"/"snapshots"/"fixture"/"tokenizer.json"
        tokenizer.unlink()
        tokenizer.symlink_to(root/"missing-tokenizer")
        status = transcription.status(self.config)
        self.assertFalse(status["model_ready"])
        self.assertNotIn("base", status["models"])

    def test_cached_model_override_is_saved_and_worker_stays_offline(self):
        self.model_ready()
        project, render = self.completed_preview()
        process = SimpleNamespace(pid=os.getpid(), wait=lambda:0)
        with patch.object(transcription.subprocess, "Popen", return_value=process) as launch, patch.object(transcription.threading, "Thread"):
            job = transcription.start(self.service, project["id"], render["id"], language="fi", model="small")
        self.assertEqual(job["model"], "small")
        self.assertEqual(job["language"], "fi")
        self.assertEqual(launch.call_args.kwargs["env"]["HF_HUB_OFFLINE"], "1")
        self.assertEqual(self.service.jobs.get(job["id"])["model"], "small")

    def test_cached_override_works_when_default_model_has_been_removed(self):
        self.model_ready(default="base", models=("small",))
        project, render = self.completed_preview()
        process = SimpleNamespace(pid=os.getpid(), wait=lambda:0)
        with patch.object(transcription.subprocess, "Popen", return_value=process), patch.object(transcription.threading, "Thread"):
            job = transcription.start(self.service, project["id"], render["id"], model="small")
        self.assertEqual(job["model"], "small")

    def test_uncached_or_unknown_model_is_rejected_before_job_creation(self):
        self.model_ready()
        project, render = self.completed_preview()
        before = self.service.jobs.list()
        for model in ("medium", "../../outside", "tiny", ""):
            with self.subTest(model=model), self.assertRaises(StudioError) as caught:
                transcription.start(self.service, project["id"], render["id"], model=model)
            self.assertEqual(caught.exception.code, "model_unavailable")
        self.assertEqual(self.service.jobs.list(), before)


if __name__ == "__main__":
    unittest.main()
