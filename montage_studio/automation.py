"""Bounded numeric animation; no caller-supplied expressions reach FFmpeg."""
from __future__ import annotations

import math

MAX_KEYFRAMES = 64


def _number(value, lo, hi, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if not lo <= value <= hi:
        raise ValueError(f"{label} must be between {lo:g} and {hi:g}")
    return float(value)


def validate_keyframes(keyframes, duration, fields, label):
    """Validate local output-time keyframes; values before/after hold endpoints."""
    if not isinstance(keyframes, list) or len(keyframes) > MAX_KEYFRAMES:
        raise ValueError(f"{label} must be a list with at most {MAX_KEYFRAMES} keyframes")
    previous = -1.
    for keyframe in keyframes:
        if not isinstance(keyframe, dict):
            raise ValueError(f"{label} keyframes must be objects")
        when = _number(keyframe.get("time"), 0, duration, f"{label}.time")
        if when <= previous:
            raise ValueError(f"{label} keyframe times must be strictly increasing")
        previous = when
        for field, bounds in fields.items():
            _number(keyframe.get(field), *bounds, f"{label}.{field}")


def validate_motion(keyframes, duration):
    validate_keyframes(keyframes, duration, {"zoom": (1, 4), "x": (0, 1), "y": (0, 1)}, "motion")


def validate_volume(keyframes, duration):
    validate_keyframes(keyframes, duration, {"volume": (0, 4)}, "volume_keyframes")


def _literal(number):
    return format(float(number), ".17g")


def expression(keyframes, field, clock):
    """Piecewise-linear ramps, with constant extrapolation at both endpoints.

    Sum of bounded ramps avoids deeply nested conditional expressions. Clock and
    field are internal constants; all interpolated data passed validation first.
    """
    value = _literal(keyframes[0][field])
    for left, right in zip(keyframes, keyframes[1:]):
        delta = float(right[field])-float(left[field])
        if delta:
            value += (f"+({_literal(delta)})*clip((({clock})-({_literal(left['time'])}))/"
                      f"({_literal(float(right['time'])-float(left['time']))}),0,1)")
    return value


def motion_filter(keyframes, width, height, fps):
    """One output per input frame; the clock spans the complete retimed clip."""
    clock = f"on/{_literal(fps)}"
    zoom = expression(keyframes, "zoom", clock)
    x, y = (expression(keyframes, field, clock) for field in ("x", "y"))
    return (f"zoompan=z='clip({zoom},1,4)':x='(iw-iw/zoom)*clip({x},0,1)':"
            f"y='(ih-ih/zoom)*clip({y},0,1)':d=1:s={width}x{height}:fps={_literal(fps)}")


def volume_filter(keyframes):
    """Sample-accurate stereo gain, applied after base volume and retiming."""
    gain = f"clip({expression(keyframes, 'volume', 't')},0,4)"
    return f"aeval=exprs='val(0)*({gain})|val(1)*({gain})':channel_layout=stereo"
