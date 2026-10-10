"""Real-output equivalence and scheduler regressions for bounded alpha batches."""
from __future__ import annotations

from array import array
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from montage_studio import engine


def ffmpeg(*args):
    result = subprocess.run([engine.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                             "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1",
                             *map(str, args)], capture_output=True, timeout=40)
    if result.returncode:
        raise AssertionError(result.stderr.decode())
    return result.stdout


@unittest.skipUnless(shutil.which(engine.FFMPEG) and shutil.which(engine.FFPROBE), "FFmpeg required")
class OverlayBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="framedrop-overlay-batches-")
        cls.root = Path(cls.temp.name)
        base = cls.root/"base.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=blue:s=160x96:r=30:d=7.1",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=7.1",
               "-c:v", "libx264", "-c:a", "aac", "-shortest", base)
        png = cls.root/"half-red.png"
        ffmpeg("-f", "lavfi", "-i", "color=red@0.5:s=40x24:r=12:d=1,format=rgba",
               "-frames:v", "1", "-c:v", "png", png)
        prores = cls.root/"half-green.mov"
        ffmpeg("-f", "lavfi", "-i", "color=lime@0.5:s=40x24:r=8:d=0.5,format=rgba",
               "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", prores)
        animated = cls.root/"animated.gif"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=40x24:r=8:d=0.5", animated)
        cls.assets = {"base": {"path": str(base), "kind": "video"},
                      "png": {"path": str(png), "kind": "image"},
                      "prores": {"path": str(prores), "kind": "video"},
                      "gif": {"path": str(animated), "kind": "image"}}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = self.root/self._testMethodName
        self.case.mkdir()

    def project(self, duration=3, fps=12):
        return {"canvas": {"width": 160, "height": 96, "fps": fps},
                "clips": [{"asset_id": "base", "in": 0, "out": duration}],
                "overlays": [], "normalize_audio": False}

    def overlay(self, **changed):
        return {"asset_id": "png", "start": .5, "duration": 1, "width": .5,
                "x": 0, "y": 0, "opacity": 1, "blend": "normal", **changed}

    def render(self, project, name, batch_size):
        started = time.monotonic()
        with patch.object(engine, "NORMAL_OVERLAY_BATCH_SIZE", batch_size):
            return engine.render_project(project, self.assets.__getitem__, self.case/(name+".mp4"), self.case/name,
                                         cancelled=lambda: time.monotonic()-started > 25)

    def frame(self, path, at):
        return ffmpeg("-ss", f"{at:.9f}", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")

    def audio(self, path):
        return ffmpeg("-i", path, "-vn", "-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:1")

    def compare(self, project, times):
        batched = self.render(project, "batch", 4)
        reference = self.render(project, "single", 1)
        self.assertAlmostEqual(batched["duration"], reference["duration"], delta=.001)
        self.assertEqual(self.audio(batched["path"]), self.audio(reference["path"]), "Overlay batching must not change base audio")
        for when in times:
            with self.subTest(time=when):
                actual, expected = self.frame(batched["path"], when), self.frame(reference["path"], when)
                self.assertEqual(len(actual), 160*96*3)
                self.assertEqual(len(actual), len(expected))
                # Eliminating intermediate H.264 encodes intentionally changes
                # compression noise; geometry, colors and alpha should agree.
                self.assertLess(sum(abs(a-b) for a, b in zip(actual, expected))/len(actual), 3)
        return batched, reference

    def test_timed_png_and_prores_batches_match_single_pass_layers(self):
        project = self.project()
        project["overlays"] = [
            self.overlay(),
            self.overlay(asset_id="prores", start=1, duration=1.5, **{"in": .125}, x=1, y=0),
            self.overlay(asset_id="prores", start=.25, duration=2, **{"in": .125}, loop=True, width=.25, x=.5, y=1),
            self.overlay(start=2, duration=2, width=1, opacity=.2),
            self.overlay(start=4, duration=1),  # skipped, no effect on batching
            self.overlay(start=1, duration=.75, width=.1, x=.8, y=.8, opacity=.3),
            self.overlay(start=1.5, duration=.5, width=.1, x=.8, y=.1, opacity=0),
        ]
        batched, _ = self.compare(project, (0, .3333333, .75, 1.1666666, 1.6666666, 2.1666666, 2.8333333))
        commands = [json.loads(line) for line in (self.case/"batch/commands.jsonl").read_text().splitlines()]
        composite = [item for item in commands if item["message"].startswith("Compositing")]
        self.assertEqual(len(composite), 2, "Six active layers need two bounded batches")
        self.assertTrue(all(item["argv"].count("-i") <= 5 for item in composite))
        # Explicit pixels catch a shared error in both render paths: a half-red
        # PNG must retain alpha, while finite ProRes disappears after source EOF.
        during = self.frame(batched["path"], .75)
        offset = (10*160+10)*3
        self.assertGreater(during[offset], 90)
        self.assertGreater(during[offset+2], 90)
        before_end = self.frame(batched["path"], 1.1666666)
        after_end = self.frame(batched["path"], 1.6666666)
        right = (10*160+150)*3
        self.assertGreater(before_end[right+1], 80)
        self.assertLess(after_end[right+1], 10)

    def test_non_normal_blends_remain_ordered_single_layer_passes(self):
        project = self.project()
        project["overlays"] = [self.overlay(start=0, duration=3),
                               self.overlay(start=0, duration=3, x=1),
                               self.overlay(start=.5, duration=1, blend="screen", width=1),
                               self.overlay(start=1, duration=1.5, x=.5),
                               self.overlay(start=1, duration=1.5, blend="chroma", key_color="#00ff00", x=1),
                               self.overlay(start=2, duration=.5, x=.5),
                               self.overlay(start=2, duration=.5, x=1)]
        self.compare(project, (.25, .75, 1.25, 1.75, 2.25, 2.75))
        commands = [json.loads(line) for line in (self.case/"batch/commands.jsonl").read_text().splitlines()]
        self.assertEqual(sum(item["message"].startswith("Compositing") for item in commands), 5)

    def test_late_alpha_layers_with_base_audio_do_not_deadlock(self):
        project = self.project(duration=7.1, fps=30)
        project["canvas"] = {"width": 96, "height": 160, "fps": 30}
        project["overlays"] = [self.overlay(asset_id="prores", start=4.1, duration=.75, width=1.8, opacity=.5),
                               self.overlay(start=4.2, duration=1, x=1, opacity=.7),
                               self.overlay(asset_id="prores", start=5.5, duration=.75, loop=True, y=1),
                               self.overlay(start=6.5, duration=.6, width=1, opacity=.4)]
        result = self.render(project, "late", 4)
        self.assertAlmostEqual(result["duration"], 7.1, delta=.05)
        samples = array("h"); samples.frombytes(self.audio(result["path"]))
        self.assertGreater(max(map(abs, samples)), 1000)
        commands = [json.loads(line) for line in (self.case/"late/commands.jsonl").read_text().splitlines()]
        batch = next(item for item in commands if item["message"].startswith("Compositing"))
        graph = batch["argv"][batch["argv"].index("-filter_complex")+1]
        self.assertEqual(graph.count("tpad=start_mode=add"), 4)

    def test_fractional_fps_gif_loop_and_negative_overlay_position_match(self):
        project = self.project(duration=2, fps=23.976)
        project["overlays"] = [self.overlay(asset_id="gif", start=.4, duration=1.2, loop=True, width=.5),
                               self.overlay(start=.25, duration=1.25, width=1.8, x=1, y=1),
                               self.overlay(asset_id="gif", start=.8, duration=1, loop=False, width=.4, x=1)]
        self.compare(project, (.1, .5, .9, 1.4, 1.8))

    def test_full_duration_png_and_loop_survive_final_frame_after_concat_rounding(self):
        project = self.project(duration=1, fps=60)
        # Each 203-frame MKV section rounds to 3.384s; the concatenated last
        # frame is at 35.490s rather than nominal 35.483333s. Without coverage
        # beyond the requested input duration, framesync selects transparent
        # padding for the final output frame, dropping the image/loop layer.
        project["clips"] = [{"asset_id": "base", "in": 0, "out": 1,
                              "freeze": {"time": 0, "duration": frames/60}}
                             for frames in [203]*10+[100]]
        project["overlays"] = [self.overlay(start=0, duration=35.5),
                               self.overlay(asset_id="prores", start=0, duration=35.5, loop=True, x=1)]
        for batch_size in (1, 4):
            with self.subTest(batch_size=batch_size):
                result = self.render(project, f"last-frame-{batch_size}", batch_size)
                self.assertAlmostEqual(result["duration"], 35.5, delta=.001)
                raw = ffmpeg("-i", result["path"], "-vf", "select=gte(n\\,2128)", "-vsync", "0",
                             "-frames:v", "2", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
                frame_size = 160*96*3
                self.assertEqual(len(raw), frame_size*2)
                for frame in range(2):
                    left = frame*frame_size+(10*160+10)*3
                    right = frame*frame_size+(10*160+150)*3
                    self.assertGreater(raw[left], 90, "PNG must cover the actual final output frame")
                    self.assertGreater(raw[right+1], 90, "Loop must cover the actual final output frame")


if __name__ == "__main__":
    unittest.main()
