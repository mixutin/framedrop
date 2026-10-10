# Framedrop 0.2.0 verification

The generated-media regression checks exercise actual FFmpeg output, not only filter strings. Run them from the repository directory with FFmpeg and FFprobe available:

```bash
python3 -m unittest discover -s tests -p 'test_advanced_engine.py' -v
python3 -m unittest discover -s tests -p 'test_engine.py' -v
python3 -m unittest discover -s tests -p 'test_advanced_effects.py' -v
```

Verified feature suites:

| Suite | Passed | Coverage |
|---|---:|---|
| Advanced engine | 8 | Native freeze matches the source frame and remains silent, near-EOF capture, motion across retimed segments, transition integration, sample-accurate clip/loop envelopes, endpoint behavior, malformed input, maximum 64-keyframe expressions |
| Existing engine | 13 | All native effect and transition recipes, heterogeneous clips, speed segments, overlays, transforms, LUTs, titles, captions, silence, cancellation and source-output protection |
| Advanced effects and shapes | 13 | Timed effects preserve exact inactive pixels, exclusive end boundaries and duration, frame rounding, flash window anchoring, echo trails, arrow direction, ellipse/rectangle geometry, alpha, antialiasing, preview stroke scaling and PNG decoding |

The complete release suite passes 126 tests, covering persistence, revision conflicts, asset/archive handling, caption exchange, MCP protocol, service behavior, optional-model job handling, and legacy-install migration:

```bash
python3 -m unittest discover -s tests -q
node --check montage_studio/static/app.js
```

## Review a real edit

Use the [quickstart](QUICKSTART.md) with media you have permission to edit. Check the exact death boundary: the frame holds, original clip audio stops, and the alarm starts on that same timeline boundary. Confirm the darkened picture, skull transparency, callout placement and editable caption timing in the rendered preview. Export once at final resolution and play the resulting MP4.

Background removal and Whisper transcription are optional downloaded-model integrations. The core generated-fixture suites do not establish recognition quality or cutout quality for arbitrary media. Inspect `background_removal_status` and `transcription_status`, run their documented job workflows, and review their completed output before applying it. Larger cached Whisper models are selectable; no accuracy guarantee follows from their size.

## Current limits

- One sequential footage track, with separate media overlay, shape, title, caption and audio layers. Preview rendering shows the full composition; source playback shows original media.
- SDR software H.264/AAC exports. Speed segments are piecewise constant with pitch-preserving audio, without optical-flow interpolation.
- Freeze source selection snaps to nominal frame boundaries; variable-frame-rate capture is approximate. Held footage is silent, while dedicated audio tracks remain audible.
- Motion/gain keyframes interpolate linearly. Shapes are static callouts; there is no automatic subject tracking or node-based compositor.
- External After Effects/Fusion presets remain searchable references and require their original hosts/plugins. Supported media, fonts and LUTs can be imported; host-specific presets are not executed.

Rendering and cached-model inference run locally. A connected AI client can receive requested metadata, preview images and caption text through MCP. Personal projects, media, model caches and workstation-specific verification artifacts are not part of the source distribution.
