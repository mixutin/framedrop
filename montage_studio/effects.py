"""Allowlisted, original FFmpeg recipes; external host presets are never executed."""
from __future__ import annotations

import math

TRANSITIONS = ("cut", "fade", "dissolve", "wipeleft", "wiperight", "slideleft",
               "slideright", "circleopen", "pixelize", "fadeblack", "fadewhite")

_RECIPES = (
    ("punchy", "Punchy", "color", "Stronger contrast, color and fine detail.", .7),
    ("cinematic", "Cinematic", "color", "Gentle contrast with cool shadows and warm highlights.", .6),
    ("warm", "Warm", "color", "Warmer red highlights and reduced blue.", .6),
    ("cool", "Cool", "color", "Cooler blue highlights and reduced red.", .6),
    ("monochrome", "Monochrome", "color", "Reduce saturation toward black and white.", 1.),
    ("sepia", "Sepia", "color", "Blend an original sepia color matrix.", .8),
    ("teal_orange", "Teal / orange", "color", "Teal shadows with warmer highlights.", .6),
    ("exposure", "Exposure", "color", "Adjust brightness; strength 0.5 is neutral.", .65),
    ("contrast", "Contrast", "color", "Adjust contrast from soft to strong.", .5),
    ("saturation", "Saturation", "color", "Adjust color intensity.", .5),
    ("sharpen", "Sharpen", "detail", "Unsharp-mask detail enhancement.", .5),
    ("blur", "Gaussian blur", "detail", "Soft Gaussian blur.", .4),
    ("glow", "Soft glow", "light", "Screen-blend a blurred copy of the frame.", .45),
    ("grain", "Film grain", "texture", "Animated fine-grain noise.", .3),
    ("vignette", "Vignette", "light", "Darken frame edges around the subject.", .6),
    ("zoom", "Crop zoom", "motion", "A fixed center crop with up to 25 percent magnification.", .4),
    ("shake", "Camera shake", "motion", "Bounded oscillating crop; enlarged edges prevent empty borders.", .5),
    ("impact", "Impact", "motion", "An opening flash and decaying shake with a small crop.", .6),
    ("rgb_split", "RGB split", "distortion", "Offset the red and blue channels horizontally.", .5),
    ("fade_in", "Fade in", "light", "Fade the beginning of a clip up from black.", .6),
    ("fade_out", "Fade out", "light", "Fade the end of a clip down to black.", .6),
    ("flash", "Opening flash", "light", "A brief bright flash decaying from the first frame.", .6),
    ("pixelate", "Pixelate", "distortion", "Enlarge pixels into crisp mosaic blocks.", .5),
    ("edge_glow", "Neon edges", "light", "Screen-blend glowing, color-enhanced contours.", .65),
    ("posterize", "Posterize", "color", "Reduce each color channel to bold stepped tones.", .65),
    ("echo_trails", "Echo trails", "motion", "Blend recent frames into weighted motion trails without changing timing.", .5),
    ("scanlines", "Scanlines", "texture", "Dark horizontal lines for a CRT-inspired texture.", .5),
    ("invert", "Invert colors", "color", "Blend toward a photographic color negative.", 1.),
)
NAMES = frozenset(row[0] for row in _RECIPES)
DEFAULTS = {row[0]: row[4] for row in _RECIPES}


def list_effects():
    return [{"name": name, "label": label, "category": category,
             "description": description, "strength": {"min": 0, "max": 1, "default": default},
             "timing": {"start": "Optional clip-output-local seconds, default 0",
                        "end": "Optional exclusive end in clip-output-local seconds, default clip duration"},
             "compatibility": "native", "implementation": "Original FFmpeg recipe",
             "source_note": "Native equivalent; does not import or execute After Effects / Resolve presets."}
            for name, label, category, description, default in _RECIPES]


def strength(effect):
    if not isinstance(effect, dict):
        raise ValueError("Each effect must be an object")
    name = effect.get("name")
    if not isinstance(name, str) or name not in NAMES:
        raise ValueError(f"Unknown native effect: {name!r}")
    value = effect.get("strength", DEFAULTS[name])
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"Effect {name}: strength must be a finite number from 0 to 1")
    return float(value)


def _window(effect, duration):
    values = []
    for key, default in (("start", 0), ("end", duration)):
        value = effect.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Effect {key} must be a finite number")
        values.append(float(value))
    start, end = values
    if not 0 <= start < end <= duration + 1e-7:
        raise ValueError("Effect window must satisfy 0 <= start < end <= clip output duration")
    return start, min(end, duration)


def validate_effect(effect, duration):
    """Validate a native recipe and its half-open, output-local time window."""
    strength(effect)
    _window(effect, duration)


def build_graph(source, recipes, width, height, duration, fps, prefix="fx", *, logical_duration=None):
    """Build allowlisted recipes, optionally enabled in output-local [start, end).

    A framesynchronized blend gates entire recipes, including multi-filter graphs
    and filters without native timeline support. Both branches retain every frame
    and timestamp, so effects never change clip duration or audio synchronization.
    The engine supplies logical_duration for strict project validation before
    clipping windows to the actual frame-rounded intermediate duration.
    """
    clauses, current = [], source
    for index, recipe in enumerate(recipes):
        s = strength(recipe)
        name = recipe["name"]
        start, end = _window(recipe, duration if logical_duration is None else logical_duration)
        end = min(end, duration) if "end" in recipe else duration
        if start >= end:
            # A sub-frame window at the clip end may contain no rendered frames.
            continue
        out = f"{prefix}{index}"
        windowed = start > 0 or end < duration
        if windowed:
            clauses.append(f"[{current}]split[{out}base][{out}input]")
            current = f"{out}input"
        target = f"{out}effect" if windowed else out
        if name in ("glow", "edge_glow"):
            sigma = .3 + 7 * s
            filters = f"gblur=sigma={sigma:.5f}"
            if name == "edge_glow":
                filters = f"edgedetect=low=.04:high=.18:mode=colormix,gblur=sigma={.3+1.3*s:.5f},eq=saturation=1.8:contrast=1.4"
            clauses.extend((f"[{current}]split[{out}s][{out}b]",
                            f"[{out}b]{filters}[{out}g]",
                            f"[{out}s][{out}g]blend=all_mode=screen:all_opacity={(.45 if name=='glow' else .9)*s:.5f}[{target}]"))
            filt = None
        elif name == "punchy":
            filt = f"eq=contrast={1+.28*s}:saturation={1+.35*s},unsharp=5:5:{.6*s}"
        elif name == "cinematic":
            filt = f"eq=contrast={1+.14*s}:saturation={1-.15*s},colorbalance=bs={.06*s}:rh={.05*s}"
        elif name in ("warm", "cool"):
            red, blue = ((.12*s, -.08*s) if name == "warm" else (-.08*s, .12*s))
            filt = f"colorbalance=rm={red}:bm={blue}"
        elif name == "monochrome":
            filt = f"hue=s={1-s}"
        elif name == "sepia":
            matrix = (.393, .769, .189, .349, .686, .168, .272, .534, .131)
            keys = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
            filt = "colorchannelmixer=" + ":".join(f"{k}={s*v+(1-s if i in (0,4,8) else 0):.6f}" for i, (k, v) in enumerate(zip(keys, matrix)))
        elif name == "teal_orange":
            filt = f"colorbalance=rs={-.06*s}:gs={.04*s}:bs={.10*s}:rh={.09*s}:bh={-.06*s}"
        elif name == "exposure":
            filt = f"eq=brightness={(s-.5)*.4}"
        elif name == "contrast":
            filt = f"eq=contrast={.7+1.3*s}"
        elif name == "saturation":
            filt = f"eq=saturation={.4+2*s}"
        elif name == "sharpen":
            filt = f"unsharp=5:5:{2*s}"
        elif name == "blur":
            filt = f"gblur=sigma={.1+8*s}"
        elif name == "grain":
            filt = f"noise=alls={round(24*s)}:allf=t+u:all_seed=17"
        elif name == "vignette":
            filt = f"vignette=angle={s*math.pi/2.5}:eval=init"
        elif name in ("zoom", "shake", "impact"):
            factor = 1 + (.25*s if name == "zoom" else .06*s)
            sw, sh = math.ceil(width*factor/2)*2, math.ceil(height*factor/2)*2
            x, y = "(iw-ow)/2", "(ih-oh)/2"
            if name != "zoom":
                decay = f"*exp(-max(0,n-{start*fps:.7f})/{max(1,fps*.12):.5f})" if name == "impact" else ""
                x += f"+{(sw-width)*.45:.5f}*sin(n*1.7){decay}"
                y += f"+{(sh-height)*.45:.5f}*cos(n*1.3){decay}"
            filt = f"scale={sw}:{sh},crop={width}:{height}:x='{x}':y='{y}'"
            if name == "impact":
                filt += f",eq=brightness='{.18*s}*exp(-max(0,t-{start:.7f})*14)':eval=frame"
        elif name == "rgb_split":
            px = max(0, round(width/1920*18*s))
            filt = f"format=gbrp,rgbashift=rh={px}:bh={-px}:edge=smear"
        elif name in ("fade_in", "fade_out"):
            d = max(1/fps, min((end-start)/2, .1+.9*s))
            filt = f"fade=t={'in' if name=='fade_in' else 'out'}:st={start if name=='fade_in' else max(start,end-d):.7f}:d={d:.7f}"
        elif name == "flash":
            filt = f"eq=brightness='{.3*s}*exp(-max(0,t-{start:.7f})*12)':eval=frame"
        elif name == "pixelate":
            block = 1 + round(31*s)
            small_w, small_h = max(2, round(width/block/2)*2), max(2, round(height/block/2)*2)
            filt = f"scale={small_w}:{small_h}:flags=area,scale={width}:{height}:flags=neighbor"
        elif name == "posterize":
            levels = max(2, round(32-28*s))
            expr = f"round(val*{levels-1}/255)*255/{levels-1}"
            filt = f"format=gbrp,lutrgb=r='{expr}':g='{expr}':b='{expr}'"
        elif name == "echo_trails":
            count = 1 + round(6*s)
            # tmix orders weights oldest to newest; preserve a strong live frame.
            weights = " ".join(f"{.7**i:.7f}" for i in reversed(range(count)))
            filt = f"tmix=frames={count}:weights='{weights}'"
        elif name == "scanlines":
            filt = f"geq=lum='lum(X,Y)*(1-{.65*s:.7f}*eq(mod(Y,4),0))':cb='cb(X,Y)':cr='cr(X,Y)'"
        elif name == "invert":
            expr = f"val*{1-s:.7f}+(255-val)*{s:.7f}"
            filt = f"format=gbrp,lutrgb=r='{expr}':g='{expr}':b='{expr}'"
        else:
            raise ValueError(f"Unknown effect {name}")
        if filt is not None:
            clauses.append(f"[{current}]{filt}[{target}]")
        if windowed:
            # Normal mode at zero top opacity selects the effect (bottom input).
            # Disabled blend forwards the original top input. Timeline enable is
            # evaluated once per frame, avoiding a conditional for every pixel.
            clauses.append(f"[{out}base][{target}]blend=all_mode=normal:all_opacity=0:enable='gte(t,{start:.17g})*lt(t,{end:.17g})'[{out}]")
        current = out
    return clauses, current
