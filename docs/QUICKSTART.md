# Framedrop quickstart: an editable death freeze

Framedrop's browser app, MCP server and CLI share the same project files. Install using the [README](../README.md), then run `framedrop ui --open`. The default editor address is [http://127.0.0.1:8741](http://127.0.0.1:8741). The `montage` command alias and Python module `montage_studio` remain available for compatibility.

## Connect an MCP client

```json
{
  "mcpServers": {
    "framedrop": {"command": "framedrop", "args": ["mcp"]}
  }
}
```

If the client cannot find `framedrop`, replace `command` with the expanded absolute path to `~/.local/bin/framedrop`. The client launches a stdio server; the browser address is not an HTTP MCP endpoint. Restart the client connection after an upgrade to reload tool definitions.

The examples use `framedrop call TOOL_NAME` with JSON arguments. MCP clients call the same tools with the same objects. Run `framedrop tools` to inspect current schemas. Substitute all uppercase asset, project and job placeholders with IDs returned by your tools.

## 1. Import the clip, skull and alarm

```bash
framedrop call system_status
framedrop call asset_import --json '{"path":"~/Downloads/clip.mp4"}'
framedrop call asset_import --json '{"path":"~/Downloads/skull.jpg"}'
framedrop call library_scan
framedrop call assets_list --json '{"query":"alarm","kind":"audio","limit":20}'
framedrop call asset_probe --json '{"asset_id":"VIDEO_ID"}'
framedrop call asset_probe --json '{"asset_id":"ALARM_ID"}'
framedrop call asset_preview --json '{"asset_id":"VIDEO_ID","time":5}'
```

Imports preserve originals; `~` expands locally. Extensionless JPEG, PNG and WebP images are recognized. Search uses your configured media library, such as `~/Editing`. Import an alarm from another folder with `asset_import` when needed.

Inspect the exact death frame. This example assumes death at source/timeline **5.0 seconds**, footage longer than 6 seconds, and at least 2 seconds of alarm audio. Adjust those values to your sources. The source preview shows original footage; a rendered preview shows the full edit.

If the skull needs its background removed, install the optional local model from the repository directory:

```bash
python3 setup_background.py --python python3.12
framedrop call background_removal_status
framedrop call image_background_remove --json '{"asset_id":"SKULL_IMAGE_ID"}'
framedrop call job_status --json '{"job_id":"CUTOUT_JOB_ID"}'
```

Poll until completed, inspect the PNG, and use `result.asset.id` as `SKULL_CUTOUT_ID` below. Installation downloads rembg and the model; processing then runs locally. A source PNG that already has transparency can be used directly.

## 2. Create the edit in one transaction

```bash
framedrop call project_create --json '{"name":"Death freeze","width":1920,"height":1080,"fps":60}'
framedrop call project_edit --file - <<'JSON'
{
  "project_id": "PROJECT_ID",
  "expected_revision": 0,
  "operations": [
    {"op":"add_clip","clip":{
      "asset_id":"VIDEO_ID","in":0,"out":5,"volume":1,
      "transition":{"name":"cut","duration":0}
    }},
    {"op":"add_clip","clip":{
      "asset_id":"VIDEO_ID","in":5,"out":6,
      "freeze":{"time":5,"duration":2},
      "color":{"brightness":-0.23},
      "motion":[
        {"time":0,"zoom":1,"x":0.5,"y":0.5},
        {"time":2,"zoom":1.1,"x":0.5,"y":0.65}
      ]
    }},
    {"op":"add_audio","audio":{
      "asset_id":"ALARM_ID","start":5,"in":0,"out":2,"volume":0.8
    }},
    {"op":"add_overlay","overlay":{
      "asset_id":"SKULL_CUTOUT_ID","start":5,"duration":2,
      "blend":"normal","opacity":1,"width":0.15,"x":0.75,"y":0.65
    }},
    {"op":"add_shape","shape":{
      "kind":"ellipse","start":5,"duration":2,
      "x":0.4,"y":0.5,"x2":0.6,"y2":0.86,
      "color":"#ff3030","stroke_width":16
    }},
    {"op":"add_shape","shape":{
      "kind":"arrow","start":5,"duration":2,
      "x":0.18,"y":0.3,"x2":0.44,"y2":0.62,
      "color":"#ff3030","stroke_width":24
    }},
    {"op":"add_shape","shape":{
      "kind":"arrow","start":5,"duration":2,
      "x":0.83,"y":0.25,"x2":0.57,"y2":0.61,
      "color":"#ff3030","stroke_width":24
    }},
    {"op":"add_caption","caption":{
      "start":3.8,"end":4.9,"text":"Don't peek."
    }},
    {"op":"set_caption_style","caption_style":{
      "preset":"bold","font_size":60,"margin":80,"outline":3
    }}
  ]
}
JSON
```

This produces a seven-second timeline. The first clip plays with its original audio; the native freeze is automatically silent. The alarm, skull and callouts all begin at 5.0 seconds. No manually extracted still is required. Replace the example caption with the actual speech, and position the arrows/circle over the body in the rendered preview. Callouts remain static while the example freeze slowly zooms; remove `motion` for a completely static picture.

Each save increments the revision. Before further edits, read `project_get` and use its current `revision` as `expected_revision`. On a revision conflict, reload and compare changes before retrying. Update operations merge top-level fields; nested objects/lists replace the previous value in full.

## 3. Render, review and refine

```bash
framedrop call project_validate --json '{"project_id":"PROJECT_ID"}'
framedrop render PROJECT_ID --quality preview --wait
framedrop call project_get --json '{"project_id":"PROJECT_ID"}'
```

The waiting CLI prints progress and then the completed job. With MCP, call `render_start({"project_id":"PROJECT_ID","quality":"preview"})`, then poll `job_status({"job_id":"RENDER_JOB_ID"})`. A returned job is not yet a successful render: wait for `status: "completed"` and inspect `output_path`, or play the export in the app.

Preview output has a maximum edge of 960 pixels; final output uses the project canvas. Adjust clip settings, caption text and timing, shape bounds or alarm volume in the app, or use `project_edit` with `update_clip`, `update_shape`, `update_audio`, `update_overlay` and `update_caption`. IDs are in `project_get`. Then export:

```bash
framedrop render PROJECT_ID --quality final --wait
```

Only one render, transcription or cutout job runs at a time. Use `framedrop jobs JOB_ID` to inspect a job and `framedrop cancel JOB_ID` to cancel it. Completed media and source files are preserved.

## 4. Optional speech captions and stronger models

From the repository directory, install a multilingual model into the optional local speech environment:

```bash
python3 setup_transcription.py --python python3.12 --model small
framedrop call transcription_status
framedrop call captions_transcribe --json '{"project_id":"PROJECT_ID","render_job_id":"RENDER_JOB_ID","language":"auto","model":"small"}'
framedrop call job_status --json '{"job_id":"TRANSCRIPTION_JOB_ID"}'
```

Model choices are `tiny`, `base`, `small`, `medium` and `large-v3`. Larger models use more resources and take longer. Run the installer for each model you want cached; `transcription_status.models` lists available choices. Omitting `model` uses the installed default. Choose a known speech language such as `fi` or `en`, or let `auto` detect it.

Transcription listens to a completed render of the current timeline, so cuts, speed changes, the silent freeze and the audio mix determine cue timing. Changing that timeline requires a fresh render. The completed job contains editable drafts in `result.captions` and an SRT at `result.path`.

Review the draft, then load the current project revision and apply it:

```bash
framedrop call project_get --json '{"project_id":"PROJECT_ID"}'
framedrop call captions_apply --json '{"project_id":"PROJECT_ID","job_id":"TRANSCRIPTION_JOB_ID","expected_revision":1,"replace":false}'
```

Replace `1` with the current revision. `replace:false` appends and retains manual cues; review overlaps because it does not deduplicate them. The default `replace:true` replaces the caption track. Correct recognition mistakes and timing in the app before the final export. Manual caption editing and SRT/VTT exchange work without a speech model:

```bash
framedrop captions import PROJECT_ID captions.srt --revision 2 --append
framedrop captions export PROJECT_ID --format vtt
```

Use the actual current revision for imports. The [timeline reference](TIMELINE.md) covers motion/gain keyframes, timed effects, transforms, LUTs and the complete caption schema.

## Files, history and upgrades

New installations use `~/.config/framedrop/config.json` and `~/.local/share/framedrop` for configuration and state. The installer reuses existing legacy configuration/data when present. Run `framedrop status` to inspect the effective media root and workspace instead of assuming an upgrade moved your files.

The configured workspace contains `projects`, `history`, `renders` and `captions`; state contains `jobs/JOB_ID`, draft transcripts, logs and model environments. `framedrop project history PROJECT_ID` lists saved revisions; `project_restore` restores one as a new revision. The Python package remains `montage_studio`, so source commands such as `python3 -m montage_studio tools` continue to work.
