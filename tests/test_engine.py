from __future__ import annotations

from array import array
import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import wave

from montage_studio import analysis, effects, engine


def ffmpeg(*args):
    result = subprocess.run([engine.FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                             "-threads", "2", "-filter_threads", "1", "-filter_complex_threads", "1",
                             *map(str, args)], capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result


@unittest.skipUnless(shutil.which(engine.FFMPEG) and shutil.which(engine.FFPROBE), "FFmpeg required")
class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="montage-engine-tests-")
        cls.root = Path(cls.temp.name)
        cls.assets = {}
        silent = cls.root/"silent clip.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x96:rate=12:duration=2", "-an", "-c:v", "libx264", "-threads", "2", silent)
        audible = cls.root/"different'fps.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=blue:size=96x160:rate=20:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2",
               "-c:v", "libx264", "-threads", "2", "-c:a", "aac", "-shortest", audible)
        red = cls.root/"red.ppm"
        red.write_bytes(b"P6\n16 16\n255\n"+bytes([255, 0, 0])*256)
        green = cls.root/"green.ppm"
        green.write_bytes(b"P6\n16 16\n255\n"+bytes([0, 255, 0])*256)
        wide = cls.root/"wide.ppm"
        wide.write_bytes(b"P6\n320 96\n255\n"+(bytes([255, 0, 0])*160+bytes([0, 0, 255])*160)*96)
        finite = cls.root/"finite.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=red:size=160x96:rate=12:duration=0.333333333", "-c:v", "libx264", "-threads", "2", finite)
        animated = cls.root/"animated.gif"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x96:rate=12:duration=0.5", animated)
        beat = cls.root/"beat.wav"
        pcm = array("h")
        for i in range(8*8000):
            pulse = (i % 4000)/8000
            amplitude = .65*math.exp(-pulse*65) if pulse < .10 else 0
            pcm.append(round(32760*amplitude*math.sin(2*math.pi*90*i/8000)))
        with wave.open(str(beat), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(pcm.tobytes())
        lut = cls.root/"identity'look.cube"
        lut.write_text('TITLE "Identity"\nLUT_3D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n')
        for name, path, kind in (("silent", silent, "video"), ("audible", audible, "video"), ("red", red, "image"), ("green", green, "image"), ("wide", wide, "image"),
                                 ("finite", finite, "video"), ("animated", animated, "image"), ("beat", beat, "audio"), ("lut", lut, "lut")):
            cls.assets[name] = {"id": name, "path": str(path), "kind": kind}
        font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        if font.exists():
            cls.assets["font"] = {"id": "font", "path": str(font), "kind": "font"}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = self.root/self._testMethodName
        self.case.mkdir()

    def resolver(self, asset_id):
        return self.assets[asset_id]

    def project(self):
        return {"canvas": {"width": 160, "height": 96, "fps": 12},
                "clips": [{"asset_id": "silent", "in": 0, "out": 1}],
                "audio": [], "overlays": [], "titles": []}

    def render(self, project, name="render", **kwargs):
        return engine.render_project(project, self.resolver, self.case/(name+".mp4"), self.case/name, **kwargs)

    def frame(self, path, at, width=160, height=96):
        return subprocess.run([engine.FFMPEG, "-v", "error", "-threads", "2", "-filter_threads", "1", "-ss", f"{at:.9f}", "-i", str(path),
                               "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                              capture_output=True, check=True).stdout

    def test_probe_and_empty_project(self):
        metadata = engine.probe(self.assets["silent"]["path"])
        self.assertTrue(metadata["has_video"])
        self.assertFalse(metadata["has_audio"])
        self.assertEqual(metadata["fps"], 12)
        project = self.project()
        project["clips"] = []
        check = engine.validate_project(project, self.resolver)
        self.assertTrue(check["valid"])
        self.assertFalse(check["renderable"])
        with self.assertRaisesRegex(ValueError, "footage"):
            engine.render_plan(project, self.resolver)

    def test_validation_rejects_unsafe_and_malformed_values(self):
        for changes in ({"speed": 0}, {"in": float("nan")}, {"out": 50}, {"effects": [{"name": "movie=/etc/passwd"}]},
                        {"effects": ["bad"]}, {"effects": [{"name": "punchy", "strength": float("inf")}]},
                        {"segments": [{"start": .2, "end": 1, "speed": 2}]}):
            with self.subTest(changes=changes):
                project = self.project()
                project["clips"][0].update(changes)
                self.assertFalse(engine.validate_project(project, self.resolver)["valid"])
        project = self.project()
        project["titles"] = [None]
        self.assertFalse(engine.validate_project(project, self.resolver)["valid"])

    def test_silent_short_export_with_all_native_effects(self):
        # Every advertised effect must survive actual frame processing, including
        # RGB format conversion, graph-based glow and time-based crop expressions.
        for effect in effects.list_effects():
            with self.subTest(effect=effect["name"]):
                clauses, label = effects.build_graph("0:v", [{"name": effect["name"], "strength": 1}], 160, 96, .5, 12)
                ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x96:rate=12:duration=0.5", "-filter_complex", ";".join(clauses),
                       "-map", f"[{label}]", "-frames:v", "6", "-f", "null", "-")
        project = self.project()
        project["clips"][0]["effects"] = [{"name": "impact"}, {"name": "glow"}, {"name": "rgb_split"}]
        events = []
        result = self.render(project, progress=lambda value, message: events.append(value))
        self.assertTrue(result["has_audio"])
        self.assertEqual(result["audio_codec"], "aac")
        self.assertAlmostEqual(result["duration"], 1, delta=.08)
        self.assertEqual(events[-1], 1)
        self.assertEqual(events, sorted(events))
        audio = subprocess.run([engine.FFMPEG, "-v", "error", "-i", result["path"], "-vn", "-f", "s16le", "pipe:1"], capture_output=True, check=True).stdout
        values = array("h"); values.frombytes(audio)
        self.assertLess(max(map(abs, values), default=0), 100, "Silent inputs must remain silent after loudnorm")

    def test_heterogeneous_speed_transition_audio_title_lut(self):
        project = self.project()
        project["clips"] = [
            {"asset_id": "silent", "in": .25, "out": 1.75, "segments": [{"start": 0, "end": .5, "speed": .5}, {"start": .5, "end": 1.5, "speed": 2}],
             "effects": [{"name": "punchy"}], "lut_asset_id": "lut", "transition": {"name": "fade", "duration": .25}},
            {"asset_id": "audible", "in": .25, "out": 1.75, "speed": 1.5, "volume": .25, "fit": "contain", "transition": {"name": "wipeleft", "duration": .25}},
            {"asset_id": "red", "in": 0, "out": .75},
        ]
        project["audio"] = [{"asset_id": "beat", "start": .5, "in": .5, "out": 1, "loop": True, "duration": 2, "volume": .4, "fade_in": .1, "fade_out": .2}]
        title = {"text": "Literal 100% : %{n} ' title", "start": .25, "duration": 1.5, "font_size": 16, "fade": .1}
        if "font" in self.assets:
            title["font_asset_id"] = "font"
        project["titles"] = [title]
        self.assertAlmostEqual(engine.project_duration(project), 2.75)
        result = self.render(project)
        self.assertAlmostEqual(result["duration"], 2.75, delta=.09)
        self.assertEqual((result["width"], result["height"]), (160, 96))
        ffmpeg("-i", result["path"], "-f", "null", "-")

    def test_overlay_modes_and_finite_overlay_disappears(self):
        for mode in ("normal", "screen", "add", "lighten", "chroma"):
            with self.subTest(mode=mode):
                project = self.project()
                project["clips"] = [{"asset_id": "audible", "in": 0, "out": 1, "volume": 0}]
                project["normalize_audio"] = False
                project["overlays"] = [{"asset_id": "green" if mode == "chroma" else "finite", "start": .25, "duration": .6,
                                        "blend": mode, "opacity": .5, "width": 1, "key_color": "#00ff00"}]
                result = self.render(project, name=mode)
                self.assertAlmostEqual(result["duration"], 1, delta=.09)
                raw = subprocess.run([engine.FFMPEG, "-v", "error", "-threads", "2", "-filter_threads", "1", "-ss", "0.8333333", "-i", result["path"],
                                      "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True).stdout
                self.assertEqual(len(raw), 3)
                self.assertGreater(raw[2], raw[0]+100, "The overlay must disappear and reveal the original blue image")
                active = subprocess.run([engine.FFMPEG, "-v", "error", "-threads", "2", "-filter_threads", "1", "-ss", "0.4166667", "-i", result["path"],
                                         "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True).stdout
                self.assertEqual(len(active), 3)
                if mode == "chroma":
                    self.assertGreater(active[2], active[1]+100, "Green chroma must key through to blue")
                else:
                    self.assertGreater(active[0], 70, "The red overlay must appear during its active range")

    def test_fractional_fps_and_animated_gif(self):
        project = self.project()
        project["canvas"]["fps"] = 23.976
        project["clips"] = [{"asset_id": "animated", "in": 0, "out": .4, "transition": {"name": "dissolve", "duration": .1}},
                            {"asset_id": "silent", "in": .1, "out": 1.37, "transition": {"name": "fadeblack", "duration": .12}},
                            {"asset_id": "audible", "in": .35, "out": 1.31}]
        project["overlays"] = [{"asset_id": "animated", "start": .3, "duration": 1.5, "loop": True, "blend": "normal", "opacity": .4, "width": .37}]
        plan = engine.render_plan(project, self.resolver)
        result = self.render(project)
        self.assertAlmostEqual(result["duration"], plan["duration"], delta=1/23.976+.03)
        self.assertAlmostEqual(result["fps"], 23.976, delta=.001)

    def test_late_overlay_framesync_with_audio_and_portrait_canvas(self):
        # Regression for the FFmpeg 8 scheduler deadlock observed on a 7.1 s
        # portrait export with a short effect first appearing at 4.1 s. Early
        # overlays did not expose the audio/video queue dependency.
        project = self.project()
        project["canvas"] = {"width": 96, "height": 160, "fps": 30}
        project["clips"] = [{"asset_id": "green", "in": 0, "out": 7.1}]
        for mode in ("screen", "normal", "add", "lighten", "chroma"):
            with self.subTest(mode=mode):
                project["overlays"] = [{"asset_id": "red" if mode == "chroma" else "finite", "start": 4.1, "duration": .75,
                                        "width": 1.8, "opacity": .5, "blend": mode, "key_color": "#0000ff"}]
                started = time.monotonic()
                result = self.render(project, name=mode, cancelled=lambda: time.monotonic()-started > 20)
                self.assertAlmostEqual(result["duration"], 7.1, delta=.05)
                before, during, after = (self.frame(result["path"], at, 1, 1) for at in (3.5, 4.2, 6.0))
                self.assertLess(before[0], 30)
                self.assertGreater(during[0], 60)
                self.assertLess(after[0], 30)

    def test_professional_transform_color_and_fades(self):
        project = self.project()
        transforms = [{"x": 0}, {"x": 1}, {"x": 0, "flip_x": True}, {"x": 0, "rotation": 180},
                      {"y": 0, "rotation": 90}, {"y": 0, "rotation": -90}]
        project["clips"] = [{"asset_id": "wide", "in": 0, "out": .5, "transform": value} for value in transforms]
        result = self.render(project, name="transforms")
        for index, dominant in enumerate((0, 2, 2, 2, 0, 2)):
            with self.subTest(transform=transforms[index]):
                rgb = self.frame(result["path"], index*.5+.25, 1, 1)
                self.assertGreater(rgb[dominant], 200, rgb)
                self.assertLess(rgb[2-dominant], 30, rgb)
        project["clips"] = [{"asset_id": "wide", "in": 0, "out": .5, "fit": "contain"},
                            {"asset_id": "wide", "in": 0, "out": .5, "fit": "contain", "transform": {"zoom": 2}}]
        result = self.render(project, name="zoom")
        before, after = self.frame(result["path"], .25), self.frame(result["path"], .75)
        top = (10*160+40)*3
        self.assertLess(before[top], 40)
        self.assertGreater(after[top], 180, "Zoom must crop the letterboxing and enlarge the source")
        project["clips"] = [{"asset_id": "red", "in": 0, "out": 1, "color": {"saturation": 0, "brightness": .1, "contrast": 1.2, "gamma": 1.1},
                             "fade_in": .25, "fade_out": .25}]
        result = self.render(project, name="color-fades")
        first, middle, last = (self.frame(result["path"], at, 1, 1) for at in (0, .5, .9166666))
        self.assertLess(max(first), 10)
        self.assertLess(max(middle)-min(middle), 6, "Zero saturation must produce a grayscale image")
        self.assertGreater(min(middle), 30)
        self.assertLess(max(last), max(middle)-20)

    def test_captions_presets_literal_text_fonts_and_timing(self):
        project = self.project()
        project["clips"] = [{"asset_id": "red", "in": 0, "out": 1}]
        project["captions"] = [{"id": "cue", "start": .25, "end": .75, "text": r"{\alpha&HFF&}VISIBLE"},
                               {"id": "outside", "start": 2, "end": 3, "text": "Outside"}]
        project["titles"] = [{"id": "title", "text": "Title", "start": 0, "duration": .1, "font_size": 10, "fade": 0}]
        style = {"font_size": 14, "outline": 1, "margin": 6, "position": "center"}
        if "font" in self.assets:
            style["font_asset_id"] = "font"
        active_frames = []
        for preset in ("clean", "bold", "boxed"):
            with self.subTest(preset=preset):
                project["caption_style"] = {**style, "preset": preset}
                validation = engine.validate_project(project, self.resolver)
                self.assertTrue(validation["valid"], validation)
                self.assertTrue(any("Caption 2" in w for w in validation["warnings"]))
                result = self.render(project, name=preset)
                self.assertEqual(result["captions_burned"], 1)
                def white_count(raw):
                    return sum(min(raw[i:i+3]) > 175 for i in range(0, len(raw), 3))
                before, during, after = (self.frame(result["path"], at) for at in (.1666666, .5, .8333333))
                self.assertLess(white_count(before), 10)
                self.assertGreater(white_count(during), 40, "Literal ASS tags must not hide caption text")
                self.assertLess(white_count(after), 10)
                active_frames.append(during)
                script = (self.case/preset/"captions.ass").read_text()
                self.assertIn("\\{\\\u2060alpha&HFF&\\}VISIBLE", script)
                self.assertEqual(script.count("Dialogue:"), 1)
                if "font" in self.assets:
                    self.assertIn("DejaVu Sans", script)
                    self.assertTrue((self.case/preset/"caption-fonts/caption-font.ttf").exists())
        self.assertNotEqual(active_frames[0], active_frames[1])
        self.assertNotEqual(active_frames[0], active_frames[2])
        project["titles"] = []
        project["caption_style"] = {**style, "preset": "clean", "font_size": 20}
        project["captions"] = [{"id": "literal", "start": 0, "end": .5, "text": r"A\NB"},
                               {"id": "newline", "start": .5, "end": 1, "text": "A\nB"}]
        result = self.render(project, name="linebreaks")
        bounds = []
        for at in (.25, .75):
            raw = self.frame(result["path"], at)
            ys = [i//3//160 for i in range(0, len(raw), 3) if min(raw[i:i+3]) > 175]
            bounds.append(max(ys)-min(ys))
        self.assertGreater(bounds[1], bounds[0]*1.5, "A literal backslash-N must remain on one line; actual newline must split lines")

    def test_caption_and_professional_control_validation(self):
        for changed in ({"transform": {"rotation": 13}}, {"transform": {"zoom": .5}}, {"transform": {"x": 2}},
                        {"transform": {"flip_x": "yes"}}, {"color": {"gamma": 0}}, {"color": {"contrast": float("nan")}}, {"fade_in": 2}):
            with self.subTest(changed=changed):
                project = self.project(); project["clips"][0].update(changed)
                self.assertFalse(engine.validate_project(project, self.resolver)["valid"])
        for cue in ({"start": -1, "end": 1, "text": "bad"}, {"start": 1, "end": 0, "text": "bad"},
                    {"start": 0, "end": 1, "text": "\x00bad"}, {"start": 0, "end": 1, "text": "x"*2001}):
            with self.subTest(cue=str(cue)[:60]):
                project = self.project(); project["captions"] = [cue]
                self.assertFalse(engine.validate_project(project, self.resolver)["valid"])
        project = self.project(); project["caption_style"] = {"preset": "raw_ass"}
        self.assertFalse(engine.validate_project(project, self.resolver)["valid"])

    def test_all_transitions_render(self):
        # Normalization is tested above; verify each advertised xfade mode with
        # deliberately different source geometry after conversion to common frames.
        for transition in effects.TRANSITIONS:
            if transition == "cut":
                continue
            with self.subTest(transition=transition):
                ffmpeg("-f", "lavfi", "-i", "color=red:s=160x96:r=12:d=0.5", "-f", "lavfi", "-i", "color=blue:s=160x96:r=12:d=0.5",
                       "-filter_complex", f"[0:v]settb=AVTB[v0];[1:v]settb=AVTB[v1];[v0][v1]xfade=transition={transition}:duration=0.5:offset=0[v]",
                       "-map", "[v]", "-t", "0.5", "-f", "null", "-")

    def test_cancel_and_output_protection(self):
        project = self.project()
        with self.assertRaises(engine.RenderCancelled):
            self.render(project, cancelled=lambda: True)
        self.assertFalse((self.case/"render.mp4").exists())
        original = Path(self.assets["silent"]["path"])
        size = original.stat().st_size
        with self.assertRaises(ValueError):
            engine.render_project(project, self.resolver, original, self.case/"overwrite")
        self.assertEqual(original.stat().st_size, size)
        state = {"checks": 0}
        def cancel_running():
            state["checks"] += 1
            return state["checks"] >= 3
        with self.assertRaises(engine.RenderCancelled):
            self.render(project, name="active-cancel", cancelled=cancel_running)
        self.assertFalse((self.case/"active-cancel.mp4").exists())

    def test_analysis_beats_waveform_and_scenes(self):
        result = analysis.analyze(self.assets["beat"]["path"], mode="beats", start=1, duration=6)
        self.assertAlmostEqual(result["bpm"], 120, delta=5)
        self.assertGreaterEqual(len(result["beats"]), 10)
        self.assertEqual(result["time_reference"], "relative_to_analysis_start")
        waveform = analysis.analyze(self.assets["beat"]["path"], mode="waveform", start=1, duration=2)
        self.assertLessEqual(len(waveform["peaks"]), 600)
        self.assertTrue(all(0 <= v <= 1 for v in waveform["peaks"]))
        self.assertAlmostEqual(waveform["duration"], 2, delta=.03)
        source = self.case/"scene.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=black:s=160x96:r=10:d=1", "-f", "lavfi", "-i", "color=white:s=160x96:r=10:d=1",
               "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", "-threads", "2", source)
        scenes = analysis.analyze(source, mode="scenes", start=.5, duration=1.5)
        self.assertTrue(any(abs(c-.5) < .15 for c in scenes["cuts"]), scenes)
        with self.assertRaisesRegex(ValueError, "no audio"):
            analysis.analyze(self.assets["silent"]["path"])


if __name__ == "__main__":
    unittest.main()
