"""Rendered-fixture regressions for native stills and animation clocks."""
from __future__ import annotations

from array import array
import copy
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from montage_studio import automation, engine


def ffmpeg(*args):
    result = subprocess.run([engine.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                             "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1",
                             *map(str, args)], capture_output=True, timeout=40)
    if result.returncode:
        raise AssertionError(result.stderr.decode())
    return result.stdout


@unittest.skipUnless(shutil.which(engine.FFMPEG) and shutil.which(engine.FFPROBE), "FFmpeg required")
class AdvancedEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="framedrop-advanced-")
        cls.root = Path(cls.temp.name)
        video = cls.root/"moving-and-audible.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x96:rate=12:duration=3",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
               "-c:v", "libx264", "-c:a", "aac", "-shortest", video)
        still = cls.root/"two-colors.ppm"
        still.write_bytes(b"P6\n160 96\n255\n"+(bytes([255, 0, 0])*80+bytes([0, 0, 255])*80)*96)
        cls.assets = {"video": {"path": str(video), "kind": "video"},
                      "still": {"path": str(still), "kind": "image"}}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = self.root/self._testMethodName
        self.case.mkdir()

    def project(self):
        return {"canvas": {"width": 160, "height": 96, "fps": 12},
                "clips": [{"asset_id": "video", "in": 0, "out": 2}], "normalize_audio": False}

    def render(self, project, name="render"):
        return engine.render_project(project, self.assets.__getitem__, self.case/(name+".mp4"), self.case/name)

    def frame(self, path, at):
        return ffmpeg("-ss", at, "-i", path, "-frames:v", 1, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")

    def rms(self, path, at, length=.1):
        data = ffmpeg("-ss", at, "-i", path, "-t", length, "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1")
        samples = array("h"); samples.frombytes(data)
        self.assertGreater(len(samples), 100)
        return math.sqrt(sum(sample*sample for sample in samples)/len(samples))

    def test_freeze_holds_requested_frame_and_removes_source_audio(self):
        project = self.project()
        # Source selection is absolute, independent of trim and speed.
        project["clips"][0].update({"in": 0, "out": .5, "speed": 8,
                                     "freeze": {"time": 1.5, "duration": 1.25}})
        self.assertEqual(engine.clip_duration(project["clips"][0]), 1.25)
        result = self.render(project)
        self.assertAlmostEqual(result["duration"], 1.25, delta=.04)
        frames = [self.frame(result["path"], at) for at in (.0833333, .5, 1.0833333)]
        for frame in frames[1:]:
            self.assertLess(sum(abs(a-b) for a, b in zip(frame, frames[0]))/len(frame), .5)
        source = self.frame(self.assets["video"]["path"], 1.5)
        self.assertLess(sum(abs(a-b) for a, b in zip(source, frames[0]))/len(source), 8)
        self.assertLess(self.rms(result["path"], .5), 2)
        # Seeking inside the final frame must still produce a non-empty still.
        project["clips"][0]["freeze"] = {"time": 2.999, "duration": .25}
        final = self.render(project, "last-frame")
        self.assertEqual(len(self.frame(final["path"], 0)), 160*96*3)

    def test_motion_interpolates_across_retimed_segments(self):
        project = self.project()
        project["clips"] = [{"asset_id": "still", "in": 0, "out": 1,
                              "segments": [{"start": 0, "end": .5, "speed": .5},
                                           {"start": .5, "end": 1, "speed": 2}],
                              "transform": {"flip_x": True},
                              "motion": [{"time": 0, "zoom": 2, "x": 0, "y": .5},
                                         {"time": 1.25, "zoom": 2, "x": 1, "y": .5}]}]
        result = self.render(project)
        before, middle, after = (self.frame(result["path"], at) for at in (.0833333, .6666666, 1.1666666))
        center = (48*160+80)*3
        self.assertGreater(before[center+2], 200, "Static flip must be applied before animated pan")
        self.assertGreater(after[center], 200, "Animation clock must not reset at a speed boundary")
        self.assertNotEqual(before, middle)
        self.assertNotEqual(middle, after)

    def test_clip_volume_keyframes_use_output_time_after_retiming(self):
        project = self.project()
        project["clips"][0].update({"out": 1.5, "volume": .4,
                                     "segments": [{"start": 0, "end": .5, "speed": .5},
                                                  {"start": .5, "end": 1.5, "speed": 1}],
                                     "volume_keyframes": [{"time": 0, "volume": 0}, {"time": 1, "volume": 0},
                                                          {"time": 1.5, "volume": 1}, {"time": 2, "volume": 1}]})
        result = self.render(project)
        self.assertLess(self.rms(result["path"], .3), 3)
        self.assertLess(self.rms(result["path"], .8), 3)
        ramp = self.rms(result["path"], 1.2)
        full = self.rms(result["path"], 1.7)
        self.assertGreater(full, 300)
        self.assertAlmostEqual(ramp/full, .5, delta=.13)
        # Retain the base volume multiplier in addition to the envelope.
        reference = copy.deepcopy(project)
        reference["clips"][0].pop("volume_keyframes")
        reference["clips"][0]["volume"] = 1
        original = self.rms(self.render(reference, "base-volume")["path"], 1.7)
        self.assertAlmostEqual(full/original, .4, delta=.04)

    def test_audio_track_keyframes_follow_local_loop_time(self):
        project = self.project()
        project["clips"] = [{"asset_id": "video", "in": 0, "out": 1,
                              "freeze": {"time": 1, "duration": 3}}]
        project["audio"] = [{"asset_id": "video", "start": .5, "in": .5, "out": 1,
                              "loop": True, "duration": 2, "volume": .5,
                              "volume_keyframes": [{"time": 0, "volume": 1}, {"time": .5, "volume": 1},
                                                   {"time": .75, "volume": 0}, {"time": 2, "volume": 0}]}]
        result = self.render(project)
        self.assertLess(self.rms(result["path"], .2), 3)
        self.assertGreater(self.rms(result["path"], .7), 500)
        self.assertLess(self.rms(result["path"], 1.5), 3)
        self.assertLess(self.rms(result["path"], 2.2), 3)

    def test_freeze_and_motion_survive_transition_sections(self):
        project = self.project()
        project["clips"] = [{"asset_id": "video", "in": 0, "out": 1, "volume": 0,
                              "transition": {"name": "fade", "duration": .25}},
                             {"asset_id": "video", "in": 0, "out": 1,
                              "freeze": {"time": 1.5, "duration": 1},
                              "motion": [{"time": 0, "zoom": 1, "x": .5, "y": .5},
                                         {"time": 1, "zoom": 1.5, "x": .5, "y": .5}]}]
        result = self.render(project)
        self.assertAlmostEqual(result["duration"], 1.75, delta=.05)
        self.assertLess(self.rms(result["path"], 1.2), 3)
        self.assertNotEqual(self.frame(result["path"], 1.1), self.frame(result["path"], 1.6))

    def test_malformed_animation_and_freeze_are_rejected(self):
        malformed = [
            {"freeze": []}, {"freeze": {}}, {"freeze": {"time": float("nan"), "duration": 1}},
            {"freeze": {"time": 3, "duration": 1}}, {"freeze": {"time": 1, "duration": 0}},
            {"freeze": {"time": 1, "duration": 1}, "segments": [{"start": 0, "end": 2, "speed": 1}]},
            {"motion": None}, {"motion": [{"time": 0, "zoom": 1, "x": .5}]},
            {"motion": [{"time": 0, "zoom": float("inf"), "x": .5, "y": .5}]},
            {"motion": [{"time": 0, "zoom": 1, "x": 2, "y": .5}]},
            {"motion": [{"time": 2.1, "zoom": 1, "x": .5, "y": .5}]},
            {"volume_keyframes": [{"time": 0, "volume": 1}, {"time": 0, "volume": 0}]},
            {"volume_keyframes": [{"time": 1, "volume": 1}, {"time": .5, "volume": 0}]},
            {"volume_keyframes": [{"time": 0, "volume": True}]},
            {"volume_keyframes": [{"time": 0, "volume": 4.01}]},
            {"volume_keyframes": [{"time": i/100, "volume": 1} for i in range(65)]},
        ]
        for changes in malformed:
            with self.subTest(changes=changes):
                project = self.project(); project["clips"][0].update(copy.deepcopy(changes))
                validation = engine.validate_project(project, self.assets.__getitem__)
                self.assertFalse(validation["valid"], validation)
        project = self.project()
        project["audio"] = [{"asset_id": "video", "in": 0, "out": 1,
                              "volume_keyframes": [{"time": 1.1, "volume": 1}]}]
        self.assertFalse(engine.validate_project(project, self.assets.__getitem__)["valid"])

    def test_keyframe_endpoints_can_be_partial_and_tiny_intervals_are_safe(self):
        project = self.project()
        project["clips"][0]["volume_keyframes"] = [{"time": .2, "volume": .5}, {"time": .2+1e-12, "volume": 1}]
        self.assertTrue(engine.validate_project(project, self.assets.__getitem__)["valid"])
        result = self.render(project)
        before, after = self.rms(result["path"], .03, .07), self.rms(result["path"], .6)
        self.assertAlmostEqual(before/after, .5, delta=.04)

    def test_maximum_keyframe_count_survives_expression_compilation(self):
        project = self.project()
        project["clips"][0]["out"] = 1
        project["clips"][0]["motion"] = [
            {"time": i/63, "zoom": 1+i%2*.01, "x": i/63, "y": .5} for i in range(64)]
        project["clips"][0]["volume_keyframes"] = [
            {"time": i/63, "volume": .5+i%2*.1} for i in range(64)]
        result = self.render(project)
        self.assertAlmostEqual(result["duration"], 1, delta=.04)
        self.assertGreater(self.rms(result["path"], .5), 300)


if __name__ == "__main__":
    unittest.main()
