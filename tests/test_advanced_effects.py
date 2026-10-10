from __future__ import annotations

import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from montage_studio import effects, engine, shapes


FFMPEG = os.environ.get("FRAMEDROP_FFMPEG", os.environ.get("MONTAGE_FFMPEG", "ffmpeg"))


def rgba_png(path):
    """Read the lossless native PNG to verify geometry and opacity."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("Not a PNG")
    offset, compressed = 8, bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset+4])[0]
        kind, payload = data[offset+4:offset+8], data[offset+8:offset+8+length]
        if kind == b"IHDR":
            width, height, depth, color, *_ = struct.unpack(">IIBBBBB", payload)
            if (depth, color) != (8, 6):
                raise AssertionError("Native shapes must use RGBA")
        elif kind == b"IDAT":
            compressed.extend(payload)
        offset += 12+length
    raw = zlib.decompress(compressed)
    stride = width*4
    assert len(raw) == (stride+1)*height
    rows = []
    for row in range(height):
        assert raw[row*(stride+1)] == 0
        rows.append(raw[row*(stride+1)+1:(row+1)*(stride+1)])
    pixels = b"".join(rows)
    return width, height, lambda x, y: tuple(pixels[(y*width+x)*4:(y*width+x+1)*4]), pixels


class NativeShapeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="framedrop-shapes-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def shape(self, kind="ellipse", **changes):
        result = {"id": "callout", "kind": kind, "start": .5, "duration": 1,
                  "x": .2, "y": .2, "x2": .8, "y2": .8,
                  "stroke_width": 6, "color": "#ff2200", "opacity": 1}
        result.update(changes)
        return result

    def render(self, shape, name="shape", **kwargs):
        return rgba_png(shapes.render_shape(shape, 100, 100, self.root/(name+".png"), **kwargs))

    def test_ellipse_has_hollow_center_correct_color_and_antialiasing(self):
        _, _, pixel, raw = self.render(self.shape())
        self.assertEqual(pixel(50, 50)[3], 0)
        self.assertEqual(pixel(20, 50), (255, 34, 0, 255))
        self.assertEqual(pixel(0, 0)[3], 0)
        self.assertTrue(any(0 < value < 255 for value in raw[3::4]), "Stroke edges must be antialiased")

    def test_reversed_rectangle_bounds_and_opacity(self):
        _, _, pixel, first = self.render(self.shape("rectangle", opacity=.5))
        _, _, _, second = self.render(self.shape("rectangle", opacity=.5, x=.8, y=.8, x2=.2, y2=.2), "reverse")
        self.assertEqual(first, second)
        self.assertEqual(pixel(20, 50), (255, 34, 0, 128))
        self.assertEqual(pixel(50, 50)[3], 0)

    def test_arrow_points_from_tail_to_tip(self):
        _, _, pixel, _ = self.render(self.shape("arrow", x=.1, y=.5, x2=.9, y2=.5, stroke_width=8))
        self.assertEqual(pixel(20, 50)[3], 255, "Tail must join the shaft")
        self.assertEqual(pixel(70, 60)[3], 255, "Filled arrowhead must widen near its base")
        self.assertEqual(pixel(20, 60)[3], 0, "Tail must remain narrow")
        self.assertEqual(pixel(89, 50)[3] > 0, True)
        self.assertEqual(pixel(96, 50)[3], 0, "Arrow must end at its tip")

    def test_preview_stroke_scaling_and_fully_transparent_shape(self):
        _, _, pixel, _ = self.render(self.shape("rectangle", stroke_width=12), stroke_scale=.25)
        self.assertEqual(pixel(20, 50)[3], 255)
        self.assertEqual(pixel(24, 50)[3], 0)
        _, _, _, raw = self.render(self.shape(opacity=0), "invisible")
        self.assertFalse(any(raw))

    def test_invalid_shape_values_are_rejected(self):
        for patch in ({"duration": 0}, {"start": 2}, {"duration": float("nan")},
                      {"x": -1}, {"x2": True}, {"x2": .2}, {"opacity": 2},
                      {"stroke_width": 0}, {"color": "red:movie=/etc/passwd"}, {"kind": []}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                shapes.validate_shape(self.shape(**patch), 2)
        with self.assertRaises(ValueError):
            shapes.validate_shape(self.shape("arrow", x2=.2, y2=.2), 2)


class EffectValidationTests(unittest.TestCase):
    def test_invalid_effect_windows_and_names_are_rejected(self):
        for effect in ({"name": "blur", "start": -.1}, {"name": "blur", "end": 2},
                       {"name": "blur", "start": .7, "end": .7},
                       {"name": "blur", "start": float("nan")}, {"name": "blur", "end": True},
                       {"name": "blur", "start": "0);movie=/etc/passwd"},
                       {"name": []}, {"name": "movie=/etc/passwd"}, []):
            with self.subTest(effect=effect), self.assertRaises(ValueError):
                effects.validate_effect(effect, 1)
        effects.validate_effect({"name": "blur", "start": .3, "end": .6}, 1)


@unittest.skipUnless(shutil.which(FFMPEG), "FFmpeg required")
class NativeEffectRenderTests(unittest.TestCase):
    def frames(self, recipes, source="testsrc2=size=96x64:rate=12:duration=1"):
        clauses, label = effects.build_graph("0:v", recipes, 96, 64, 1, 12)
        command = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-threads", "1",
                   "-filter_threads", "1", "-filter_complex_threads", "1", "-f", "lavfi", "-i", source]
        if clauses:
            command += ["-filter_complex", ";".join(clauses), "-map", f"[{label}]"]
        command += ["-an", "-c:v", "rawvideo", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        result = subprocess.run(command, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        frame_size = 96*64*3
        self.assertEqual(len(result.stdout), frame_size*12, "Effects must preserve frame count and timing")
        return [result.stdout[start:start+frame_size] for start in range(0, len(result.stdout), frame_size)]

    def test_every_recipe_supports_time_window_and_preserves_timing(self):
        for recipe in effects.list_effects():
            with self.subTest(effect=recipe["name"]):
                self.frames([{"name": recipe["name"], "strength": 1, "start": 1/3, "end": 2/3}])

    def test_new_effects_change_only_their_active_range(self):
        baseline = self.frames([])
        for name in ("pixelate", "edge_glow", "posterize", "echo_trails", "scanlines", "invert"):
            with self.subTest(effect=name):
                rendered = self.frames([{"name": name, "strength": 1, "start": 1/3, "end": 2/3}])
                for index in (0, 2, 8, 11):
                    difference = sum(abs(a-b) for a, b in zip(baseline[index], rendered[index]))/len(baseline[index])
                    self.assertLess(difference, 3, f"{name} leaks outside its effect window at frame {index}")
                active_difference = sum(abs(a-b) for a, b in zip(baseline[6], rendered[6]))/len(baseline[6])
                self.assertGreater(active_difference, 1, "The enabled recipe must visibly change frames")

    def test_late_flash_is_anchored_to_window_start(self):
        baseline = self.frames([], "color=c=gray:size=96x64:rate=12:duration=1")
        rendered = self.frames([{"name": "flash", "strength": 1, "start": .5, "end": .75}],
                               "color=c=gray:size=96x64:rate=12:duration=1")
        self.assertEqual(rendered[5], baseline[5])
        self.assertGreater(rendered[6][0]-baseline[6][0], 60)
        self.assertEqual(rendered[9], baseline[9])

    def test_timed_invert_preserves_exact_inactive_pixels_and_exclusive_end(self):
        source = "color=c=red:size=96x64:rate=12:duration=1"
        baseline = self.frames([], source)
        rendered = self.frames([{"name":"invert", "strength":1, "start":1/3, "end":2/3}], source)
        for index in (0, 1, 2, 3, 8, 9, 10, 11):
            self.assertEqual(rendered[index], baseline[index], f"Inactive frame {index} must remain exact")
        for index in (4, 5, 6, 7):
            red, green, blue = rendered[index][:3]
            self.assertLess(red, 5)
            self.assertGreater(green, 250)
            self.assertGreater(blue, 250)

    def test_echo_trail_decays_after_a_bright_frame(self):
        source = "nullsrc=size=96x64:rate=12:duration=1,geq=lum='if(eq(N,6),235,16)':cb=128:cr=128"
        rendered = self.frames([{"name": "echo_trails", "strength": 1}], source)
        self.assertLess(rendered[5][0], 3)
        self.assertGreater(rendered[6][0], 50, "The live frame must have the strongest weight")
        self.assertGreater(rendered[6][0], rendered[7][0])
        self.assertGreater(rendered[7][0], rendered[8][0])
        self.assertGreater(rendered[8][0], 10, "Older frames should leave a fading trail")

    def test_png_is_decodable_by_ffmpeg(self):
        with tempfile.TemporaryDirectory(prefix="framedrop-png-") as directory:
            path = shapes.render_shape({"kind": "arrow", "duration": 1, "x": .1, "y": .1, "x2": .9, "y2": .9},
                                       96, 64, Path(directory)/"arrow.png")
            result = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "null", "-"],
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode())

    @unittest.skipUnless(shutil.which(engine.FFPROBE), "ffprobe required")
    def test_non_frame_aligned_clip_end_effect_renders_and_overrun_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="framedrop-effect-window-") as directory:
            root = Path(directory)
            source = shapes.render_shape({"kind":"rectangle", "duration":1, "x":.1, "y":.1, "x2":.9, "y2":.9},
                                         96, 64, root/"source.png")
            resolver = lambda ident: {"id":ident, "kind":"image", "path":str(source)}
            project = {"canvas":{"width":96, "height":64, "fps":12},
                       "clips":[{"asset_id":"source", "in":0, "out":1.02, "effects":[
                           {"name":"invert", "start":.5, "end":1.02},
                           {"name":"flash", "start":1.01, "end":1.02}]}],
                       "audio":[], "overlays":[], "titles":[]}
            self.assertTrue(engine.validate_project(project, resolver)["valid"])
            result = engine.render_project(project, resolver, root/"render.mp4", root/"work")
            self.assertAlmostEqual(result["duration"], 1, delta=1/12)
            project["clips"][0]["effects"][0]["end"] = 1.03
            self.assertFalse(engine.validate_project(project, resolver)["valid"],
                             "Frame rounding must not loosen project effect-window validation")


if __name__ == "__main__":
    unittest.main()
