# Framedrop 0.2.0 timeline and automation reference

All three interfaces edit the same schema-version-1 project. Seconds are decimal numbers. Asset IDs come from the catalog; do not put source paths or FFmpeg filter text in the timeline. A project retains its ID when edited. `revision` changes on every saved edit, and `expected_revision` is required by save/edit/restore tools.

For working CLI recipes and the installed MCP connection, see [QUICKSTART.md](QUICKSTART.md). `framedrop tools` prints the current input schemas; `framedrop call TOOL_NAME --json '{...}'` passes those arguments directly to the same service used by MCP.

## Minimal project

Use `project_create` to get the IDs, timestamps and revision, then modify the returned document:

```json
{
  "schema_version": 1,
  "id": "p_RETURNED_ID",
  "name": "Example montage",
  "revision": 0,
  "created_at": "2026-10-10T00:00:00.000+00:00",
  "updated_at": "2026-10-10T00:00:00.000+00:00",
  "canvas": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "fit": "cover",
    "background": "#101014"
  },
  "clips": [],
  "audio": [],
  "overlays": [],
  "shapes": [],
  "titles": [],
  "captions": [],
  "markers": [],
  "normalize_audio": true
}
```

An empty project can be saved. Rendering requires at least one footage clip. The timeline duration comes from the clips and their outgoing transition overlaps. Audio, overlays, titles and captions never extend that duration; content outside it is skipped or trimmed. Shapes must end within the timeline. Missing `shapes`, `captions` and `caption_style` fields receive defaults on save; older projects remain compatible.

## Footage clip

```json
{
  "id": "c_UNIQUE_ID",
  "asset_id": "VIDEO_OR_IMAGE_ASSET_ID",
  "in": 2,
  "out": 6,
  "speed": 1,
  "volume": 0,
  "fit": "cover",
  "effects": [
    {"name": "punchy", "strength": 0.55},
    {"name": "impact", "strength": 0.4}
  ],
  "transition": {"name": "fade", "duration": 0.25},
  "segments": []
}
```

`in` and `out` are absolute times in the source. `out` is exclusive. Without speed segments, output duration is `(out - in) / speed`. `speed` ranges from 0.125 to 8. `fit: "cover"` fills the canvas by cropping; `contain` preserves the whole picture with padding. `volume: 0` mutes source audio. The engine supplies silence when a clip has no audio stream.

The transition applies from this clip **into the next clip**. The last clip's transition is ignored. Supported names are `cut`, `fade`, `dissolve`, `wipeleft`, `wiperight`, `slideleft`, `slideright`, `circleopen`, `pixelize`, `fadeblack` and `fadewhite`. Transition duration is 0–2 seconds. Non-cut durations must fit in the neighboring clip durations; a clip's incoming and outgoing overlaps together cannot exceed its duration. Cuts have zero overlap. Video transitions also crossfade the neighboring source audio.

`effects_list` returns the current native recipes, descriptions and strength defaults. A clip can contain up to 12 effect entries, applied in their listed order. Effects generally use strengths from 0 to 1; inspect the effect description because a midpoint may be neutral for a control such as exposure. Set `lut_asset_id` to a catalogued LUT ID to apply it after the native effect stack. Version 0.2 adds `pixelate`, `edge_glow`, `posterize`, `echo_trails`, `scanlines` and `invert`.

Every recipe accepts optional `start` and `end` in **clip output seconds**. The active interval is `[start, end)`, defaulting to the whole clip; require `0 <= start < end <= clip_duration`. For example, `{"name":"flash","strength":0.6,"start":0.5,"end":0.8}` flashes half a second into the rendered clip. Flash, impact and fade timing anchors to this window. Effect windows are evaluated after retiming and before transitions.

Professional clip controls are independent of creative effect recipes:

```json
{
  "transform": {"x": 0.5, "y": 0.5, "zoom": 1, "rotation": 0, "flip_x": false, "flip_y": false},
  "color": {"brightness": 0, "contrast": 1, "saturation": 1, "gamma": 1},
  "fade_in": 0.15,
  "fade_out": 0.25
}
```

Crop anchors range from 0 to 1; zoom from 1 to 4. With `fit: "contain"`, anchors position the padded picture; zoom then crops the fitted canvas. Rotation supports −180, −90, 0, 90 and 180 degrees, with positive values clockwise. Flips and rotation happen before fitting the clip to the canvas. Color ranges are brightness −0.5 to 0.5, contrast 0.25 to 3, saturation 0 to 3, gamma 0.25 to 3. Color adjustments precede creative effects and LUTs. Video fades occur after that processing and are measured in output seconds, bounded by clip duration. Clip `fade_in` / `fade_out` affect video; audio-track fades are configured separately.

## Native freeze frame

```json
{
  "asset_id": "VIDEO_ASSET_ID", "in": 5, "out": 6,
  "freeze": {"time": 5, "duration": 2},
  "color": {"brightness": -0.23}
}
```

`freeze.time` is an absolute source timestamp; it must be nonnegative and before the end of video media. `freeze.duration` is the output hold length, 0.001–14400 seconds. The renderer captures and holds a source frame directly; no extracted image asset is needed. Selection snaps down to the nominal source frame boundary, so variable-frame-rate footage is approximate. `in/out` remain valid source metadata but do not determine the hold length. A freeze ignores `speed` and cannot contain speed `segments`.

**A freeze always has silent original clip audio.** Separate sound-effect tracks still play. Append a frozen clip after a normal clip, use a cut, and start an alarm track at that exact boundary. A transition overlaps the clips and therefore moves the freeze's timeline start earlier. Motion, color and effects can still animate the held picture.

## Motion and audio automation

```json
{
  "motion": [
    {"time": 0, "zoom": 1, "x": 0.5, "y": 0.5},
    {"time": 2, "zoom": 1.8, "x": 0.65, "y": 0.6}
  ],
  "volume_keyframes": [
    {"time": 0, "volume": 1},
    {"time": 1.5, "volume": 1},
    {"time": 2, "volume": 0}
  ]
}
```

Each list accepts at most 64 keyframes with finite, strictly increasing `time` values between zero and the rendered clip duration. All shown fields are required. Values interpolate linearly; the first and last values hold outside their keyframe range. An empty list disables that automation. Motion uses zoom 1–4 and x/y 0–1. The x/y values place the crop within the zoomed picture; they have no visible effect at zoom 1.

Motion applies after fitting and static transforms, once across the joined speed segments. Creative effects, LUTs, fades and transitions follow. Thus an animation does not restart at speed changes. Static zoom and animated zoom compound.

`volume_keyframes` also works on audio tracks, using seconds since the track starts, including across loops. Gain ranges from 0 to 4 and multiplies the base `volume`. Clip envelopes apply after retiming and before transition audio crossfades; track envelopes apply before track fades and placement. Audio interpolation is sample-accurate. Loudness normalization can change the overall gain; disable it when judging a specific gain envelope, leaving the peak limiter active.

## Piecewise velocity ramp

`segments` replaces a clip's single speed with contiguous source intervals. These positions are relative to the trimmed source, so they begin at zero and end at `out - in`:

```json
{
  "segments": [
    {"start": 0, "end": 1, "speed": 2},
    {"start": 1, "end": 3, "speed": 0.5},
    {"start": 3, "end": 4, "speed": 2}
  ]
}
```

This four-second source selection produces about five seconds of output: half a second, four seconds, then half a second. A clip supports up to 64 segments, each with speed 0.125–8. Segment durations are quantized to the output frame grid during rendering. Clip audio is retimed using chained tempo filters. The ramp is piecewise constant; no optical-flow interpolation is claimed.

## Audio and sound effects

```json
{
  "id": "a_UNIQUE_ID",
  "asset_id": "AUDIO_ASSET_ID",
  "start": 0,
  "in": 12,
  "out": 28,
  "volume": 0.7,
  "fade_in": 0.15,
  "fade_out": 0.5,
  "loop": false
}
```

`start` is a position in the edited timeline. `in/out` select source audio. Music and sound effects use the same track type, so multiple timed hits can be placed precisely. For a loop, set `loop: true` and `duration` to its total timeline length. Only the selected source interval is repeated. Fade times apply to the resulting audio track.

Audio is mixed at 48 kHz stereo. `normalize_audio: true` applies single-pass loudness normalization; false applies a peak limiter. Fade and volume edits remain editable in the project.

## Overlay

```json
{
  "id": "o_UNIQUE_ID",
  "asset_id": "OVERLAY_ASSET_ID",
  "start": 3,
  "duration": 1.2,
  "in": 0,
  "opacity": 0.5,
  "blend": "screen",
  "width": 1,
  "x": 0.5,
  "y": 0.5,
  "loop": false
}
```

`width` is a fraction of canvas width; the source aspect ratio is preserved. `x/y` position the overlay in the available space: 0 is left/top, 0.5 centered, and 1 right/bottom. Blend modes are `normal`, `screen`, `add`, `lighten` and `chroma`. Screen/add/lighten work well with light effects on black backgrounds. Normal preserves supported source alpha. Chroma accepts optional `key_color` (default `#00ff00`) and `key_similarity` (default 0.15).

A finite overlay disappears when its source ends or its selected timeline range ends; it does not freeze indefinitely. `loop: true` repeats a video source. Still images naturally fill the specified duration. Animated GIFs are finite media rather than indefinitely looped stills.

Consecutive `normal` overlays render in batches of up to four, preserving list order while reducing intermediate video encodes. Other blend modes keep separate passes. Still and looping inputs retain a small decoding margin so a full-duration layer covers the final frame after clip-concatenation rounding; its visible timing remains bounded by the requested interval.

## Arrows, circles and rectangles

```json
{
  "id": "s_UNIQUE_ID", "kind": "ellipse",
  "start": 5, "duration": 2,
  "x": 0.35, "y": 0.55, "x2": 0.65, "y2": 0.9,
  "color": "#ff3030", "stroke_width": 12, "opacity": 1
}
```

The project `shapes` list accepts up to 64 entries. `kind` is `arrow`, `ellipse` or `rectangle`. All coordinates are normalized 0–1: opposite corners for ellipse/rectangle, tail `(x,y)` to tip `(x2,y2)` for arrows. A circle is an ellipse with equal width and height in canvas pixels; normalized spans differ on a nonsquare canvas. Shapes need nonzero geometry. Colors use `#RRGGBB`; stroke width is 1–256 full-canvas pixels and scales for preview, while opacity is 0–1. Defaults are red `#ff3030`, 12 pixels and full opacity.

Timing is `[start, start + duration)` on the assembled timeline, with positive duration ending within the timeline. Shapes render after media overlays and before titles/captions, in list order. They are static callouts, not automatically tracked to subjects.

## Title

```json
{
  "id": "t_UNIQUE_ID",
  "text": "A literal title: 100%",
  "start": 0.3,
  "duration": 2,
  "font_asset_id": null,
  "font_size": 64,
  "x": 0.5,
  "y": 0.8,
  "color": "#ffffff",
  "box": true,
  "fade": 0.15
}
```

Font size is measured in full-project pixels and scales down for previews. A null font uses the system default; a catalogued TTF/OTF ID selects your font. Text is passed through a UTF-8 text file with expansion disabled, so punctuation is literal. `x/y` use the same free-space placement rule as overlays. `fade` is the fade-in and fade-out time, limited to half the title duration.

## Atomic edit operations

`project_edit` accepts one project ID, one expected revision, and a list of operations. The whole edited document is validated before a new revision is written.

| Operation | Fields |
|---|---|
| `add_clip` | `clip` object; optional insertion `index` |
| `update_clip` | `clip_id`, `changes` object |
| `remove_clip` | `clip_id` |
| `reorder_clips` | `clip_ids`, listing each existing clip exactly once |
| `add_audio` / `update_audio` / `remove_audio` | `audio`, or `audio_id` and optional `changes` |
| `add_overlay` / `update_overlay` / `remove_overlay` | `overlay`, or `overlay_id` and optional `changes` |
| `add_shape` / `update_shape` / `remove_shape` | `shape`, or `shape_id` and optional `changes` |
| `add_title` / `update_title` / `remove_title` | `title`, or `title_id` and optional `changes` |
| `set_canvas` | `canvas` with changed canvas fields |
| `rename` | `name` |
| `set_markers` | `markers: [{time, label}]` |
| `add_caption` / `update_caption` / `remove_caption` | `caption`, or `caption_id` and optional `changes` |
| `set_caption_style` | `caption_style` with changed style fields |

New entry IDs are generated when omitted. Direct `project_save` calls must include IDs for all entries. Update operations cannot change an entry's ID. `changes` merges the entry's top-level fields; a supplied nested `transform`, `color`, `effects`, `segments`, `motion`, `freeze` or `volume_keyframes` value replaces that whole value. Include the existing nested settings you want to retain. `set_canvas` and `set_caption_style` merge their supplied fields with the current settings.

If a revision conflict occurs, reload the project, compare the changes and apply a new edit against the returned revision. Do not automatically retry with a new revision while blindly overwriting another edit.

## Caption track

Captions use their own list rather than title layers:

```json
{
  "captions": [{"id": "cap_UNIQUE_ID", "start": 0.5, "end": 2.0, "text": "An editable caption"}],
  "caption_style": {
    "preset": "clean", "font_size": 52, "font_asset_id": null,
    "color": "#ffffff", "outline_color": "#000000", "outline": 3,
    "position": "bottom", "margin": 80
  }
}
```

There may be up to 2000 cues, each with at most 2000 characters, and at most 500000 caption characters in total. `start` is at least zero, `end` is at most 14400 seconds, and cues must last at least 10 ms. Overlapping cues are permitted, but check their rendered layout. Presets are `clean`, `bold` and `boxed`; positions are `bottom`, `center` and `top`. Font size is 8–512 full-canvas pixels, outline thickness 0–12, and margin 0–2000 pixels. Fill and outline colors accept `#RRGGBB` or `#RRGGBBAA`, where the final byte is opacity. A null font selects the default; a catalogued TTF/OTF ID selects a local font. Preview typography scales with the canvas.

Captions are serialized into one literal-text ASS script and rendered through libass. Endpoints round inward to centiseconds, so a caption does not appear before its requested start or after its requested end; an interval that collapses on this grid is skipped. Unsupported imported SRT/WebVTT styling is reduced to plain text; app styling remains editable separately. Export escapes literal angle brackets and ampersands and preserves ordinary line breaks. Blank lines separate cues in SRT/WebVTT, so avoid empty paragraphs inside a cue when exchanging those formats.

`captions_import` takes required `project_id`, `expected_revision` and `text`; `format` defaults to `srt`, `offset` defaults to zero, and `replace` defaults to true. A positive offset moves cues later in the timeline. Import accepts up to 2,097,152 characters, removes cue markup, decodes entities, and validates the whole project before saving. WebVTT requires a `WEBVTT` header; BOM and CRLF files are accepted. `captions_export` takes `project_id` and optional `format`, returns `{format, text, path, cue_count, revision}`, and creates a revision-qualified subtitle file without overwriting differing existing content.

With the optional offline model installed, `captions_transcribe` takes `project_id`, a completed `render_job_id`, and optional `language` (`auto` by default, or a supported code) and `model`. Model choices are `tiny`, `base`, `small`, `medium` and `large-v3`; a requested model must already be cached. Inspect `transcription_status.models`, or cache one with `python3 setup_transcription.py --python python3.12 --model small`. Omitting `model` uses the installed default. It returns an asynchronous job with `kind: "transcription"`. The rendered timeline must still match the project's clips, audio, canvas and normalization settings. Caption and title edits or project renaming do not invalidate that audio snapshot. Once complete, `result.captions` holds draft cues and `result.path` points to the draft SRT.

`captions_apply` requires the same project, `job_id`, current `expected_revision`, and optional `replace`; it rechecks timeline timing and creates a new revision. Both import and apply **replace all current captions by default**. Pass `replace: false` to append and retain existing manual cues. Appending sorts cues by timing without deduplicating them. Empty transcripts raise `no_speech_detected` and leave the project unchanged. Transcription jobs have no playable MP4 endpoint.

## Job lifecycle

`render_start` snapshots the current project and returns a job object. Its status progresses from `queued` to `running`, then `completed`, `failed` or `cancelled`. Renders, transcriptions and background-removal jobs share one active worker slot. `progress` is a fraction from 0 to 1; `message` describes the current stage. A completed render includes `output_path` and result metadata; a completed transcription includes draft caption metadata instead. A background-removal job has `kind: "background_removal"` and returns its transparent PNG catalog entry in `result.asset`; it does not attach that image to any project automatically.

The exact timeline revision rendered is preserved with the job. Saving new edits while a render runs does not change that export. Poll `job_status`, then inspect the completed video before starting another export. `job_cancel` requests termination of the active FFmpeg operation and removes incomplete output.


## Import and optional background removal

`asset_import({"path":"~/Downloads/skull.jpg"})` imports a deliberately selected local media, font or LUT file and returns its asset entry. Use an absolute local path; `~` expands to the local user's home. Supported extensionless JPEG, PNG and WebP files are recognized. Files are copied into the library when necessary; originals are preserved. Imports are limited to nonempty regular files up to 20 GiB.

Install the optional offline cutout engine with `python3 setup_background.py --python python3.12`, which downloads rembg and its model. Inspect `background_removal_status`, then call `image_background_remove({"asset_id":"IMAGE_ASSET_ID"})`. Poll the returned job ID with `job_status`; use the completed `result.asset.id` in an overlay with `blend: "normal"` to retain transparency. Cutouts support still images up to 24 megapixels; GIFs are excluded. Review the generated edges before export. Once installed and cached, the model runs locally.
