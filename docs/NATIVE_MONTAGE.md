# Native montage workflow

Framedrop 0.3 keeps lyric typography and kill accents editable. Use the browser's Captions panel and Accent button, or apply the same operations through MCP/CLI. The following times illustrate independent words; replace them with onsets and offsets verified against your soundtrack.

Create a project and add footage/music first. Read `project_get`, then submit these operations with its current `expected_revision`:

```json
[
  {"op":"set_export_profile","export_profile":"high"},
  {"op":"set_caption_style","caption_style":{
    "preset":"neon","font_size":110,"color":"#fff5fc",
    "outline_color":"#ff62c6","outline":1,"position":"center",
    "animation":"pop","animation_duration":0.16,"glow":0.7,"glow_color":"#ff62c6"
  }},
  {"op":"add_caption","caption":{"text":"OHO","start":6.69,"end":7.62}},
  {"op":"add_caption","caption":{"text":"HUPS","start":7.65,"end":8.30}},
  {"op":"add_caption","caption":{"text":"SORI","start":8.51,"end":9.00}},
  {"op":"add_caption","caption":{"text":"XD","start":9.07,"end":9.95}},
  {"op":"add_accent","accent":{"kind":"impact_ring","start":7.60,"duration":0.43,"color":"#ff62c6","size":0.26}},
  {"op":"add_accent","accent":{"kind":"light_sweep","start":6.65,"duration":0.24,"color":"#ffc0e8","opacity":0.35}},
  {"op":"add_title","title":{"text":"2K","start":16.20,"duration":0.85,"font_size":70,"x":0.22,"y":0.68,"box":false,"animation":"slide_up","glow":0.6}}
]
```

Choose a custom library font with `font_asset_id`. The app does not bundle third-party typography, footage, songs, or character art. Existing imported transparent graphics remain normal overlays.

For automatic word drafts, first render this timeline's audio, then call `captions_transcribe` with `mode:"words"` and that render's job ID. Poll, review, and use `captions_apply`. CLI equivalent:

```bash
framedrop captions transcribe PROJECT_ID --render-job RENDER_JOB_ID --mode words --language fi
```

Each word has its own cue and entry animation. SRT/VTT export preserves timings and text; subtitle files do not encode Framedrop's animation/glow style. For recurring hook words, duplicate/add cues at their actual onsets, not simply at every beat.

## Smooth gameplay and impacts

A 60 fps clip played at 0.6× has only 36 unique frames per second. Raising export fps repeats those frames unless interpolation is enabled. Inspect `render_plan` and prefer a continuous real-time section when possible. For slow motion, use `update_clip` with `changes:{"interpolation":"optical_flow"}`. Set `motion_blur:0.25` for subtle two-sample blur. Both operations can slow renders; inspect fast camera turns and UI edges for interpolation artifacts.

Pan/zoom keyframes use clip-local output time. For example:

```json
{"motion":[
  {"time":0,"zoom":1,"x":0.5,"y":0.5,"easing":"ease_out"},
  {"time":0.12,"zoom":1.08,"x":0.5,"y":0.5,"easing":"ease_in_out"},
  {"time":0.40,"zoom":1,"x":0.5,"y":0.5}
]}
```

Limit flashes/RGB splits to short kill windows. Accents do not overlap or shorten adjacent footage; transitions do. High-quality exports use the configured canvas resolution. Render previews are intentionally smaller, so judge final detail from a final export.
