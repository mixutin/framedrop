"""Bounded, sequential FFmpeg timeline rendering.

All user paths enter through the asset resolver. Timeline expressions are numbers,
allowlisted recipes and literal text, never user-provided FFmpeg filter graphs.
Intermediate audio is floating-point PCM: summing tracks cannot clip before the
final normalization/limiter. Clip and transition sections share one video format.
"""
from __future__ import annotations

import functools
import hashlib
import errno
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import time

from . import automation, effects, shapes, graphics

FFMPEG = os.environ.get("MONTAGE_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("MONTAGE_FFPROBE", "ffprobe")
THREADS = min(8, max(1, int(os.environ.get("MONTAGE_FFMPEG_THREADS", "4"))))
STALL_TIMEOUT = min(600., max(30., float(os.environ.get("MONTAGE_FFMPEG_STALL_TIMEOUT", "120"))))
COLORS = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
CAPTION_STYLE = {"preset": "clean", "font_size": 52, "font_asset_id": None,
                 "color": "#ffffff", "outline_color": "#000000", "outline": 3,
                 "position": "bottom", "margin": 80}
COLOR_DEFAULTS = {"brightness": 0, "contrast": 1, "saturation": 1, "gamma": 1}
# Bound simultaneously decoded alpha streams while avoiding an intermediate
# full-timeline encode for every normal overlay. Other blend modes stay isolated.
NORMAL_OVERLAY_BATCH_SIZE = 4


class RenderError(RuntimeError):
    pass


class RenderCancelled(RenderError):
    pass


def _number(value, minimum=None, maximum=None, label="value"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return float(value)


def _ratio(value):
    try:
        numerator, denominator = str(value).split("/")
        return float(numerator)/float(denominator)
    except (ValueError, ZeroDivisionError):
        try:
            return float(value or 0)
        except (ValueError, TypeError):
            return 0.


@functools.lru_cache(maxsize=512)
def _probe_cached(path, modified, size):
    command = [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", path]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Cannot inspect media {Path(path).name}: {exc}") from exc
    if result.returncode:
        raise ValueError(f"Cannot inspect media {Path(path).name}: {result.stderr.strip()[-1200:]}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    video, audio = (videos[0] if videos else {}), (audios[0] if audios else {})
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = next((s.get("rotation", 0) for s in video.get("side_data_list", []) if "rotation" in s), 0)
    if abs(int(rotation)) % 180 == 90:
        width, height = height, width
    durations = []
    for value in [data.get("format", {}).get("duration")] + [s.get("duration") for s in streams]:
        try:
            parsed = float(value)
            if math.isfinite(parsed) and parsed >= 0:
                durations.append(parsed)
        except (ValueError, TypeError):
            pass
    return {"duration": max(durations, default=0.), "width": width, "height": height,
            "fps": _ratio(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "has_audio": bool(audios), "has_video": bool(videos),
            "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name")}


def probe(path: str) -> dict:
    media = Path(path).expanduser().resolve(strict=True)
    if not media.is_file():
        raise ValueError("Media path is not a regular file")
    stat = media.stat()
    return dict(_probe_cached(str(media), stat.st_mtime_ns, stat.st_size))


def clip_duration(clip) -> float:
    if clip.get("freeze") is not None:
        return float(clip["freeze"]["duration"])
    length = float(clip.get("out", 0)) - float(clip.get("in", 0))
    if clip.get("segments"):
        return sum((float(s["end"])-float(s["start"]))/float(s.get("speed", 1)) for s in clip["segments"])
    return length/float(clip.get("speed", 1))


def _transition_duration(clip):
    transition = clip.get("transition") or {}
    return float(transition.get("duration", 0)) if transition.get("name", "cut") != "cut" else 0.


def project_duration(project) -> float:
    clips = project.get("clips", [])
    return max(0., sum(clip_duration(c) for c in clips) - sum(_transition_duration(c) for c in clips[:-1]))


def _asset(asset_id, resolver, cache):
    if not isinstance(asset_id, str) or not asset_id:
        raise ValueError("asset_id is required")
    if asset_id not in cache:
        asset = dict(resolver(asset_id))
        raw_path = Path(asset["path"])
        if not raw_path.is_absolute():
            raise ValueError("Asset resolver returned a non-absolute path")
        path = raw_path.resolve(strict=True)
        if not path.is_file():
            raise ValueError("Asset is not a regular file")
        asset["path"] = str(path)
        cache[asset_id] = asset
    return cache[asset_id]


def _is_image(asset):
    # GIF is animated media: the GIF demuxer rejects image2's -loop option.
    # It is trimmed as a finite clip and can explicitly loop as an overlay.
    if Path(asset["path"]).suffix.lower() == ".gif":
        return False
    return asset.get("kind") == "image" or Path(asset["path"]).suffix.lower() in IMAGE_EXTENSIONS


def _track_duration(track):
    if track.get("loop") and track.get("duration") is not None:
        return float(track["duration"])
    return float(track.get("out", 0))-float(track.get("in", 0))


def validate_project(project, resolve_asset):
    errors, warnings, cache = [], [], {}
    if not isinstance(project, dict):
        return {"valid": False, "errors": ["Project must be an object"], "warnings": [], "duration": 0.}
    duration = 0.
    def check(label, function):
        try:
            function()
        except (ValueError, KeyError, TypeError, AttributeError, OSError, ZeroDivisionError) as exc:
            errors.append(f"{label}: {exc}")
    def canvas_check():
        c = project.get("canvas", {})
        w, h = _number(c.get("width", 1920), 64, 7680, "width"), _number(c.get("height", 1080), 64, 7680, "height")
        if int(w) != w or int(h) != h or w*h > 7680*4320:
            raise ValueError("Canvas dimensions must be integers within 8K pixel area")
        _number(c.get("fps", 30), 1, 120, "fps")
        if c.get("fit", "cover") not in ("cover", "contain"):
            raise ValueError("fit must be cover or contain")
        if not COLORS.fullmatch(c.get("background", "#101014")):
            raise ValueError("background must be a #RRGGBB color")
        if w % 2 or h % 2:
            warnings.append("Odd canvas dimensions will be rounded down to even dimensions for H.264.")
    check("Canvas", canvas_check)
    if project.get("export_profile", "standard") not in ("standard", "high"):
        errors.append("export_profile must be standard or high")
    collections = {}
    for name, limit in (("clips", 200), ("audio", 64), ("overlays", 64), ("shapes", 128), ("titles", 128), ("captions", 2000), ("accents", 128)):
        value = project.get(name, [])
        if not isinstance(value, list) or len(value) > limit:
            errors.append(f"{name} must be a list with at most {limit} items")
            value = []
        collections[name] = value
    clips = collections["clips"]
    if not clips:
        warnings.append("Add at least one footage clip before rendering")
    durations = []
    for index, clip in enumerate(clips):
        def clip_check():
            if not isinstance(clip, dict):
                raise ValueError("Clip must be an object")
            asset = _asset(clip.get("asset_id"), resolve_asset, cache)
            metadata = probe(asset["path"])
            if not metadata["has_video"]:
                raise ValueError("Footage must contain a video stream or be an image")
            start = _number(clip.get("in", 0), 0, 86400, "in")
            end = _number(clip.get("out"), start+.001, 86400, "out")
            if not _is_image(asset) and metadata["duration"] and end > metadata["duration"]+.06:
                raise ValueError(f"out {end:g}s exceeds source duration {metadata['duration']:.3f}s")
            _number(clip.get("speed", 1), .125, 8, "speed")
            if clip.get("interpolation", "duplicate") not in ("duplicate", "optical_flow"):
                raise ValueError("interpolation must be duplicate or optical_flow")
            _number(clip.get("motion_blur", 0), 0, 1, "motion_blur")
            _number(clip.get("volume", 1), 0, 4, "volume")
            if clip.get("fit", project.get("canvas", {}).get("fit", "cover")) not in ("cover", "contain"):
                raise ValueError("fit must be cover or contain")
            segments = clip.get("segments", [])
            if not isinstance(segments, list) or len(segments) > 64:
                raise ValueError("segments must have at most 64 contiguous intervals")
            position = 0.
            for segment in segments:
                left = _number(segment.get("start"), 0, end-start, "segment.start")
                right = _number(segment.get("end"), left+.00001, end-start+.0001, "segment.end")
                _number(segment.get("speed", 1), .125, 8, "segment.speed")
                if abs(left-position) > .0001:
                    raise ValueError("Speed segments must be contiguous and start at zero")
                position = right
            if segments and abs(position-(end-start)) > .0001:
                raise ValueError("Speed segments must cover the entire trimmed source")
            freeze = clip.get("freeze")
            if freeze is not None:
                if not isinstance(freeze, dict):
                    raise ValueError("freeze must be an object")
                source_time = _number(freeze.get("time"), 0, 86400, "freeze.time")
                _number(freeze.get("duration"), .001, 14400, "freeze.duration")
                if not _is_image(asset) and metadata["duration"] and source_time >= metadata["duration"]:
                    raise ValueError("freeze.time must be before the end of the source")
                if segments:
                    raise ValueError("A freeze cannot also have speed segments")
            automation.validate_motion(clip.get("motion", []), clip_duration(clip))
            automation.validate_volume(clip.get("volume_keyframes", []), clip_duration(clip))
            recipes = clip.get("effects", [])
            if not isinstance(recipes, list) or len(recipes) > 12:
                raise ValueError("At most 12 effects may be applied to a clip")
            for recipe in recipes:
                effects.validate_effect(recipe, clip_duration(clip))
            transform = clip.get("transform", {})
            if not isinstance(transform, dict):
                raise ValueError("transform must be an object")
            _number(transform.get("x", .5), 0, 1, "transform.x")
            _number(transform.get("y", .5), 0, 1, "transform.y")
            _number(transform.get("zoom", 1), 1, 4, "transform.zoom")
            rotation = _number(transform.get("rotation", 0), -180, 180, "transform.rotation")
            if rotation not in (-180, -90, 0, 90, 180):
                raise ValueError("transform.rotation must be -180, -90, 0, 90, or 180 degrees")
            for key in ("flip_x", "flip_y"):
                if not isinstance(transform.get(key, False), bool):
                    raise ValueError(f"transform.{key} must be true or false")
            color = clip.get("color", {})
            if not isinstance(color, dict):
                raise ValueError("color must be an object")
            for key, lo, hi in (("brightness", -.5, .5), ("contrast", .25, 3), ("saturation", 0, 3), ("gamma", .25, 3)):
                _number(color.get(key, COLOR_DEFAULTS[key]), lo, hi, "color."+key)
            for key in ("fade_in", "fade_out"):
                _number(clip.get(key, 0), 0, clip_duration(clip), key)
            if clip.get("lut_asset_id"):
                lut = _asset(clip["lut_asset_id"], resolve_asset, cache)
                if lut.get("kind") != "lut" or Path(lut["path"]).suffix.lower() not in (".cube", ".3dl", ".dat", ".m3d", ".csp"):
                    raise ValueError("lut_asset_id must refer to a supported 3D LUT")
            transition = clip.get("transition") or {}
            if transition.get("name", "cut") not in effects.TRANSITIONS:
                raise ValueError("Unknown transition")
            _number(transition.get("duration", 0), 0, 2, "transition.duration")
        check(f"Clip {index+1}", clip_check)
        try:
            length = clip_duration(clip)
            durations.append(length if math.isfinite(length) and length > 0 else 0.)
        except (TypeError, ValueError, AttributeError, KeyError, ZeroDivisionError):
            durations.append(0.)
    if clips and all(d > 0 for d in durations):
        try:
            outgoing = [_transition_duration(c) for c in clips[:-1]] + [0.]
            for i, d in enumerate(durations):
                incoming = outgoing[i-1] if i else 0.
                if incoming + outgoing[i] > d + .0001:
                    errors.append(f"Clip {i+1}: incoming and outgoing transitions exceed clip duration")
            duration = max(0., sum(durations)-sum(outgoing))
        except (TypeError, ValueError, AttributeError):
            pass
    if duration > 14400:
        errors.append("Timeline exceeds the four-hour render limit")
    for index, track in enumerate(collections["audio"]):
        def audio_check():
            asset = _asset(track.get("asset_id"), resolve_asset, cache)
            metadata = probe(asset["path"])
            if not metadata["has_audio"]:
                raise ValueError("Audio track must contain an audio stream")
            _number(track.get("start", 0), 0, 14400, "start")
            start = _number(track.get("in", 0), 0, 86400, "in")
            end = _number(track.get("out"), start+.001, 86400, "out")
            if metadata["duration"] and end > metadata["duration"]+.06:
                raise ValueError("Audio out exceeds source duration")
            length = _number(_track_duration(track), .001, 14400, "duration")
            _number(track.get("volume", .7), 0, 4, "volume")
            automation.validate_volume(track.get("volume_keyframes", []), length)
            _number(track.get("fade_in", 0), 0, length, "fade_in")
            _number(track.get("fade_out", 0), 0, length, "fade_out")
            if float(track.get("start", 0)) >= duration:
                warnings.append(f"Audio {index+1} starts after the end of the timeline and will be skipped.")
        check(f"Audio {index+1}", audio_check)
    for index, overlay in enumerate(collections["overlays"]):
        def overlay_check():
            asset = _asset(overlay.get("asset_id"), resolve_asset, cache)
            metadata = probe(asset["path"])
            if not metadata["has_video"]:
                raise ValueError("Overlay must be an image or video")
            start = _number(overlay.get("start", 0), 0, 14400, "start")
            length = _number(overlay.get("duration"), .001, 14400, "duration")
            source_in = _number(overlay.get("in", 0), 0, 86400, "in")
            for key, default, lo, hi in (("opacity", .6, 0, 1), ("width", 1, .01, 4), ("x", .5, 0, 1), ("y", .5, 0, 1)):
                _number(overlay.get(key, default), lo, hi, key)
            if overlay.get("blend", "screen") not in ("normal", "screen", "add", "lighten", "chroma"):
                raise ValueError("Unknown overlay blend mode")
            if not COLORS.fullmatch(overlay.get("key_color", "#00ff00")):
                raise ValueError("key_color must be #RRGGBB")
            _number(overlay.get("key_similarity", .15), .01, 1, "key_similarity")
            if not _is_image(asset) and metadata["duration"]:
                if source_in >= metadata["duration"]:
                    raise ValueError("Overlay in is beyond the end of its source")
                if not overlay.get("loop") and source_in+length > metadata["duration"]+.06:
                    warnings.append(f"Overlay {index+1} will disappear when its finite source ends; it will not freeze.")
            if start >= duration:
                warnings.append(f"Overlay {index+1} starts after the timeline and will be skipped.")
        check(f"Overlay {index+1}", overlay_check)
    for index, shape in enumerate(collections["shapes"]):
        check(f"Shape {index+1}", lambda shape=shape: shapes.validate_shape(shape, duration))
    for index, accent in enumerate(collections["accents"]):
        check(f"Accent {index+1}", lambda accent=accent: graphics.validate_accent(accent))
        if isinstance(accent, dict) and isinstance(accent.get("start", 0), (int, float)) and accent.get("start", 0) >= duration:
            warnings.append(f"Accent {index+1} starts after the timeline and will be skipped.")
    for index, title in enumerate(collections["titles"]):
        def title_check():
            graphics.validate_text_motion(title)
            text = title.get("text", "")
            if not isinstance(text, str) or len(text) > 4000 or "\x00" in text:
                raise ValueError("Text must contain at most 4000 characters without NUL")
            _number(title.get("start", 0), 0, 14400, "start")
            _number(title.get("duration"), .001, 14400, "duration")
            _number(title.get("font_size", 64), 4, 512, "font_size")
            _number(title.get("x", .5), 0, 1, "x")
            _number(title.get("y", .8), 0, 1, "y")
            _number(title.get("fade", .15), 0, 10, "fade")
            if not COLORS.fullmatch(title.get("color", "#ffffff")):
                raise ValueError("color must be #RRGGBB")
            if title.get("font_asset_id"):
                font = _asset(title["font_asset_id"], resolve_asset, cache)
                if font.get("kind") != "font" or Path(font["path"]).suffix.lower() not in (".ttf", ".otf", ".ttc"):
                    raise ValueError("font_asset_id must refer to a font file")
        check(f"Title {index+1}", title_check)
    def caption_style_check():
        supplied = project.get("caption_style", {})
        if not isinstance(supplied, dict):
            raise ValueError("caption_style must be an object")
        style = {**CAPTION_STYLE, **supplied}
        graphics.validate_text_motion(style)
        if style["preset"] not in ("clean", "bold", "boxed", "neon"):
            raise ValueError("preset must be clean, bold, boxed, or neon")
        if style["position"] not in ("bottom", "top", "center"):
            raise ValueError("position must be bottom, top, or center")
        _number(style["font_size"], 8, 512, "font_size")
        _number(style["outline"], 0, 12, "outline")
        _number(style["margin"], 0, 2000, "margin")
        for key in ("color", "outline_color"):
            if not isinstance(style[key], str) or not COLORS.fullmatch(style[key]):
                raise ValueError(f"{key} must be #RRGGBB or #RRGGBBAA")
        if style["font_asset_id"]:
            font = _asset(style["font_asset_id"], resolve_asset, cache)
            if font.get("kind") != "font" or Path(font["path"]).suffix.lower() not in (".ttf", ".otf", ".ttc"):
                raise ValueError("font_asset_id must refer to a font file")
    check("Caption style", caption_style_check)
    caption_characters = 0
    for index, caption in enumerate(collections["captions"]):
        def caption_check():
            if not isinstance(caption, dict):
                raise ValueError("Caption must be an object")
            start = _number(caption.get("start"), 0, 14400, "start")
            end = _number(caption.get("end"), start+.01, 14400, "end")
            text = caption.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise ValueError("Text must contain 1 to 2000 characters")
            if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
                raise ValueError("Caption text contains unsupported control characters")
            if start >= duration:
                warnings.append(f"Caption {index+1} starts after the timeline and will be skipped.")
            elif end > duration+.01:
                warnings.append(f"Caption {index+1} extends beyond the timeline and will end with the video.")
        check(f"Caption {index+1}", caption_check)
        if isinstance(caption, dict) and isinstance(caption.get("text"), str):
            caption_characters += len(caption["text"])
    if caption_characters > 500000:
        errors.append("Captions exceed the 500,000-character project limit")
    return {"valid": not errors, "renderable": bool(clips) and not errors,
            "errors": errors, "warnings": warnings, "duration": duration}


def _shape(project, quality):
    if quality not in ("preview", "final"):
        raise ValueError("quality must be preview or final")
    canvas = project.get("canvas", {})
    w, h = int(canvas.get("width", 1920)), int(canvas.get("height", 1080))
    ratio = min(1., 960/max(w, h)) if quality == "preview" else 1.
    return max(2, int(w*ratio)//2*2), max(2, int(h*ratio)//2*2), float(canvas.get("fps", 30))


def _segments(clip, fps):
    if clip.get("freeze") is not None:
        return [{"in": float(clip["freeze"]["time"]), "source_duration": 0., "speed": 1.,
                 "frames": max(1, round(float(clip["freeze"]["duration"])*fps))}]
    source_in = float(clip.get("in", 0))
    segments = clip.get("segments") or [{"start": 0., "end": float(clip["out"])-source_in, "speed": clip.get("speed", 1)}]
    return [{"in": source_in+float(s["start"]), "source_duration": float(s["end"])-float(s["start"]),
             "speed": float(s.get("speed", 1)),
             "frames": max(1, round((float(s["end"])-float(s["start"]))/float(s.get("speed", 1))*fps))}
            for s in segments]


def _timings(project, fps):
    clips = project["clips"]
    lengths = [sum(s["frames"] for s in _segments(c, fps)) for c in clips]
    transitions = [max(0, round(_transition_duration(c)*fps)) for c in clips[:-1]] + [0]
    for i, length in enumerate(lengths):
        if (transitions[i-1] if i else 0)+transitions[i] > length:
            raise ValueError(f"Clip {i+1}: transitions exceed its duration after frame rounding")
    return lengths, transitions


def render_plan(project, resolve_asset, quality="preview"):
    validation = validate_project(project, resolve_asset)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    if not project.get("clips"):
        raise ValueError("Add at least one footage clip before rendering")
    width, height, fps = _shape(project, quality)
    lengths, transitions = _timings(project, fps)
    rendered = (sum(lengths)-sum(transitions))/fps
    warnings = list(validation["warnings"])
    if abs(rendered-validation["duration"]) > .001:
        warnings.append("Clip and speed-segment endpoints are rounded to whole video frames.")
    cadence = []
    for index, clip in enumerate(project["clips"]):
        asset = resolve_asset(clip["asset_id"])
        if clip.get("freeze") or _is_image(asset):
            continue
        source_fps = probe(asset["path"])["fps"]
        rates = [source_fps*s["speed"] for s in _segments(clip, fps)]
        low = min(rates)
        interpolation = clip.get("interpolation", "duplicate")
        cadence.append({"clip_id": clip.get("id"), "source_fps": source_fps,
                        "minimum_unique_fps": low, "output_fps": fps, "interpolation": interpolation})
        if low < fps*.95:
            if interpolation == "optical_flow":
                warnings.append(f"Clip {index+1}: optical flow synthesizes frames from {low:.2f} unique fps; inspect fast movement and HUD edges for artifacts. Rendering is slower.")
            else:
                warnings.append(f"Clip {index+1}: only {low:.2f} unique fps at {fps:g} fps output. Duplicated frames can stutter; use real-time footage, a higher-rate source, or optical_flow interpolation.")
        if any(e.get("name") == "echo_trails" and e.get("start", 0) == 0 and e.get("end", clip_duration(clip)) >= clip_duration(clip) for e in clip.get("effects", [])):
            warnings.append(f"Clip {index+1}: full-length echo trails create ghosting; use short windows for sharp gameplay.")
        if clip.get("motion_blur", 0):
            warnings.append(f"Clip {index+1}: motion blur samples at twice output fps using optical flow when needed. It increases render time and can distort fast movement; inspect the preview.")
    high = quality == "final" and project.get("export_profile") == "high"
    return {"quality": quality, "width": width, "height": height, "fps": fps,
            "export_profile": project.get("export_profile", "standard"), "final_crf": 23 if quality == "preview" else 16 if high else 18,
            "cadence": cadence, "accent_count": len(project.get("accents", [])),
            "duration": rendered, "requested_duration": validation["duration"],
            "stages": [{"name": "normalize_clips", "count": len(lengths)},
                       {"name": "transition_sections", "count": sum(t > 0 for t in transitions)},
                       {"name": "composite_overlays", "count": len(project.get("overlays", []))},
                       {"name": "draw_shapes", "count": len(project.get("shapes", []))},
                       {"name": "mix_audio", "count": len(project.get("audio", []))},
                       {"name": "titles_and_export", "count": 1}],
            "caption_count": len(project.get("captions", [])),
            "caption_method": "Literal timed captions, animated neon words and native vector accents share one libass export pass",
            "warnings": warnings, "threads": THREADS,
            "video_codec": "h264", "audio_codec": "aac", "audio_sample_rate": 48000,
            "speed_method": "Piecewise constant retiming with pitch-preserving audio; optional motion-compensated optical flow per clip.",
            "animation_method": "Eased motion and sample-accurate volume keyframes in local output seconds, before transitions.",
            "freeze_method": "Native frame hold at absolute source time; silent, with duration independent of speed.",
            "audio_normalization": "Single-pass dynamic loudness normalization to -16 LUFS" if project.get("normalize_audio", True) else "Peak limiter"}


class _Runner:
    def __init__(self, work_dir, progress, cancelled, steps):
        self.work = Path(work_dir)
        self.progress = progress or (lambda fraction, message: None)
        self.cancelled = cancelled or (lambda: False)
        self.steps, self.done, self.command_index = max(1, steps), 0, 0

    def check_cancelled(self):
        if self.cancelled():
            raise RenderCancelled("Render cancelled")

    def run(self, arguments, duration, message, count=True):
        self.check_cancelled()
        self.command_index += 1
        log_path = self.work / f"ffmpeg-{self.command_index:04d}.log"
        bounded_arguments = []
        for argument in arguments:
            if argument == "-i":
                # Input codec options reset after each input; bound every decoder,
                # including the second clip in transitions and overlay sources.
                bounded_arguments.extend(("-threads", str(THREADS)))
            bounded_arguments.append(str(argument))
        command = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "warning",
                   "-threads", str(THREADS), "-filter_threads", "1", "-filter_complex_threads", "1",
                   "-progress", "pipe:1", "-nostats"] + bounded_arguments
        with (self.work / "commands.jsonl").open("a", encoding="utf-8") as command_log:
            command_log.write(json.dumps({"message": message, "argv": command, "log": str(log_path)})+"\n")
        self.progress(min(.98, self.done/self.steps), message)
        process = None
        with log_path.open("wb") as log:
            try:
                process = subprocess.Popen(command, cwd=self.work, stdout=subprocess.PIPE, stderr=log,
                                           stdin=subprocess.DEVNULL)
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                pending = b""
                last_position, last_advance = -1., time.monotonic()
                while process.poll() is None:
                    self.check_cancelled()
                    if time.monotonic()-last_advance > STALL_TIMEOUT:
                        raise RenderError(f"{message}: FFmpeg stopped advancing for {STALL_TIMEOUT:g} seconds; render stopped. See {log_path.name} and commands.jsonl.")
                    for key, _ in selector.select(.15):
                        chunk = os.read(key.fileobj.fileno(), 16384)
                        if not chunk:
                            continue
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            if line.startswith(b"out_time_us="):
                                try:
                                    position = max(0., float(line.split(b"=", 1)[1])/1e6)
                                    if position > last_position+.000001:
                                        last_position, last_advance = position, time.monotonic()
                                    fraction = min(1., position/max(.001, duration))
                                    self.progress(min(.98, (self.done+fraction)/self.steps), message)
                                except ValueError:
                                    pass
                selector.close()
                self.check_cancelled()
                if process.returncode:
                    detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                    raise RenderError(f"{message} failed (FFmpeg {process.returncode}). {detail.strip()}")
            except BaseException:
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                raise
            finally:
                if process and process.stdout:
                    process.stdout.close()
        if count:
            self.done += 1
        self.progress(min(.98, self.done/self.steps), message)


def _codec(quality):
    return ["-c:v", "libx264", "-preset", "veryfast" if quality == "preview" else "fast",
            "-crf", "19" if quality == "preview" else "12" if quality == "high" else "16", "-pix_fmt", "yuv420p", "-threads", str(THREADS),
            "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2"]


def _fit(width, height, fit, background, transform=None):
    transform = transform or {}
    x, y = float(transform.get("x", .5)), float(transform.get("y", .5))
    zoom = float(transform.get("zoom", 1))
    before = []
    rotation = transform.get("rotation", 0)
    if rotation == 90:
        before.append("transpose=clock")
    elif rotation == -90:
        before.append("transpose=cclock")
    elif abs(rotation) == 180:
        before.extend(("hflip", "vflip"))
    if transform.get("flip_x", False):
        before.append("hflip")
    if transform.get("flip_y", False):
        before.append("vflip")
    square_pixels = "scale=w='max(2,trunc(iw*sar/2)*2)':h=ih,setsar=1,"
    if fit == "contain":
        fit_filter = square_pixels+f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)*{x:.9f}:(oh-ih)*{y:.9f}:color={background}"
    else:
        fit_filter = square_pixels+f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={width}:{height}:(iw-ow)*{x:.9f}:(ih-oh)*{y:.9f}"
    before.append(fit_filter)
    if zoom > 1:
        zw, zh = math.ceil(width*zoom/2)*2, math.ceil(height*zoom/2)*2
        before.append(f"scale={zw}:{zh},crop={width}:{height}:(iw-ow)*{x:.9f}:(ih-oh)*{y:.9f}")
    return ",".join(before)


def _color_filter(clip):
    color = {**COLOR_DEFAULTS, **clip.get("color", {})}
    if all(color[key] == default for key, default in COLOR_DEFAULTS.items()):
        return ""
    return ",eq="+":".join(f"{key}={float(color[key]):.9f}" for key in COLOR_DEFAULTS)


def _needs_effect_pass(clip):
    return bool(clip.get("effects") or clip.get("lut_asset_id") or clip.get("fade_in") or clip.get("fade_out")
                or clip.get("motion") or clip.get("volume_keyframes"))


def _atempo(speed):
    values = []
    while speed > 2.+1e-8:
        values.append(2.)
        speed /= 2
    while speed < .5-1e-8:
        values.append(.5)
        speed /= .5
    values.append(speed)
    return ",".join(f"atempo={v:.9f}" for v in values)


def _concat(runner, paths, output, duration, message):
    # All section basenames are generated here; no user data enters concat syntax.
    manifest = runner.work / (Path(output).stem+"-concat.txt")
    manifest.write_text("".join(f"file '{Path(p).name}'\n" for p in paths), encoding="utf-8")
    runner.run(["-f", "concat", "-safe", "1", "-i", manifest.name,
                "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-t", f"{duration:.9f}", output],
               duration, message)


def _safe_link(source, destination):
    destination = Path(destination)
    if not destination.exists():
        try:
            destination.symlink_to(Path(source).resolve())
        except OSError:
            shutil.copyfile(source, destination)
    return destination.name


def _overlay_batches(overlays, duration):
    """Group consecutive active normal layers without reordering blend modes."""
    batch = []
    for index, overlay in enumerate(overlays):
        if min(float(overlay["duration"]), duration-float(overlay.get("start", 0))) <= 0:
            continue
        if overlay.get("blend", "screen") != "normal":
            if batch:
                yield batch
                batch = []
            yield [(index, overlay)]
        else:
            batch.append((index, overlay))
            if len(batch) == NORMAL_OVERLAY_BATCH_SIZE:
                yield batch
                batch = []
    if batch:
        yield batch


def _overlay_input_duration(overlay, asset, length, fps):
    # Concatenated Matroska sections have millisecond time bases. Their last
    # frame can be a few ms later than its nominal output-frame timestamp;
    # framesync must still find an opaque frame rather than trailing padding.
    # Decode a little extra only for inexhaustible still/loop inputs. The enable
    # expression remains authoritative, and finite source ends stay unchanged.
    return length+2/fps if _is_image(asset) or overlay.get("loop") else length


def _overlay_base_clock(fps):
    # Normalization has already produced one frame per canvas tick. Container
    # duration rounding during concat can accumulate beyond the overlay's end
    # on some FFmpeg versions. Restore that intended clock without duplicating
    # or dropping pictures, so every layer sees the exported frame timestamps.
    return f"settb=AVTB,setpts=N/({fps:.9f}*TB)"


def _normal_overlay_batch(runner, base, batch, resolve_asset, cache, width, fps, duration, quality, output):
    """Composite bounded normal-alpha layers in one pass, retaining base audio.

    Every overlay still begins at timestamp zero with transparent leading and
    trailing frames. Merely shifting its first PTS into the future can deadlock
    the FFmpeg 7/8 scheduler when the unchanged base audio fills its queue.
    """
    args, graph = ["-i", str(base)], [f"[0:v]{_overlay_base_clock(fps)}[bg0]"]
    for slot, (_, overlay) in enumerate(batch, 1):
        asset = _asset(overlay["asset_id"], resolve_asset, cache)
        start = float(overlay.get("start", 0))
        length = min(float(overlay["duration"]), duration-start)
        if _is_image(asset):
            args += ["-loop", "1", "-framerate", f"{fps:.9f}"]
        else:
            if overlay.get("loop"):
                args += ["-stream_loop", "-1"]
            args += ["-ss", f"{float(overlay.get('in', 0)):.9f}"]
        coverage = _overlay_input_duration(overlay, asset, length, fps)
        args += ["-t", f"{coverage:.9f}", "-i", asset["path"]]
        overlay_width = max(2, round(width*float(overlay.get("width", 1))/2)*2)
        x, y = float(overlay.get("x", .5)), float(overlay.get("y", .5))
        opacity = float(overlay.get("opacity", .6))
        # Keep framesync coverage beyond the final base timestamp as well as
        # decoding it; trimming this stream at duration would discard the fix.
        padded_duration = duration+2/fps
        graph.append(f"[{slot}:v]setpts=PTS-STARTPTS,fps={fps:.9f},scale={overlay_width}:-2,setsar=1,format=rgba,"
                     f"colorchannelmixer=aa={opacity:.9f},tpad=start_mode=add:start_duration={start:.9f}:"
                     f"stop_mode=add:stop_duration={duration:.9f}:color=black@0,trim=duration={padded_duration:.9f},"
                     f"setpts=PTS-STARTPTS[ov{slot}]")
        enabled = f"gte(t,{start:.9f})*lt(t,{start+length:.9f})"
        # Match the existing per-layer pixel format and placement semantics;
        # the omitted lossy encode is the only intentional visual difference.
        graph.append(f"[bg{slot-1}][ov{slot}]overlay=x='(W-w)*{x:.9f}':y='(H-h)*{y:.9f}':"
                     f"eof_action=pass:repeatlast=0:enable='{enabled}',format=yuv420p[bg{slot}]")
    runner.run(args+["-filter_complex", ";".join(graph), "-map", f"[bg{len(batch)}]", "-map", "0:a",
                     *_codec(quality), "-t", f"{duration:.9f}", str(output)], duration,
               f"Compositing normal overlays {batch[0][0]+1}–{batch[-1][0]+1} in one pass")


def _effect_pass(runner, input_path, output, clip, asset_cache, resolve_asset, width, height, fps, duration, quality, prefix):
    graph, source = [], "0:v"
    if clip.get("motion"):
        source = f"{prefix}motion"
        graph.append(f"[0:v]setpts=PTS-STARTPTS,{automation.motion_filter(clip['motion'], width, height, fps)}[{source}]")
    effect_graph, label = effects.build_graph(source, clip.get("effects", []), width, height, duration, fps, prefix,
                                              logical_duration=clip_duration(clip))
    graph.extend(effect_graph)
    if clip.get("lut_asset_id"):
        asset = _asset(clip["lut_asset_id"], resolve_asset, asset_cache)
        filename = _safe_link(asset["path"], runner.work/f"{prefix}-lut{Path(asset['path']).suffix.lower()}")
        graph.append(f"[{label}]lut3d=file={filename}[{prefix}lut]")
        label = f"{prefix}lut"
    fades = []
    for key in ("fade_in", "fade_out"):
        length = min(duration, float(clip.get(key, 0)))
        if length > 0:
            kind, start = ("in", 0) if key == "fade_in" else ("out", duration-length)
            fades.append(f"fade=t={kind}:st={start:.9f}:d={length:.9f}")
    if fades:
        graph.append(f"[{label}]{','.join(fades)}[{prefix}faded]")
        label = f"{prefix}faded"
    graph.append(f"[{label}]format=yuv420p[v]")
    audio = "0:a:0"
    if clip.get("volume_keyframes"):
        graph.append(f"[0:a:0]asetpts=PTS-STARTPTS,{automation.volume_filter(clip['volume_keyframes'])}[a]")
        audio = "[a]"
    runner.run(["-i", input_path, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", audio,
                *_codec(quality), "-t", f"{duration:.9f}", output], duration, "Applying clip effects")


def _ass_color(value):
    """ASS colors are alpha-blue-green-red, with inverse opacity."""
    raw = value[1:]
    opacity = int(raw[6:8], 16) if len(raw) == 8 else 255
    return f"&H{255-opacity:02X}{raw[4:6]}{raw[2:4]}{raw[0:2]}".upper()


def _ass_text(value):
    """Escape literal text for libass, never accepting ASS override tags.

    libass supports escaped braces, but doubling a backslash does not disable
    sequences such as \\N. An invisible word joiner separates literal backslashes
    from the next character while preserving their visible appearance. Actual
    newlines are inserted only after that escaping step.
    """
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    return (normalized.replace("\\", "\\\u2060").replace("{", "\\{").replace("}", "\\}")
            .replace("\t", "    ").replace("\n", "\\N"))


def _ass_timestamp(centiseconds):
    seconds, fraction = divmod(int(centiseconds), 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _caption_font(asset, work):
    """Load a single resolved font; never interpolate its path into ASS syntax."""
    font_scan = shutil.which("fc-scan")
    if not font_scan:
        raise RenderError("Custom caption fonts require fc-scan from the fontconfig package")
    try:
        result = subprocess.run([font_scan, "--format", "%{family[0]}\n", asset["path"]],
                                capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RenderError(f"Cannot read the selected caption font: {exc}") from exc
    family = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if result.returncode or not family:
        raise RenderError("The selected caption font has no readable font family")
    if len(family) > 200 or any(ch in family for ch in ",\r\n{}\\") or any(ord(ch) < 32 for ch in family):
        raise RenderError("This caption font's family name cannot safely be represented in ASS; choose another font")
    folder = work/"caption-fonts"
    folder.mkdir(exist_ok=True)
    _safe_link(asset["path"], folder/("font-"+hashlib.sha256(str(asset["path"]).encode()).hexdigest()[:16]+Path(asset["path"]).suffix.lower()))
    return family


def _write_captions(project, resolve_asset, asset_cache, work, duration):
    cues = project.get("captions", [])
    titles = [t for t in project.get("titles", []) if graphics.animated_title(t)]
    accents = project.get("accents", [])
    if not cues and not titles and not accents:
        return None, 0
    style = {**CAPTION_STYLE, **project.get("caption_style", {})}
    family = "DejaVu Sans"
    if style["font_asset_id"]:
        family = _caption_font(_asset(style["font_asset_id"], resolve_asset, asset_cache), work)
    canvas = project.get("canvas", {})
    width, height = int(canvas.get("width", 1920)), int(canvas.get("height", 1080))
    alignment = {"bottom": 2, "top": 8, "center": 5}[style["position"]]
    bold = -1 if style["preset"] in ("bold", "neon") else 0
    border = 3 if style["preset"] == "boxed" else 1
    shadow = 0 if style["preset"] == "boxed" else 1
    margin = int(style["margin"])
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
             "ScaledBorderAndShadow: yes", "WrapStyle: 0", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Caption,{family},{float(style['font_size']):.4f},{_ass_color(style['color'])},{_ass_color(style['color'])},{_ass_color(style['outline_color'])},&H80000000,{bold},0,0,0,100,100,0,0,{border},{float(style['outline']):.4f},{shadow},{alignment},{margin},{margin},{margin},1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    count = 0
    for cue in sorted(cues, key=lambda c: (float(c["start"]), float(c["end"]))):
        # ASS stores centiseconds. Round inward so captions cannot appear before
        # their requested start or linger past their requested exclusive end.
        start = math.ceil(float(cue["start"])*100-1e-7)
        end = math.floor(min(duration, float(cue["end"]))*100+1e-7)
        if end <= start:
            continue
        y = {"bottom": height-margin, "top": margin, "center": height/2}[style["position"]]
        for a, b, layer, payload in graphics.text_events(style, (end-start)/100, width/2, y, _ass_text(cue["text"]), alignment=alignment):
            lines.append(f"Dialogue: {20+layer},{_ass_timestamp(start+round(a*100))},{_ass_timestamp(start+round(b*100))},Caption,,0,0,0,,{payload}")
        count += 1
    def event(start, end, layer, name, payload):
        a = math.ceil(float(start)*100-1e-7)
        b = math.floor(min(duration,float(end))*100+1e-7)
        if b > a:
            lines.append(f"Dialogue: {layer},{_ass_timestamp(a)},{_ass_timestamp(b)},{name},,0,0,0,,{payload}")
    for index, title in enumerate(titles):
        font = "DejaVu Sans"
        if title.get("font_asset_id"):
            font = _caption_font(_asset(title["font_asset_id"], resolve_asset, asset_cache), work)
        name = f"Title{index}"
        box = 3 if title.get("box", True) else 1
        style_line = f"Style: {name},{font},{float(title.get('font_size',64))},{_ass_color(title.get('color','#ffffff'))},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,{box},1,0,5,0,0,0,1"
        lines.insert(lines.index("[Events]")-1, style_line)
        start = math.ceil(float(title.get("start",0))*100-1e-7)/100
        end = math.floor(min(duration,float(title.get("start",0))+float(title["duration"]))*100+1e-7)/100
        if end <= start: continue
        for a,b,layer,payload in graphics.text_events(title,end-start,float(title.get("x",.5))*width,float(title.get("y",.8))*height,_ass_text(title["text"])):
            event(start+a,start+b,10+layer,name,payload)
    for accent in accents:
        start = math.ceil(float(accent.get("start",0))*100-1e-7)/100
        end = math.floor(min(duration,float(accent.get("start",0))+float(accent.get("duration",.4)))*100+1e-7)/100
        if end <= start: continue
        for layer, payload in graphics.accent_layers(accent,width,height,end-start):
            event(start,end,layer,"Caption",payload)
    if not any(line.startswith("Dialogue:") for line in lines):
        return None, 0
    path = work/"captions.ass"
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    # Only generated constant basenames enter the filter, independent of user
    # paths. Script resolution scales caption typography for preview rendering.
    return "ass=filename=captions.ass:fontsdir=caption-fonts" if (work/"caption-fonts").exists() else "ass=filename=captions.ass", count


def render_project(project, resolve_asset, output_path, work_dir, quality="preview", progress=None, cancelled=None):
    plan = render_plan(project, resolve_asset, quality)
    if quality == "final" and project.get("export_profile") == "high":
        quality = "high"
    output = Path(output_path).expanduser().resolve()
    work = Path(work_dir).expanduser().resolve()
    if output.exists():
        raise ValueError("Output already exists; use a new render path")
    if output.suffix.lower() != ".mp4":
        raise ValueError("Render output must use the .mp4 extension")
    cache = {}
    for group in ("clips", "audio", "overlays"):
        for item in project.get(group, []):
            if output == Path(_asset(item["asset_id"], resolve_asset, cache)["path"]):
                raise ValueError("Cannot overwrite source media")
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if (work/"commands.jsonl").exists():
        raise ValueError("Render work directory has already been used; choose a new directory")
    width, height, fps, duration = plan["width"], plan["height"], plan["fps"], plan["duration"]
    clips = project["clips"]
    lengths, transitions = _timings(project, fps)
    overlay_batches = list(_overlay_batches(project.get("overlays", []), duration))
    steps = sum(len(_segments(c, fps))+int(bool(c.get("segments")))+int(_needs_effect_pass(c)) for c in clips)
    steps += len(clips)+sum(t>0 for t in transitions)+len(overlay_batches)+len(project.get("shapes", []))+2*len(project.get("audio", []))+2
    runner = _Runner(work, progress, cancelled, steps)
    normalized = []
    background = "0x"+project.get("canvas", {}).get("background", "#101014")[1:]
    for index, clip in enumerate(clips):
        asset = _asset(clip["asset_id"], resolve_asset, cache)
        metadata = probe(asset["path"])
        segments = _segments(clip, fps)
        segment_paths = []
        for si, segment in enumerate(segments):
            target = work/f"clip-{index:04d}-segment-{si:03d}.mkv"
            segment_duration = segment["frames"]/fps
            args = []
            frozen = clip.get("freeze") is not None
            if _is_image(asset):
                args += ["-loop", "1", "-framerate", f"{fps:.9f}", "-i", asset["path"]]
            elif frozen:
                # Snap down to a source frame boundary. A timestamp within the
                # final frame must hold that frame rather than seeking past EOF.
                source_fps = metadata["fps"] or fps
                seek = math.floor(segment["in"]*source_fps+1e-7)/source_fps
                if metadata["duration"]:
                    seek = min(seek, max(0., metadata["duration"]-1/source_fps))
                args += ["-ss", f"{seek:.9f}", "-i", asset["path"]]
            else:
                args += ["-ss", f"{segment['in']:.9f}", "-t", f"{segment['source_duration']:.9f}", "-i", asset["path"]]
            has_audio = metadata["has_audio"] and not _is_image(asset) and not frozen
            if not has_audio:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            fit = clip.get("fit", project.get("canvas", {}).get("fit", "cover"))
            hold = "trim=end_frame=1,setpts=PTS-STARTPTS," if frozen else ""
            pad = f"tpad=stop_mode=clone:stop_duration={segment_duration:.9f}"
            cadence = f"{pad},fps={fps:.9f}" if frozen else f"fps={fps:.9f},{pad}"
            blur = float(clip.get("motion_blur", 0)) if not frozen and not _is_image(asset) else 0
            sample_fps = fps*2 if blur else fps
            if not frozen and not _is_image(asset) and (blur or clip.get("interpolation") == "optical_flow") and metadata["fps"]*segment["speed"] < sample_fps*.95:
                # minterpolate needs lookahead. Clone a bounded tail before it,
                # then trim to the exact frame-rounded segment duration.
                cadence = (f"tpad=stop_mode=clone:stop_duration={max(.25,3/max(1,metadata['fps']*segment['speed'])):.9f},"
                           f"minterpolate=fps={sample_fps:.9f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff:scd_threshold=10,{pad}")
            elif blur:
                cadence = f"fps={sample_fps:.9f},{pad}"
            if blur:
                cadence += f",tmix=frames=2:weights='{blur:.9f} 1',fps={fps:.9f}"
            vf = f"[0:v:0]{hold}setpts=(PTS-STARTPTS)/{segment['speed']:.9f},{_fit(width,height,fit,background,clip.get('transform'))}{_color_filter(clip)},setsar=1,{cadence},trim=duration={segment_duration:.9f},settb=AVTB,format=yuv420p[v]"
            af = f"[{0 if has_audio else 1}:a:0]asetpts=PTS-STARTPTS,{_atempo(segment['speed']) if has_audio else 'anull'},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={float(clip.get('volume',1)):.9f},apad=whole_dur={segment_duration:.9f},atrim=duration={segment_duration:.9f},asetpts=PTS-STARTPTS[a]"
            runner.run(args+["-filter_complex", vf+";"+af, "-map", "[v]", "-map", "[a]",
                             *_codec(quality), "-t", f"{segment_duration:.9f}", str(target)],
                       segment_duration, f"Preparing clip {index+1}/{len(clips)} · segment {si+1}/{len(segments)}")
            segment_paths.append(target)
        clip_path = segment_paths[0]
        clip_length = lengths[index]/fps
        if len(segment_paths) > 1:
            clip_path = work/f"clip-{index:04d}-retimed.mkv"
            _concat(runner, segment_paths, str(clip_path), clip_length, f"Joining speed segments for clip {index+1}")
        if _needs_effect_pass(clip):
            target = work/f"clip-{index:04d}-effects.mkv"
            _effect_pass(runner, str(clip_path), str(target), clip, cache, resolve_asset, width, height, fps, clip_length, quality, f"c{index}fx")
            clip_path = target
        normalized.append(clip_path)
    sections = []
    for index, clip_path in enumerate(normalized):
        incoming = transitions[index-1] if index else 0
        outgoing = transitions[index]
        body_frames = lengths[index]-incoming-outgoing
        if body_frames > 0:
            if incoming == outgoing == 0:
                sections.append(clip_path)
            else:
                body_duration = body_frames/fps
                target = work/f"section-{index:04d}-body.mkv"
                graph = f"[0:v]setpts=PTS-STARTPTS,fps={fps:.9f},trim=duration={body_duration:.9f},settb=AVTB[v];[0:a]asetpts=PTS-STARTPTS,atrim=duration={body_duration:.9f}[a]"
                runner.run(["-ss", f"{incoming/fps:.9f}", "-i", str(clip_path), "-filter_complex", graph,
                            "-map", "[v]", "-map", "[a]", *_codec(quality), "-t", f"{body_duration:.9f}", str(target)],
                           body_duration, f"Preparing body of clip {index+1}")
                sections.append(target)
        if outgoing:
            transition_duration = outgoing/fps
            target = work/f"section-{index:04d}-transition.mkv"
            kind = clips[index].get("transition", {}).get("name", "fade")
            graph = f"[0:v]setpts=PTS-STARTPTS,fps={fps:.9f},settb=AVTB,trim=duration={transition_duration:.9f},format=yuv420p[v0];[1:v]setpts=PTS-STARTPTS,fps={fps:.9f},settb=AVTB,trim=duration={transition_duration:.9f},format=yuv420p[v1];[v0][v1]xfade=transition={kind}:duration={transition_duration:.9f}:offset=0,trim=duration={transition_duration:.9f},format=yuv420p[v];[0:a]asetpts=PTS-STARTPTS,apad=whole_dur={transition_duration:.9f},atrim=duration={transition_duration:.9f}[a0];[1:a]asetpts=PTS-STARTPTS,apad=whole_dur={transition_duration:.9f},atrim=duration={transition_duration:.9f}[a1];[a0][a1]acrossfade=d={transition_duration:.9f}:c1=tri:c2=tri[a]"
            runner.run(["-ss", f"{(lengths[index]-outgoing)/fps:.9f}", "-t", f"{transition_duration:.9f}", "-i", str(clip_path),
                        "-t", f"{transition_duration:.9f}", "-i", str(normalized[index+1]), "-filter_complex", graph,
                        "-map", "[v]", "-map", "[a]", *_codec(quality), "-t", f"{transition_duration:.9f}", str(target)],
                       transition_duration, f"Rendering {kind} transition {index+1}")
            sections.append(target)
    base = work/"timeline.mkv"
    _concat(runner, sections, str(base), duration, "Assembling the timeline")
    for batch in overlay_batches:
        runner.check_cancelled()
        if len(batch) > 1:
            target = work/f"overlays-{batch[0][0]:03d}-{batch[-1][0]:03d}.mkv"
            _normal_overlay_batch(runner, base, batch, resolve_asset, cache, width, fps, duration, quality, target)
            base = target
            continue
        index, overlay = batch[0]
        start = float(overlay.get("start", 0))
        length = min(float(overlay["duration"]), duration-start)
        if length <= 0:
            continue
        asset = _asset(overlay["asset_id"], resolve_asset, cache)
        args = ["-i", str(base)]
        if _is_image(asset):
            args += ["-loop", "1", "-framerate", f"{fps:.9f}"]
        elif overlay.get("loop"):
            args += ["-stream_loop", "-1"]
        if not _is_image(asset):
            args += ["-ss", f"{float(overlay.get('in',0)):.9f}"]
        coverage = _overlay_input_duration(overlay, asset, length, fps)
        args += ["-t", f"{coverage:.9f}", "-i", asset["path"]]
        blend = overlay.get("blend", "screen")
        overlay_width = max(2, round(width*float(overlay.get("width", 1))/2)*2)
        x, y, opacity = float(overlay.get("x", .5)), float(overlay.get("y", .5)), float(overlay.get("opacity", .6))
        preparation = f"[1:v]setpts=PTS-STARTPTS,fps={fps:.9f},scale={int(overlay_width)}:-2,setsar=1,format=rgba"
        if blend == "chroma":
            preparation += f",colorkey=0x{overlay.get('key_color','#00ff00')[1:]}:{float(overlay.get('key_similarity',.15)):.9f}:.1"
        preparation += f",colorchannelmixer=aa={opacity:.9f}"
        enabled = f"gte(t,{start:.9f})*lt(t,{start+length:.9f})"
        if blend in ("normal", "chroma"):
            # Feed framesync from timestamp zero. A future first overlay timestamp
            # can deadlock FFmpeg 7/8's threaded scheduler when base audio fills its
            # queue while the video filter waits for the delayed second stream.
            # Transparent/black leading frames remove that queue dependency.
            graph = preparation+f",tpad=start_mode=add:start_duration={start:.9f}:stop_mode=add:stop_duration={duration:.9f}:color=black@0,trim=duration={duration+2/fps:.9f},setpts=PTS-STARTPTS[ov];[0:v]{_overlay_base_clock(fps)}[bg];[bg][ov]overlay=x='(W-w)*{x:.9f}':y='(H-h)*{y:.9f}':eof_action=pass:repeatlast=0:enable='{enabled}',format=yuv420p[v]"
        else:
            mode = {"screen": "screen", "add": "addition", "lighten": "lighten"}[blend]
            graph = preparation+f"[ov];color=c=black:s={width}x{height}:r={fps:.9f}:d={length:.9f},format=rgba[black];[black][ov]overlay=x='(W-w)*{x:.9f}':y='(H-h)*{y:.9f}':eof_action=pass:repeatlast=0,format=gbrp,tpad=start_mode=add:start_duration={start:.9f}:stop_mode=add:stop_duration={duration:.9f}:color=black,trim=duration={duration:.9f},setpts=PTS-STARTPTS[plate];[0:v]format=gbrp,{_overlay_base_clock(fps)}[bg];[bg][plate]blend=all_mode={mode}:eof_action=pass:repeatlast=0:enable='{enabled}',format=yuv420p[v]"
        target = work/f"overlay-{index:03d}.mkv"
        runner.run(args+["-filter_complex", graph, "-map", "[v]", "-map", "0:a", *_codec(quality), "-t", f"{duration:.9f}", str(target)],
                   duration, f"Compositing overlay {index+1}/{len(project.get('overlays',[]))}")
        base = target
    for index, shape in enumerate(project.get("shapes", [])):
        runner.check_cancelled()
        start = float(shape.get("start", 0))
        end = min(duration, start+float(shape["duration"]))
        if end <= start:
            continue
        stroke_scale = width/float(project.get("canvas", {}).get("width", 1920))
        plate = shapes.render_shape(shape, width, height, work/f"shape-{index:03d}.png", stroke_scale=stroke_scale)
        target = work/f"shape-{index:03d}.mkv"
        enabled = f"gte(t,{start:.9f})*lt(t,{end:.9f})"
        graph = f"[0:v]setpts=PTS-STARTPTS[bg];[bg][1:v]overlay=0:0:enable='{enabled}',format=yuv420p[v]"
        runner.run(["-i", str(base), "-loop", "1", "-framerate", f"{fps:.9f}", "-i", str(plate),
                    "-filter_complex", graph, "-map", "[v]", "-map", "0:a", *_codec(quality),
                    "-t", f"{duration:.9f}", str(target)], duration, f"Drawing shape {index+1}/{len(project.get('shapes', []))}")
        base = target
    for index, track in enumerate(project.get("audio", [])):
        runner.check_cancelled()
        start = float(track.get("start", 0))
        length = min(_track_duration(track), duration-start)
        if length <= 0:
            continue
        asset = _asset(track["asset_id"], resolve_asset, cache)
        source_length = float(track["out"])-float(track.get("in", 0))
        audio_input = asset["path"]
        input_args = ["-ss", f"{float(track.get('in',0)):.9f}", "-t", f"{source_length:.9f}"]
        if track.get("loop"):
            audio_input = str(work/f"audio-loop-{index:03d}.wav")
            runner.run(input_args+["-i", asset["path"], "-vn", "-map", "0:a:0", "-af", "asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo",
                                   "-c:a", "pcm_f32le", "-t", f"{source_length:.9f}", audio_input],
                       source_length, f"Preparing audio loop {index+1}")
            input_args = ["-stream_loop", "-1", "-t", f"{length:.9f}"]
        fade_in, fade_out = min(length, float(track.get("fade_in", 0))), min(length, float(track.get("fade_out", 0)))
        af = f"[1:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={float(track.get('volume',.7)):.9f},apad=whole_dur={length:.9f},atrim=duration={length:.9f}"
        if track.get("volume_keyframes"):
            af += ","+automation.volume_filter(track["volume_keyframes"])
        if fade_in:
            af += f",afade=t=in:d={fade_in:.9f}"
        if fade_out:
            af += f",afade=t=out:st={length-fade_out:.9f}:d={fade_out:.9f}"
        af += f",adelay={round(start*48000)}S:all=1[track];[0:a][track]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,atrim=duration={duration:.9f}[a]"
        target = work/f"audio-mix-{index:03d}.mkv"
        runner.run(["-i", str(base), *input_args, "-i", audio_input, "-filter_complex", af,
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2", "-t", f"{duration:.9f}", str(target)],
                   duration, f"Mixing music / sound effect {index+1}")
        base = target
    title_filters = []
    for index, title in enumerate(project.get("titles", [])):
        if graphics.animated_title(title):
            continue
        start, length = float(title.get("start", 0)), float(title["duration"])
        if start >= duration or not title.get("text"):
            continue
        text_path = work/f"title-{index:03d}.txt"
        text_path.write_text(title["text"], encoding="utf-8")
        size = max(4, round(float(title.get("font_size", 64))*height/float(project.get("canvas", {}).get("height", 1080))))
        draw = f"drawtext=textfile={text_path.name}:expansion=none:fontsize={size}:fontcolor=0x{title.get('color','#ffffff')[1:]}:x='(w-text_w)*{float(title.get('x',.5)):.9f}':y='(h-text_h)*{float(title.get('y',.8)):.9f}'"
        if title.get("font_asset_id"):
            font = _asset(title["font_asset_id"], resolve_asset, cache)
            font_name = _safe_link(font["path"], work/f"font-{index:03d}{Path(font['path']).suffix.lower()}")
            draw += f":fontfile={font_name}"
        if title.get("box", True):
            draw += f":box=1:boxcolor=black@0.55:boxborderw={max(2,round(size*.15))}"
        fade = min(length/2, float(title.get("fade", .15)))
        if fade > 0:
            alpha = f"if(lt(t,{start+fade:.9f}),(t-{start:.9f})/{fade:.9f},if(gt(t,{start+length-fade:.9f}),({start+length:.9f}-t)/{fade:.9f},1))"
            draw += f":alpha='{alpha}'"
        draw += f":enable='gte(t,{start:.9f})*lt(t,{start+length:.9f})'"
        title_filters.append(draw)
    caption_filter, caption_count = _write_captions(project, resolve_asset, cache, work, duration)
    if caption_filter:
        title_filters.append(caption_filter)
    final = work/"export.mp4"
    normalize = "loudnorm=I=-16:TP=-1.5:LRA=11" if project.get("normalize_audio", True) else "alimiter=limit=0.95:level=false:latency=1"
    args = ["-i", str(base), "-map", "0:v:0", "-map", "0:a:0"]
    if title_filters:
        args += ["-vf", ",".join(title_filters)]
    # A finite integer sample format also sanitizes loudnorm's NaN output for
    # completely silent, very short clips on some FFmpeg builds.
    args += ["-af", normalize+f",aresample=48000:osf=s16,apad=whole_dur={duration:.9f},atrim=duration={duration:.9f}",
             "-c:v", "libx264", "-preset", "veryfast" if quality == "preview" else "medium", "-crf", str(plan["final_crf"]),
             "-threads", str(THREADS), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", "-t", f"{duration:.9f}", str(final)]
    runner.run(args, duration, "Encoding the finished MP4")
    runner.check_cancelled()
    metadata = probe(str(final))
    if not metadata["has_video"] or not metadata["has_audio"] or abs(metadata["duration"]-duration) > max(.15, 2/fps):
        raise RenderError(f"Export verification failed: expected {duration:.3f}s, received {metadata['duration']:.3f}s")
    # An exclusive hard link publishes without duplicating a large export. If the
    # user's render folder is another filesystem, copy with cancellation checks.
    if output != final:
        try:
            os.link(final, output)
        except OSError as exc:
            if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP):
                raise
            created = False
            try:
                with output.open("xb") as destination, final.open("rb") as source:
                    created = True
                    while True:
                        runner.check_cancelled()
                        block = source.read(1024*1024)
                        if not block:
                            break
                        destination.write(block)
            except BaseException:
                if created:
                    output.unlink(missing_ok=True)
                raise
    runner.progress(1., "Render complete")
    return {"path": str(output), **metadata, "width": width, "height": height, "fps": fps,
            "quality": plan["quality"], "export_profile": plan["export_profile"], "timeline_duration": duration, "warnings": plan["warnings"],
            "captions_burned": caption_count,
            "work_dir": str(work), "audio_normalization": plan["audio_normalization"]}
