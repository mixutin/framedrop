"""Native, antialiased callout graphics written as dependency-free RGBA PNGs.

Coordinates are normalized to the canvas: x/y and x2/y2 are an arrow's tail
and tip, or opposite corners of an outlined rectangle/ellipse. Stroke width
is measured in canvas pixels. Shapes have a half-open timeline interval
[start, start + duration); rendering generates the image, not its timing.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import struct
import zlib

KINDS = frozenset(("arrow", "ellipse", "rectangle"))
DEFAULT_COLOR = "#ff3030"
DEFAULT_STROKE_WIDTH = 12
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


def _number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Shape {name} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"Shape {name} must be between {low} and {high}")
    return float(value)


def validate_shape(shape, timeline_duration):
    """Reject invalid geometry, colors and timing without interpreting expressions."""
    if not isinstance(shape, dict):
        raise ValueError("Each shape must be an object")
    if not isinstance(shape.get("kind"), str) or shape["kind"] not in KINDS:
        raise ValueError("Shape kind must be arrow, ellipse or rectangle")
    if "id" in shape and (not isinstance(shape["id"], str) or not 1 <= len(shape["id"]) <= 128):
        raise ValueError("Shape id must be a nonempty string of at most 128 characters")
    start = _number(shape.get("start", 0), 0, timeline_duration, "start")
    duration = _number(shape.get("duration"), 0, timeline_duration, "duration")
    if duration <= 0 or start + duration > timeline_duration + 1e-7:
        raise ValueError("Shape duration must be positive and end within the timeline")
    x, y, x2, y2 = (_number(shape.get(key), 0, 1, key) for key in ("x", "y", "x2", "y2"))
    if shape["kind"] == "arrow":
        if math.hypot(x2-x, y2-y) < 1e-8:
            raise ValueError("An arrow must have distinct tail and tip coordinates")
    elif abs(x2-x) < 1e-8 or abs(y2-y) < 1e-8:
        raise ValueError("An ellipse or rectangle must have nonzero width and height")
    color = shape.get("color", DEFAULT_COLOR)
    if not isinstance(color, str) or not _COLOR.fullmatch(color):
        raise ValueError("Shape color must be a #RRGGBB hex color")
    _number(shape.get("stroke_width", DEFAULT_STROKE_WIDTH), 1, 256, "stroke_width")
    _number(shape.get("opacity", 1), 0, 1, "opacity")


def _segment_distance(x, y, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    length2 = dx*dx + dy*dy
    t = max(0., min(1., ((x-ax)*dx+(y-ay)*dy)/length2)) if length2 else 0.
    return math.hypot(x-ax-t*dx, y-ay-t*dy)


def _triangle_distance(x, y, vertices):
    """Signed distance to a filled triangle (negative inside)."""
    sign, inside, distance = None, True, float("inf")
    for index in range(3):
        ax, ay = vertices[index]
        bx, by = vertices[(index+1) % 3]
        cross = (bx-ax)*(y-ay)-(by-ay)*(x-ax)
        positive = cross >= 0
        if sign is None:
            sign = positive
        elif sign != positive:
            inside = False
        distance = min(distance, _segment_distance(x, y, ax, ay, bx, by))
    return -distance if inside else distance


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)


def render_shape(shape, width, height, path, *, stroke_scale=1):
    """Write a full-canvas straight-alpha PNG and return its pathlib.Path.

    Analytic signed-distance coverage gives smooth one-pixel edges without
    importing image libraries or evaluating user-supplied drawing expressions.
    """
    if (isinstance(width, bool) or isinstance(height, bool) or
            not isinstance(width, int) or not isinstance(height, int) or
            not 1 <= width <= 8192 or not 1 <= height <= 8192):
        raise ValueError("Shape canvas dimensions must be integers between 1 and 8192")
    # Timing is validated by the engine against the actual timeline. Validate
    # geometry here too so direct callers cannot bypass the allowlist.
    if not isinstance(shape, dict):
        raise ValueError("Each shape must be an object")
    start, duration = shape.get("start", 0), shape.get("duration", 1)
    if not isinstance(start, (int, float)) or not isinstance(duration, (int, float)):
        raise ValueError("Shape start and duration must be numbers")
    validate_shape({**shape, "duration": duration}, max(0, start+duration))
    x, y, x2, y2 = (shape[key]*size for key, size in (("x", width), ("y", height), ("x2", width), ("y2", height)))
    _number(stroke_scale, .001, 128, "stroke_scale")
    stroke = float(shape.get("stroke_width", DEFAULT_STROKE_WIDTH))*stroke_scale
    half = stroke/2
    opacity = float(shape.get("opacity", 1))
    color = shape.get("color", DEFAULT_COLOR)
    rgb = bytes(int(color[index:index+2], 16) for index in (1, 3, 5))
    kind = shape["kind"]
    left, right = min(x, x2), max(x, x2)
    top, bottom = min(y, y2), max(y, y2)
    if kind == "arrow":
        length = math.hypot(x2-x, y2-y)
        ux, uy = (x2-x)/length, (y2-y)/length
        head_length = min(length*.6, max(stroke*3, min(width, height)*.018))
        head_half = head_length*.58
        base_x, base_y = x2-ux*head_length, y2-uy*head_length
        vertices = ((x2, y2), (base_x-uy*head_half, base_y+ux*head_half),
                    (base_x+uy*head_half, base_y-ux*head_half))
        left = min(left, *(v[0] for v in vertices))-half-1
        right = max(right, *(v[0] for v in vertices))+half+1
        top = min(top, *(v[1] for v in vertices))-half-1
        bottom = max(bottom, *(v[1] for v in vertices))+half+1

        def distance(px, py):
            return min(_segment_distance(px, py, x, y, base_x, base_y)-half,
                       _triangle_distance(px, py, vertices))
    else:
        cx, cy = (left+right)/2, (top+bottom)/2
        rx, ry = (right-left)/2, (bottom-top)/2
        left, right, top, bottom = left-half-1, right+half+1, top-half-1, bottom+half+1
        if kind == "rectangle":
            def distance(px, py):
                qx, qy = abs(px-cx)-rx, abs(py-cy)-ry
                signed = math.hypot(max(qx, 0), max(qy, 0))+min(max(qx, qy), 0)
                return abs(signed)-half
        else:
            def distance(px, py):
                dx, dy = abs(px-cx), abs(py-cy)
                q = math.hypot(dx/rx, dy/ry)
                if q < 1e-12:
                    return min(rx, ry)-half
                # First-order implicit ellipse distance has uniform pixel-scale
                # coverage at the contour, even for wide or tall ellipses.
                gradient = math.hypot(dx/(rx*rx), dy/(ry*ry))/q
                return abs(q-1)/gradient-half
    pixels = bytearray(width*height*4)
    if opacity > 0:
        for py in range(max(0, math.floor(top)), min(height, math.ceil(bottom))):
            for px in range(max(0, math.floor(left)), min(width, math.ceil(right))):
                coverage = max(0., min(1., .5-distance(px+.5, py+.5)))
                alpha = round(255*opacity*coverage)
                if alpha:
                    offset = (py*width+px)*4
                    pixels[offset:offset+3] = rgb
                    pixels[offset+3] = alpha
    compressor = zlib.compressobj(6)
    encoded = bytearray()
    stride = width*4
    for row in range(height):
        encoded.extend(compressor.compress(b"\0"+pixels[row*stride:(row+1)*stride]))
    encoded.extend(compressor.flush())
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
                       _chunk(b"IDAT", bytes(encoded)) + _chunk(b"IEND", b""))
    return output
