"""Native, bounded motion graphics rendered with libass in the export pass.

Only our generated override tags and vector paths enter ASS. Text is escaped by
the engine, and all caller-supplied numbers/colors are validated before rendering.
"""
from __future__ import annotations

import math
import re

ANIMATIONS = ("none", "fade", "pop", "slide_up")
ACCENTS = ("impact_ring", "spark_burst", "light_sweep")


def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a finite number from {low} to {high}")
    return float(value)


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Graphics colors must be #RRGGBB")
    return "&H" + value[5:7] + value[3:5] + value[1:3] + "&"


def validate_text_motion(item):
    if item.get("animation", "none") not in ANIMATIONS:
        raise ValueError("Unknown text animation")
    number(item.get("animation_duration", .16), .01, 2, "animation_duration")
    number(item.get("glow", 0), 0, 1, "glow")
    color(item.get("glow_color", "#ff62c6"))


def animated_title(item):
    return item.get("animation", "none") != "none" or item.get("glow", 0) > 0


def validate_accent(item):
    if not isinstance(item, dict) or item.get("kind") not in ACCENTS:
        raise ValueError("Accent kind must be impact_ring, spark_burst, or light_sweep")
    for key, default, low, high in (("start", 0, 0, 14400), ("duration", .4, .02, 10),
                                  ("size", .25, .02, 2), ("x", .5, 0, 1), ("y", .5, 0, 1),
                                  ("opacity", .8, 0, 1), ("rotation", 0, -180, 180)):
        number(item.get(key, default), low, high, key)
    color(item.get("color", "#ff62c6"))


def text_layers(item, length, x, y, literal, *, alignment=5):
    """Return (relative layer, escaped ASS text) pairs for one timed cue."""
    ms = max(1, round(length*1000))
    enter = min(round(float(item.get("animation_duration", .16))*1000), ms//2)
    leave = min(enter, 120)
    animation = item.get("animation", "none")
    tags = f"\\an{alignment}\\pos({x:.3f},{y:.3f})"
    if animation != "none":
        tags += f"\\fad({min(60,enter)},{leave})"
    if animation == "pop":
        split = max(1, round(enter*.65))
        tags += (f"\\fscx82\\fscy82\\t(0,{split},0.6,\\fscx108\\fscy108)"
                 f"\\t({split},{enter},1.5,\\fscx100\\fscy100)")
    elif animation == "slide_up":
        shift = float(item.get("font_size", 52))*.45
        tags = tags.replace(f"\\pos({x:.3f},{y:.3f})",
                            f"\\move({x:.3f},{y+shift:.3f},{x:.3f},{y:.3f},0,{enter})")
    elif animation == "fade":
        tags = tags.replace(f"\\fad({min(60,enter)},{leave})", f"\\fad({enter},{leave})")
    glow = float(item.get("glow", .7 if item.get("preset") == "neon" else 0))
    layers = []
    if glow:
        tint = color(item.get("glow_color", "#ff62c6"))
        for layer, border, blur, alpha in ((0, 8*glow, 12*glow, "80"), (1, 3*glow, 4*glow, "40")):
            layers.append((layer, "{"+tags+f"\\1c{tint}\\3c{tint}\\1a&H{alpha}&\\3a&H{alpha}&\\bord{border:.3f}\\blur{blur:.3f}\\shad0"+"}"+literal))
    layers.append((2, "{"+tags+"}"+literal))
    return layers


def text_events(item, length, x, y, literal, *, alignment=5):
    """Return local start/end, layer, payload for the engine's timed events."""
    layers = text_layers(item, length, x, y, literal, alignment=alignment)
    return [(0, length, layer, text) for layer, text in layers]


def _polygon(points, offset=0):
    return "m " + " l ".join(f"{x+offset:.3f} {y+offset:.3f}" for x,y in points) + " "


def accent_layers(item, width, height, length):
    kind = item["kind"]
    size = float(item.get("size", .25))*width
    x, y = float(item.get("x", .5))*width, float(item.get("y", .5))*height
    ms = max(1, round(length*1000))
    alpha = round(255*(1-float(item.get("opacity", .8))))
    tint = color(item.get("color", "#ff62c6"))
    rotation = float(item.get("rotation", 0))
    base = f"\\an5\\p1\\bord0\\shad0\\1c{tint}\\1a&H{alpha:02X}&\\frz{rotation:.3f}"
    if kind == "light_sweep":
        # Overscan vertically so no letterboxed/corner border is introduced.
        path = _polygon([(0,0),(size*.25,0),(-height*.35+size*.25,height*1.6),(-height*.35,height*1.6)])
        tags = base+f"\\move({-size:.3f},{y:.3f},{width+size:.3f},{y:.3f})\\blur12\\fad({ms//5},{ms//3})"
    else:
        radius = size/2
        if kind == "impact_ring":
            path = ""
            for sector in range(4):
                a = sector*math.pi/2+.12
                angles = [a+i*(math.pi/2-.24)/20 for i in range(21)]
                # ASS positions the drawing's positive-coordinate box; negative
                # vertices shift its apparent center as animated scale changes.
                path += _polygon([(radius*math.cos(t),radius*math.sin(t)) for t in angles]+[(radius*.96*math.cos(t),radius*.96*math.sin(t)) for t in reversed(angles)], radius)
        else:
            path = ""
            for i in range(12):
                angle = i*math.pi/6
                def point(r, side):
                    return (r*math.cos(angle)-side*math.sin(angle),r*math.sin(angle)+side*math.cos(angle))
                path += _polygon([point(radius*.5,0),point(radius*.75,radius*.025),point(radius,0),point(radius*.75,-radius*.025)], radius)
        tags = base+f"\\pos({x:.3f},{y:.3f})\\blur1\\fscx25\\fscy25\\t(0,{ms},0.55,\\fscx115\\fscy115)\\fad({min(20,ms//4)},{ms*3//4})"
    return [(0,"{"+tags+"\\blur9}"+path),(1,"{"+tags+"}"+path)]
