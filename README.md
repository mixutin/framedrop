# Framedrop

**AI-assisted video editor. Local media. MCP, CLI, and a browser workspace.**

This is vibe coded slop. I use it for quick AI-assisted edits.

Framedrop lets an AI agent assemble and render edits through MCP while you inspect and adjust the same timeline in a local app. It uses FFmpeg, saves editable JSON projects, and keeps original media intact. No API key or cloud rendering service is required. Optional speech transcription and image cutouts run locally after their models are downloaded.

## What it does

- **Freeze frames:** choose a source timestamp and hold duration. Native freezes are silent, so an alarm or sound effect can play by itself.
- **Callouts:** draw red arrows, circles/ellipses, and rectangles directly on a timed shapes track. No external image editor needed.
- **Motion:** animate pan and zoom with linear or eased keyframes, including on a freeze frame.
- **Native montage graphics:** animate individual neon lyric words and titles with smooth pop, fade, or slide entries. Place impact rings, spark bursts, and light sweeps at kills and beats without preparing overlay videos.
- **Smooth playback:** optional optical-flow interpolation for slow footage, plus motion-compensated two-sample blur. Render plans flag repeated-frame cadence and full-length ghost trails.
- **Quality:** standard or high-quality export profiles; the latter reduces compression in intermediate passes and the final encode.
- **Effects:** 28 native effects, including shake, impact, RGB split, glow, pixelation, neon edges, posterization, echo trails, scanlines, and inversion. Limit each effect to a precise time window.
- **Audio:** mix source sound, music, and effects; align sounds with a freeze; mute tracks; automate gain with keyframes; use fades and loudness normalization.
- **Captions:** edit styled caption cues, import/export SRT or VTT, and generate offline Whisper drafts as phrases or individual timestamped words. Select a cached tiny, base, small, medium, or large-v3 model. Review drafts before applying them.
- **Images:** import local files, including JPEGs without an extension; remove backgrounds with an optional local model; composite transparent PNGs and other overlays.
- **Editing:** trim/reorder clips, piecewise speed ramps, color adjustment, LUTs, titles, transitions, revision history, and preview/final H.264/AAC export.

The browser, CLI, and MCP server use the same editing service and renderer. Jobs are asynchronous and report completion or failure; queued does not mean rendered.

## Install

Linux, Python 3.11+, FFmpeg with libx264/libass/drawtext, and fontconfig for custom caption fonts. Core editing has no third-party Python dependencies.

```bash
git clone https://github.com/mixutin/framedrop.git
cd framedrop
mkdir -p "$HOME/Editing"
python3 install.py --media-root "$HOME/Editing" --register-mcp --start
```

Open **Framedrop** from your applications menu or visit **http://127.0.0.1:8741**. Omit `--register-mcp` for non-Codex clients and `--start` to run it manually with `framedrop ui --open`.

The installer uses a per-user service, requires no sudo, and preserves existing Montage Studio libraries, projects, models, and history. The old `montage` command remains an alias. The Python package is still named `montage_studio` for compatibility.

Optional AI tools (download once, then run locally):

```bash
python3 setup_transcription.py --python python3.12 --model base
python3 setup_transcription.py --python python3.12 --model medium
python3 setup_background.py --python python3.12
```

The speech installer makes the requested model the default; other cached models remain selectable. Image cutouts use rembg's `isnet-general-use` model. Inspect cutout edges and correct caption wording: neither model is guaranteed to get every detail right.

## MCP

For a local MCP client, launch the installed executable:

```json
{
  "mcpServers": {
    "framedrop": {
      "command": "/absolute/path/to/.local/bin/framedrop",
      "args": ["mcp"]
    }
  }
}
```

`plugin.json` and `mcp.json` also provide a portable local plugin package. Reload your MCP client after upgrading so it discovers the new tools and schema.

Start with `system_status`, `asset_import` or `library_scan`, then `assets_list`. Create a project, read its current revision, and use `project_edit` or `project_save`. Inspect `render_plan` before `render_start`, then poll `job_status`. Captions and background removal also return jobs that need polling.

Every tool is available from the CLI:

```bash
framedrop status
framedrop tools
framedrop call asset_import --json '{"path":"/absolute/path/to/clip.mp4"}'
framedrop project new "Death edit" --format landscape --fps 60
framedrop project edit PROJECT_ID --revision 0 --file operations.json
framedrop render PROJECT_ID --plan
framedrop render PROJECT_ID --quality final --wait
```

See the [quickstart](docs/QUICKSTART.md) for an end-to-end death-freeze edit, and the [timeline reference](docs/TIMELINE.md) for exact fields and examples. The [native montage recipe](docs/NATIVE_MONTAGE.md) covers animated lyrics, kill accents, motion blur, and quality settings.

## Local storage and limits

New installs use `~/.config/framedrop/config.json`, `~/.local/share/framedrop`, and `Framedrop/` inside your media folder. Upgrades reuse legacy paths recorded in your existing configuration; no source media or projects are relocated. `MONTAGE_CONFIG` and the existing `MONTAGE_*` overrides remain supported, with `FRAMEDROP_CONFIG` available for the config path.

The app binds to loopback and checks origin/session tokens for writes. It is a local personal editor, not a multi-user hosting service. Your MCP client receives the media metadata, transcript text, and previews it requests; local rendering does not imply your AI client is offline.

The source player is not a live composite. Render a preview to see all effects, layers, captions, timing, and audio together. Exports are SDR H.264/AAC. There is one sequential footage track with layered audio, images, titles, and shapes; no optical-flow retiming, object tracking, or native After Effects/Fusion preset execution. Variable-frame-rate freeze selection is approximate. Effects are implemented as bounded, allowlisted FFmpeg recipes, not arbitrary filter commands.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q montage_studio
node --check montage_studio/static/app.js
```

Tests render generated media and check timing, real pixels/audio, revision conflicts, job cancellation, imports, and MCP/HTTP behavior. They do not require your footage or download AI models. See [verification notes](docs/VALIDATION.md).

## License

[0BSD](LICENSE) — BSD Zero Clause. Framedrop's original application code is covered by this license. Dependencies, downloaded models, and your media retain their own licenses. No game footage, music, fonts, models, or third-party editing packs are bundled in this repository.
