"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const uid = () => window.crypto?.randomUUID?.() || `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const round = (value, digits = 3) => Math.round(number(value) * 10 ** digits) / 10 ** digits;
  const fmt = (value) => { const n = Math.max(0, number(value)); return `${String(Math.floor(n / 60)).padStart(2, "0")}:${(n % 60).toFixed(2).padStart(5, "0")}`; };
  const seconds = (value) => `${round(value, 2)}s`;
  const bytes = (value) => { const n = number(value); if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`; if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`; return `${Math.max(1, Math.round(n / 1e3))} KB`; };
  const titleCase = (value) => String(value || "").replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const icons = {
    shape:'<path d="m3 20 15-15M11 5h7v7"/><ellipse cx="8" cy="15" rx="6" ry="5"/>',
    plus:'<path d="M12 5v14M5 12h14"/>', minus:'<path d="M5 12h14"/>', x:'<path d="m6 6 12 12M18 6 6 18"/>',
    search:'<circle cx="10.7" cy="10.7" r="6.7"/><path d="m16 16 4.5 4.5"/>',
    refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.6-2L20 8M4 16l2.3 3A7 7 0 0 0 18 17"/>',
    save:'<path d="M4 3h13l4 4v14H3V3h1Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    export:'<path d="M12 15V3m-4 4 4-4 4 4M5 12v8h14v-8"/>',
    undo:'<path d="M8 4 3 9l5 5M3 9h11a6 6 0 0 1 0 12h-3"/>',
    terminal:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/>',
    play:'<path d="m8 4 12 8-12 8V4Z"/>', pause:'<path d="M8 5v14M16 5v14"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>', check:'<path d="m5 12 4 4L19 6"/>',
    folder:'<path d="M3 7V5h6l2 2h10v13H3V7Z"/>',
    frame:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 6 3-6 3V9Z"/>',
    film:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/>',
    music:'<path d="M9 18V5l12-2v13M9 8l12-2"/><ellipse cx="5.5" cy="18" rx="3.5" ry="3"/><ellipse cx="17.5" cy="16" rx="3.5" ry="3"/>',
    layers:'<path d="m12 3 10 5-10 5L2 8l10-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
    type:'<path d="M4 7V4h16v3M12 4v16M8 20h8"/>',
    captions:'<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M10 10H7v4h3M18 10h-3v4h3"/>',
    sparkles:'<path d="m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8L12 3ZM20 2v4M18 4h4"/>',
    settings:'<path d="M4 6h8M16 6h4M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="14" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    fullscreen:'<path d="M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    timeline:'<path d="M3 4h18v4H3zM3 11h11v4H3zM3 18h15v3H3z"/>',
    wave:'<path d="M3 10v4M6 6v12M9 9v6M12 3v18M15 8v8M18 5v14M21 10v4"/>',
    download:'<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
    archive:'<path d="M4 7h16v14H4V7ZM3 3h18v4H3V3ZM10 11h4M12 11v5m-2 0h4"/>',
    file:'<path d="M5 3h9l5 5v13H5V3Zm9 0v6h5M8 13h8M8 17h6"/>',
    image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-6-6L3 21"/>',
    fx:'<path d="M12 4H9a3 3 0 0 0-3 3v10a3 3 0 0 1-3 3M3 10h7m4 1 7 9m0-9-7 9"/>',
    left:'<path d="m14 5-7 7 7 7"/>', right:'<path d="m10 5 7 7-7 7"/>',
    scissors:'<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8 8 13 13M8 16 21 3"/>',
    volume:'<path d="m11 4-5 4H2v8h4l5 4V4ZM15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
    render:'<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9h18M6 3l3 6M13 3l3 6m-6 3 5 3-5 3v-6Z"/>',
    bolt:'<path d="m13 2-9 12h7l-1 8 10-13h-7l0-7Z"/>'
  };
  const icon = (name, extraClass = "") => `<svg class="icon ${extraClass}" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
  function hydrateIcons(root = document) { root.querySelectorAll("[data-icon]").forEach((el) => { el.innerHTML = icon(el.dataset.icon); }); }
  const S = {
    csrf: "", status: {}, projects: [], effects: [], transitions: [], assets: [], assetsMap: new Map(), fonts: [],
    libraryMode: "assets", filter: "all", otherKind: "preset", query: "", total: 0, offset: 0, request: 0,
    project: null, dirty: false, editVersion: 0, undo: [], selection: null, selectedClipId: null, selectedTitleId: null,
    source: null, viewerMode: "source", rendered: null, job: null, pollTimer: null, saving: null,
    zoom: 1, pps: 40, playhead: 0, analysis: new Map(), changingProject: false
  };
  function toast(message, type = "info", duration = 6500) {
    const el = document.createElement("div"); el.className = `toast ${type}`;
    el.innerHTML = `${icon(type === "success" ? "check" : "info")}<span>${escapeHTML(message)}</span><button aria-label="Dismiss notification">×</button>`;
    el.querySelector("button").onclick = () => el.remove(); $("toast-region").append(el);
    if (duration) setTimeout(() => el.remove(), duration);
  }
  function report(error) { toast(error?.message || String(error), "error", 11000); }
  function run(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(report); }
  async function call(tool, args = {}, timeout = 180000) {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), timeout);
    let response;
    try {
      response = await fetch("/api/call", {method: "POST", headers: {"Content-Type": "application/json", "X-Montage-Token": S.csrf}, body: JSON.stringify({tool, arguments: args}), signal: controller.signal});
      const data = await response.json();
      if (!response.ok || !data.ok) { const e = new Error(typeof data.error === "string" ? data.error : data.error?.message || `Request failed (${response.status}).`); e.status = response.status; e.code = data.code; throw e; }
      $("connection-dot").className = "status-dot ready";
      return data.result;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("This operation is taking too long. The server may still be working; check its status before trying again.");
      if (error instanceof TypeError) { $("connection-dot").className = "status-dot error"; throw new Error("Connection lost. Make sure Framedrop is still running on this computer."); }
      throw error;
    } finally { clearTimeout(timer); }
  }
  function rememberAssets(assets) { for (const a of assets || []) { if (a && a.id) S.assetsMap.set(a.id, {...S.assetsMap.get(a.id), ...a}); } }
  const asset = (id) => S.assetsMap.get(id);
  const assetName = (id) => asset(id)?.name || "Loading source…";
  function metadataDuration(a) { return Math.max(0, number(a?.metadata?.duration)); }
  async function probeAsset(id) {
    const current = asset(id); if (current?.metadata && (metadataDuration(current) || ["font", "image", "lut", "preset", "reference", "project", "archive", "recipe"].includes(current.kind))) return current;
    const result = await call("asset_probe", {asset_id: id}); rememberAssets([result]); return result;
  }
  function clipDuration(clip) {
    if (clip.freeze) return number(clip.freeze.duration);
    if (clip.segments?.length) return clip.segments.reduce((sum, seg) => sum + Math.max(0, number(seg.end) - number(seg.start)) / Math.max(.01, number(seg.speed, 1)), 0);
    return Math.max(0, number(clip.out) - number(clip.in)) / Math.max(.01, number(clip.speed, 1));
  }
  function clipLayout() {
    const clips = S.project?.clips || []; let time = 0;
    return clips.map((clip, i) => {
      const duration = clipDuration(clip); const start = time;
      const transition = i < clips.length - 1 && clip.transition?.name !== "cut" ? Math.max(0, number(clip.transition?.duration)) : 0;
      time += duration - transition; return {clip, start, duration, transition};
    });
  }
  function projectDuration() { const layout = clipLayout(); const last = layout.at(-1); return last ? last.start + last.duration : 0; }
  function itemFor(type = S.selection?.type, id = S.selection?.id) { return S.project?.[type]?.find((item) => item.id === id); }
  function selectedClip() { return S.project?.clips.find((clip) => clip.id === S.selectedClipId); }
  function pushUndo() { S.undo.push({project: clone(S.project), dirty: S.dirty}); if (S.undo.length > 60) S.undo.shift(); }
  function mutate(fn, {inspector = true} = {}) {
    if (!S.project) return;
    pushUndo(); fn(S.project); S.dirty = true; S.editVersion++; syncHeader(); renderTimeline(); if (inspector) renderInspector(); updateCaption();
  }
  function syncHeader() {
    const p = S.project; const active = S.job && ["queued", "running"].includes(S.job.status);
    $("save-status").textContent = S.saving ? "Saving…" : S.dirty ? "Unsaved changes" : p ? `Saved · v${p.revision}` : "Local workspace";
    $("save-status").classList.toggle("dirty", S.dirty);
    $("save").disabled = !p || !S.dirty || !!S.saving;
    $("undo").disabled = !p || !!S.saving || (!S.undo.length && number(p.revision) <= 1);
    $("render-preview").disabled = !p?.clips?.length || active || !!S.saving;
    $("render-final").disabled = !p?.clips?.length || active || !!S.saving;
    $("add-title").disabled = !p; $("add-accent").disabled = !p;
    $("add-shape").disabled = !p?.clips?.length;
    $("canvas-label").textContent = p ? `${p.canvas.width} × ${p.canvas.height} · ${p.canvas.fps} fps` : "Canvas settings";
    $("project-select").value = p?.id || "";
    $("empty-create").hidden = !!p;
    document.title = p ? `${p.name}${S.dirty ? " •" : ""} — Framedrop` : "Framedrop";
  }
  function renderProjectOptions() {
    $("project-select").innerHTML = `<option value="">Choose a project</option>${S.projects.map((p) => `<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)}</option>`).join("")}`;
    $("project-select").value = S.project?.id || "";
  }
  async function refreshProjects() { const result = await call("project_list"); S.projects = result.projects || []; renderProjectOptions(); }
  async function hydrateProjectAssets() {
    const p = S.project; if (!p) return;
    const ids = [...new Set([...(p.clips || []), ...(p.audio || []), ...(p.overlays || [])].map((item) => item.asset_id).concat((p.clips || []).map((c) => c.lut_asset_id), (p.titles || []).map((t) => t.font_asset_id)).filter(Boolean))];
    const missing = ids.filter((id) => !asset(id));
    for (let i = 0; i < missing.length; i += 4) {
      await Promise.allSettled(missing.slice(i, i + 4).map((id) => probeAsset(id)));
      if (S.project?.id !== p.id) return;
      renderTimeline(); renderInspector();
    }
  }
  function setProject(project) {
    S.project = project; for (const key of ["clips", "audio", "overlays", "shapes", "titles", "markers", "captions", "accents"]) S.project[key] ||= [];
    S.project.caption_style ||= {preset:"clean",font_size:52,font_asset_id:null,color:"#ffffff",outline_color:"#000000",outline:3,position:"bottom",margin:80};
    S.dirty = false; S.undo = []; S.editVersion++; S.selection = {type:"project"}; S.selectedClipId = null; S.selectedTitleId = null;
    S.rendered = null; S.playhead = 0; resetViewer();
    try { localStorage.setItem("montage-project", project.id); } catch (_) { /* Private browsing may not allow storage. */ }
    const existing = S.projects.findIndex((p) => p.id === project.id); if (existing < 0) S.projects.unshift(project); else S.projects[existing] = project;
    renderProjectOptions(); syncHeader(); renderTimeline(); renderInspector();
    hydrateProjectAssets().catch(report);
    loadProjectJobs().catch(report);
  }
  async function switchProject(id, force = false) {
    if (!id || (id === S.project?.id && !force)) return;
    if (!force && S.dirty && !window.confirm("Discard your unsaved changes and open another project?")) { $("project-select").value = S.project.id; return; }
    if (S.saving) await S.saving;
    S.changingProject = true;
    try { setProject(await call("project_get", {project_id: id})); } finally { S.changingProject = false; }
  }
  async function saveProject() {
    if (!S.project || !S.dirty) return S.project;
    if (S.saving) return S.saving;
    const draft = clone(S.project); const stamp = S.editVersion;
    S.saving = (async () => {
      try {
        const saved = await call("project_save", {project: draft, expected_revision: draft.revision});
        if (S.project?.id === draft.id) {
          if (stamp === S.editVersion) { S.project = saved; S.dirty = false; S.undo = []; }
          else { S.project.revision = saved.revision; S.project.updated_at = saved.updated_at; S.undo.forEach((entry) => { entry.project.revision = saved.revision; entry.dirty = true; }); }
          const idx = S.projects.findIndex((p) => p.id === saved.id); if (idx >= 0) S.projects[idx] = saved;
          renderProjectOptions(); updateCaption();
        }
        return saved;
      } catch (error) {
        if (error.status === 409 || String(error.code || "").includes("conflict")) { showConflict(); throw new Error("This project was updated by another editor or AI tool. Your unsaved changes are still available here."); }
        throw error;
      } finally { S.saving = null; syncHeader(); }
    })();
    syncHeader(); return S.saving;
  }
  async function ensureSaved() { for (let i = 0; i < 3 && S.dirty; i++) await saveProject(); if (S.dirty) throw new Error("Finish the current edit, then try rendering again."); }
  async function undo() {
    if (!S.project) return;
    if (S.undo.length) { const old = S.undo.pop(); S.project = old.project; S.dirty = old.dirty; S.editVersion++; syncHeader(); renderInspector(); renderTimeline(); updateCaption(); return; }
    const history = await call("project_history", {project_id: S.project.id});
    const prior = (history.revisions || []).filter((entry) => number(entry.revision) < S.project.revision).sort((a, b) => b.revision - a.revision)[0];
    if (!prior) { toast("There isn’t an earlier saved revision for this project."); return; }
    const restored = await call("project_restore", {project_id: S.project.id, revision: prior.revision, expected_revision: S.project.revision});
    setProject(restored); toast(`Restored revision ${prior.revision} as a new saved revision.`, "success");
  }
  function showConflict() {
    dialog("A newer revision is available", `<p>Your project changed through another app, CLI, or MCP session. Your draft is still in this browser. You can keep working, save the draft as a new project, or load the latest saved version.</p>`, `<button class="button secondary" data-close>Keep my draft</button><button class="button secondary" id="conflict-copy">Save as a copy</button><button class="button primary" id="conflict-reload">Load latest</button>`);
    $("conflict-reload").onclick = run(async () => { if (window.confirm("Discard this unsaved draft and load the latest project?")) { closeDialog(); await switchProject(S.project.id, true); } });
    $("conflict-copy").onclick = run(async () => {
      const draft = clone(S.project); const created = await call("project_create", {name: `${draft.name.slice(0, 110)} copy`, width:draft.canvas.width, height:draft.canvas.height, fps:draft.canvas.fps});
      draft.id = created.id; draft.name = created.name; draft.revision = created.revision; draft.created_at = created.created_at;
      const saved = await call("project_save", {project:draft, expected_revision:created.revision}); closeDialog(); setProject(saved); toast("Your draft is saved as a separate project.", "success");
    });
  }

  function kindIcon(kind) { return ({video:"film", image:"image", audio:"wave", font:"type", archive:"archive", preset:"fx", lut:"layers", recipe:"file", project:"film"})[kind] || "file"; }
  function visualForAsset(a) {
    if (["video", "image"].includes(a.kind)) return `<img src="/api/thumbnail?id=${encodeURIComponent(a.id)}" loading="lazy" decoding="async" alt="">`;
    if (a.kind === "font") return '<span class="font-preview">Aa</span>';
    return icon(kindIcon(a.kind));
  }
  function externalAsset(a) { return a.supported === false || ["preset", "reference", "project", "recipe"].includes(a.kind); }
  function renderAssets() {
    if (S.libraryMode === "effects") return renderEffects();
    $("asset-grid").className = "asset-grid";
    $("library-filters").hidden = false; $("library-selection-hint").textContent = "Drag to timeline";
    $("library-count").textContent = `${S.total.toLocaleString()} ${S.total === 1 ? "asset" : "assets"}${S.query ? " found" : ""}`;
    if (!S.assets.length) {
      $("asset-grid").innerHTML = `<div class="grid-message">${icon("folder")}<strong>${S.query ? "No matching assets" : "No assets in this view"}</strong>${S.query ? "Try a shorter name or a different media filter." : "Your Editing folder is the media source. Add files there, then rescan the library."}</div>`;
    } else {
      $("asset-grid").innerHTML = S.assets.map((a) => `<article class="asset-card ${S.selection?.type === "asset" && S.selection.id === a.id ? "selected" : ""}" data-asset="${escapeHTML(a.id)}" tabindex="0" role="button" aria-label="Inspect ${escapeHTML(a.name)}" draggable="${["video", "audio", "image"].includes(a.kind)}" title="${escapeHTML(a.relative_path || a.name)}"><div class="asset-visual ${escapeHTML(a.kind)}">${visualForAsset(a)}<span class="asset-extension">${escapeHTML(String(a.extension || a.kind).replace(/^\./, ""))}</span>${["video", "audio", "image"].includes(a.kind) ? `<button class="asset-add" data-add-asset="${escapeHTML(a.id)}" title="Add to timeline" aria-label="Add ${escapeHTML(a.name)} to timeline">${icon("plus")}</button>` : ""}</div><div class="asset-caption"><span class="asset-name">${escapeHTML(a.name)}</span><div class="asset-meta"><span class="${externalAsset(a) ? "external" : ""}">${externalAsset(a) ? "External / reference" : escapeHTML(titleCase(a.category || a.kind))}</span><span>${metadataDuration(a) ? seconds(metadataDuration(a)) : bytes(a.size)}</span></div></div></article>`).join("");
    }
    $("library-footer").hidden = S.assets.length >= S.total; $("load-more").disabled = false;
  }
  function renderEffects() {
    $("asset-grid").className = "asset-grid effect-grid"; $("library-filters").hidden = true; $("library-footer").hidden = true;
    const query = S.query.toLowerCase(); const list = S.effects.filter((e) => `${e.name} ${e.label} ${e.category} ${e.description}`.toLowerCase().includes(query));
    $("library-count").textContent = `${list.length} native effects`; $("library-selection-hint").textContent = "Apply to a video clip";
    $("asset-grid").innerHTML = list.map((e) => `<button class="effect-card" data-effect="${escapeHTML(e.name)}" title="Apply ${escapeHTML(e.label)} to the selected clip"><span class="effect-tile">${icon(/shake|impact|punch|flash/i.test(e.name) ? "bolt" : /glow|bloom|dream/i.test(e.name) ? "sparkles" : /blur|rgb|zoom/i.test(e.name) ? "layers" : "fx")}</span><span><h3>${escapeHTML(e.label || titleCase(e.name))}</h3><p>${escapeHTML(e.description)}</p><span class="effect-type">${escapeHTML(e.category || "Effect")} · FFmpeg native</span></span><span class="effect-add">${icon("plus")}</span></button>`).join("") || `<div class="grid-message">${icon("fx")}<strong>No matching effects</strong>Try a different name.</div>`;
  }
  async function loadAssets(append = false) {
    if (S.libraryMode === "effects") { renderEffects(); return; }
    const request = ++S.request; const offset = append ? S.assets.length : 0;
    if (!append) $("asset-grid").innerHTML = Array.from({length:6}, () => '<div class="skeleton"></div>').join(""); else $("load-more").disabled = true;
    const args = {limit:60, offset, query:S.query};
    if (["video", "audio", "font"].includes(S.filter)) args.kind = S.filter;
    else if (S.filter === "overlay") args.category = "overlay";
    else if (S.filter === "other") args.kind = S.otherKind;
    try {
      const result = await call("assets_list", args);
      if (request !== S.request || S.libraryMode !== "assets") return;
      rememberAssets(result.items); S.assets = append ? S.assets.concat(result.items || []) : result.items || []; S.total = result.total || 0; S.offset = offset; renderAssets();
    } catch (error) { if (request === S.request) { $("asset-grid").innerHTML = `<div class="grid-message">${icon("info")}<strong>Couldn’t load the library</strong>${escapeHTML(error.message)}<button class="button secondary" id="retry-assets">Try again</button></div>`; $("retry-assets").onclick = run(() => loadAssets()); } throw error; }
  }
  function showLibrary(mode) {
    if(mode!==S.libraryMode){S.libraryQueries||={};S.libraryQueries[S.libraryMode]=S.query;S.query=S.libraryQueries[mode]||"";$("library-search").value=S.query;}
    S.libraryMode = mode; $("assets-tab").classList.toggle("active", mode === "assets"); $("effects-tab").classList.toggle("active", mode === "effects");
    $("assets-tab").setAttribute("aria-selected", String(mode === "assets")); $("effects-tab").setAttribute("aria-selected", String(mode === "effects"));
    $("library-search").placeholder = mode === "effects" ? "Find an effect…" : "Search your library…";
    if (mode === "effects") { S.request++; renderEffects(); } else loadAssets().catch(report);
  }
  async function selectAsset(id) {
    const a = asset(id); if (!a) return;
    S.selection = {type:"asset", id}; renderAssets(); renderInspector();
    if (["video", "audio", "image"].includes(a.kind)) setSource(a);
    if (!a.metadata && ["video", "audio", "image"].includes(a.kind)) {
      try { await probeAsset(id); if (S.selection?.type === "asset" && S.selection.id === id) renderInspector(); } catch (error) { report(error); }
    }
  }
  async function ensureProject() {
    if (S.project) return;
    if(S.creatingProject)return S.creatingProject;
    S.creatingProject=call("project_create", {name:"Untitled montage", width:1920, height:1080, fps:30}).then(setProject).finally(()=>{S.creatingProject=null;});
    return S.creatingProject;
  }
  async function addAsset(id, role) {
    const a = await probeAsset(id); if (!["video", "audio", "image"].includes(a.kind)) throw new Error("This asset is a reference for another editing tool; it cannot be placed directly on this timeline.");
    await ensureProject();
    role ||= a.kind === "audio" ? "audio" : "clips";
    const duration = metadataDuration(a); const newId = uid(); const total = projectDuration(); let item;
    if (role === "clips") {
      if (a.kind === "audio") throw new Error("Use the audio track for audio files.");
      item = {id:newId, asset_id:id, in:0, out:a.kind === "image" ? 4 : Math.min(4, duration || 4), speed:1, volume:1, fit:S.project.canvas.fit || "cover", effects:[], transition:{name:"cut", duration:0}, segments:[]};
    } else if (role === "audio") {
      if (a.kind === "image") throw new Error("Images do not have an audio stream.");
      if (a.kind === "video" && a.metadata?.has_audio === false) throw new Error("This video does not contain audio.");
      const length=Math.min(duration || 4, total || 16);
      item = {id:newId, asset_id:id, start:a.category === "sfx" ? round(S.playhead) : 0, in:0, out:length, volume:a.category === "sfx" ? 1 : .7, fade_in:Math.min(.2,length/2), fade_out:Math.min(.5,length/2), loop:false};
    } else if (role === "overlays") {
      if (a.kind === "audio") throw new Error("Audio files belong on the audio track.");
      item = {id:newId, asset_id:id, start:round(Math.min(S.playhead, Math.max(0, total - .1))), duration:Math.min(4, duration || total || 4), in:0, opacity:a.kind === "image" ? 1 : .7, blend:a.kind === "image" ? "normal" : "screen", width:1, x:.5, y:.5, loop:a.kind === "image"};
    } else throw new Error("Unknown timeline track.");
    mutate((p) => p[role].push(item)); selectItem(role, newId); toast(`Added ${a.name} to ${role === "clips" ? "video" : role}.`, "success", 2800);
  }
  function applyEffect(name) {
    const clip = selectedClip(); if (!clip) { toast("Select a video clip on the timeline, then choose an effect."); return; }
    const effect = S.effects.find((e) => e.name === name); if (!effect) return;
    mutate(() => { clip.effects ||= []; clip.effects.push({name, strength:number(effect.strength?.default, .7)}); S.selection = {type:"clips", id:clip.id}; });
    toast(`${effect.label || name} applied. Render a preview to see the result.`, "success", 4200);
  }

  function resetViewer() {
    const player = $("video-player"); player.pause(); player.removeAttribute("src"); player.load(); player.hidden = true;
    $("image-player").hidden = true; $("audio-art").hidden = true; $("viewer-empty").hidden = false; $("media-error").hidden = true; $("preview-badge").hidden = true;
    S.source = null; S.viewerMode = "source"; $("view-source").classList.add("active"); $("view-render").classList.remove("active"); $("view-render").disabled = true;
    $("viewer-name").textContent = S.project ? "Select footage to inspect" : "Your next cut starts here";
    $("play-pause").disabled = true; $("playback-seek").disabled = true; $("play-time").textContent = "00:00.00"; $("play-duration").textContent = "00:00.00";
    if (!S.job || S.job.kind !== "background_removal" && S.job.project_id !== S.project?.id) $("render-banner").hidden = true;
    updateCaption();
  }
  function setSource(a, sourceTime = null) {
    const player = $("video-player"); const same = S.viewerMode === "source" && S.source?.id === a.id;
    S.source = a; S.viewerMode = "source";
    $("view-source").classList.add("active"); $("view-render").classList.remove("active");
    $("viewer-name").textContent = a.name; $("viewer-empty").hidden = true; $("media-error").hidden = true;
    $("preview-badge").hidden = false; $("preview-badge").textContent = "SOURCE"; $("preview-badge").className = "preview-badge";
    player.hidden = a.kind !== "video"; $("audio-art").hidden = a.kind !== "audio"; $("image-player").hidden = a.kind !== "image";
    if (a.kind === "image") {
      player.pause(); if (!same) { player.removeAttribute("src"); player.load(); }
      $("image-player").src = `/api/media?id=${encodeURIComponent(a.id)}`; $("play-pause").disabled = true; $("playback-seek").disabled = true;
      $("play-time").textContent = "00:00.00"; $("play-duration").textContent = seconds(S.selection?.type === "clips" ? clipDuration(itemFor() || {}) : 0);
    } else if (["video", "audio"].includes(a.kind)) {
      if (!same) { player.pause(); player.src = `/api/media?id=${encodeURIComponent(a.id)}`; player.load(); }
      player.playbackRate = 1; $("audio-name").textContent = a.name;
      $("play-pause").disabled = false;
      if (sourceTime !== null) seekWhenReady(sourceTime);
    }
    updateCaption(); updatePlayhead();
  }
  function seekWhenReady(time) {
    const player = $("video-player"); const value = Math.max(0, number(time));
    if (player.readyState >= 1) player.currentTime = Math.min(value, Number.isFinite(player.duration) ? player.duration : value);
    else player.addEventListener("loadedmetadata", () => { player.currentTime = Math.min(value, Number.isFinite(player.duration) ? player.duration : value); }, {once:true});
  }
  function showRendered(job = S.rendered) {
    if (!job || job.status !== "completed" || job.kind === "transcription") return;
    const player = $("video-player"); player.pause(); S.viewerMode = "render"; S.rendered = job;
    player.src = `/api/output?job=${encodeURIComponent(job.id)}`; player.hidden = false; player.load(); player.playbackRate = 1;
    $("view-render").disabled = false; $("view-render").classList.add("active"); $("view-source").classList.remove("active");
    $("image-player").hidden = true; $("audio-art").hidden = true; $("viewer-empty").hidden = true; $("media-error").hidden = true;
    $("preview-badge").hidden = false; $("preview-badge").textContent = `${job.quality === "final" ? "EXPORT" : "PREVIEW"} · V${job.revision}`; $("preview-badge").className = "preview-badge rendered";
    $("viewer-name").textContent = job.project_name || S.project?.name || "Rendered output"; $("play-pause").disabled = false; updateCaption();
  }
  function updateCaption() {
    if (S.viewerMode === "render" && S.rendered) {
      const stale = S.dirty || S.project?.revision !== S.rendered.revision;
      $("viewer-caption").textContent = stale ? `Rendered revision ${S.rendered.revision} · your timeline has newer changes.` : `Rendered ${S.rendered.quality === "final" ? "export" : "preview"} · effects, transitions, titles and audio included.`;
    } else $("viewer-caption").textContent = S.source ? "Source playback · render a preview to see effects and the complete timeline." : "Source playback is unprocessed. Render a preview to see your complete edit.";
  }
  async function togglePlayback() {
    const player = $("video-player"); if (!player.src || $("play-pause").disabled) return;
    if (player.paused) { try { await player.play(); } catch (_) { $("media-error").hidden = false; } } else player.pause();
  }
  function sourceToTimeline(clip, sourceTime) {
    if (clip.freeze) return 0;
    const local = clamp(sourceTime - number(clip.in), 0, Math.max(0, number(clip.out) - number(clip.in)));
    if (!clip.segments?.length) return local / Math.max(.01, number(clip.speed, 1));
    let total = 0;
    for (const seg of clip.segments) { total += Math.max(0, Math.min(local, seg.end) - seg.start) / Math.max(.01, number(seg.speed, 1)); if (local <= seg.end) break; }
    return total;
  }
  function timelineToSource(clip, time) {
    if (clip.freeze) return number(clip.freeze.time);
    if (!clip.segments?.length) return number(clip.in) + time * number(clip.speed, 1);
    let remaining = time;
    for (const seg of clip.segments) { const duration = (seg.end - seg.start) / number(seg.speed, 1); if (remaining <= duration) return number(clip.in) + seg.start + remaining * seg.speed; remaining -= duration; }
    return number(clip.out);
  }
  function updatePlayhead() {
    const player = $("video-player");
    if (S.viewerMode === "render") S.playhead = number(player.currentTime);
    else if (S.selection?.type === "clips" && S.source?.id === itemFor()?.asset_id) { const layout = clipLayout().find((entry) => entry.clip.id === S.selection.id); if (layout) S.playhead = layout.start + sourceToTimeline(layout.clip, number(player.currentTime)); }
    $("timeline-playhead").hidden = !S.project?.clips?.length;
    $("timeline-playhead").style.left = `${Math.max(0, S.playhead) * S.pps + 12}px`;
  }
  async function seekTimeline(time) {
    S.playhead = clamp(time, 0, projectDuration());
    if (S.viewerMode === "render" && S.rendered) { seekWhenReady(S.playhead); updatePlayhead(); return; }
    const entries = clipLayout(); const entry = [...entries].reverse().find((item) => S.playhead >= item.start) || entries[0];
    if (entry) { const target = S.playhead; selectItem("clips", entry.clip.id, false); const a = asset(entry.clip.asset_id) || await probeAsset(entry.clip.asset_id); setSource(a, timelineToSource(entry.clip, target - entry.start)); S.playhead = target; $("timeline-playhead").style.left = `${target * S.pps + 12}px`; }
  }

  function selectItem(type, id, preview = true) {
    const item = itemFor(type, id); if (!item) return;
    S.selection = {type, id}; if (type === "clips") S.selectedClipId = id; if (type === "titles") S.selectedTitleId = id;
    renderInspector(); renderTimeline();
    const a = asset(item.asset_id);
    if (preview && a && ["clips", "audio", "overlays"].includes(type)) setSource(a, item.freeze ? number(item.freeze.time) : number(item.in));
    else if (preview && item.asset_id && !a) probeAsset(item.asset_id).then((resolved) => { if (S.selection?.id === id) setSource(resolved, number(item.in)); }).catch(report);
  }
  function renderTimeline() {
    const p = S.project; const duration = projectDuration(); const viewWidth = Math.max(200, $("timeline-scroll").clientWidth - 25); const visibleDuration = Math.max(12, duration);
    S.pps = clamp(viewWidth / visibleDuration, 2, 80) * S.zoom;
    const width = Math.max(viewWidth + 25, duration * S.pps + 100); $("timeline-surface").style.width = `${width}px`;
    $("timeline-summary").textContent = p ? `${p.clips.length} ${p.clips.length === 1 ? "clip" : "clips"} · ${fmt(duration)}` : "No project open";
    $("timeline-tip").textContent = S.selection?.type === "clips" ? "Drag clips to reorder · select a clip to trim, retime or add effects" : "One project. The same edit in your app, CLI, and MCP.";
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((value) => value * S.pps >= 65) || 600;
    let ticks = ""; const maxTime = (width - 12) / S.pps;
    for (let t = 0; t < maxTime; t += step) { ticks += `<div class="ruler-tick" style="left:${t * S.pps + 12}px"><span>${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}</span></div>`; if (step * S.pps > 85) ticks += `<div class="ruler-tick minor" style="left:${(t + step / 2) * S.pps + 12}px"></div>`; }
    ticks += (p?.markers || []).filter((m) => number(m.time) <= duration).map((m) => `<span class="timeline-marker" style="left:${number(m.time) * S.pps + 10}px" title="${escapeHTML(m.label || "Marker")} · ${fmt(m.time)}"></span>`).join("");
    $("timeline-ruler").innerHTML = ticks; $("marker-count").textContent = p?.markers?.length ? `${p.markers.length} markers` : "";
    $("video-track").innerHTML = clipLayout().map(({clip, start, duration:d, transition}) => {
      const a = asset(clip.asset_id); const w = Math.max(20, d * S.pps); const frames = a && ["image", "video"].includes(a.kind) ? Array.from({length:Math.min(8, Math.ceil(w / 79))}, () => `<img src="/api/thumbnail?id=${encodeURIComponent(a.id)}" alt="" loading="lazy">`).join("") : "";
      return `<div class="timeline-item ${S.selection?.type === "clips" && S.selection.id === clip.id ? "selected" : ""}" data-item="${escapeHTML(clip.id)}" data-type="clips" draggable="true" tabindex="0" role="button" aria-label="Select clip ${escapeHTML(a?.name || clip.id)}" style="left:${start * S.pps + 12}px;width:${w}px" title="${escapeHTML(a?.name || "Clip")} · ${seconds(d)}${clip.effects?.length ? ` · ${clip.effects.length} effects` : ""}"><div class="timeline-film">${frames}</div><div class="timeline-item-content"><span class="timeline-item-name">${escapeHTML(a?.name || "Loading source…")}</span><span class="timeline-item-meta">${seconds(d)}${clip.freeze ? '<b>FREEZE</b>' : ""}${clip.segments?.length ? '<b>RAMP</b>' : number(clip.speed, 1) !== 1 ? `<b>${clip.speed}×</b>` : ""}${clip.effects?.length ? `<b>FX ${clip.effects.length}</b>` : ""}${number(clip.volume, 1) === 0 ? '<b>MUTED</b>' : ""}</span></div>${transition ? `<span class="transition-hint" style="width:${Math.max(8, transition * S.pps)}px" title="${escapeHTML(clip.transition.name)}">${transition * S.pps > 16 ? "◇" : ""}</span>` : ""}</div>`;
    }).join("") || '<div class="track-empty">Drop footage here or use + in the media library</div>';
    for (const [type, target, className, iconName] of [["overlays", "overlay-track", "overlay-item", "layers"], ["shapes", "shape-track", "shape-item", "shape"], ["accents", "accent-track", "accent-item", "sparkles"], ["titles", "title-track", "title-item", "type"], ["audio", "audio-track", "audio-item", "music"]]) {
      $(target).innerHTML = (p?.[type] || []).map((item) => {
        const d = type === "audio" ? item.loop && item.duration ? number(item.duration) : number(item.out) - number(item.in) : number(item.duration);
        const itemWidth = Math.max(20, Math.min(Math.max(0, duration - number(item.start)), Math.max(0, d)) * S.pps);
        const label = type === "titles" ? item.text : ["shapes","accents"].includes(type) ? titleCase(item.kind) : assetName(item.asset_id);
        let waveform = "";
        const wave = type === "audio" ? S.analysis.get(item.asset_id)?.waveform : null;
        if (wave?.peaks?.length) { const values = wave.peaks.map((v) => Array.isArray(v) ? Math.max(...v.map(Math.abs)) : typeof v === "object" ? Math.max(Math.abs(v.min || 0), Math.abs(v.max || 0)) : Math.abs(number(v))); const max = Math.max(.001, ...values); const stride = Math.max(1, Math.ceil(values.length / 200)); let path = ""; for (let i = 0; i < values.length; i += stride) { const x = i / values.length * 1000; const h = values[i] / max * 11; path += `M${x.toFixed(1)},${(12-h).toFixed(1)}V${(12+h).toFixed(1)}`; } waveform = `<div class="track-waveform"><svg viewBox="0 0 1000 24" preserveAspectRatio="none"><path d="${path}"/></svg></div>`; }
        return `<div class="timeline-item ${className} ${S.selection?.type === type && S.selection.id === item.id ? "selected" : ""}" data-item="${escapeHTML(item.id)}" data-type="${type}" tabindex="0" role="button" aria-label="Select ${escapeHTML(label)}" style="left:${number(item.start) * S.pps + 12}px;width:${itemWidth}px" title="${escapeHTML(label)} · starts ${fmt(item.start)}">${waveform}<div class="timeline-item-content">${icon(iconName)}<span class="timeline-item-name">${escapeHTML(label)}</span></div></div>`;
      }).join("");
    }
    $("caption-track").innerHTML=(p?.captions||[]).map((cue)=>`<button class="timeline-item caption-item" data-caption="${escapeHTML(cue.id)}" style="left:${number(cue.start)*S.pps+12}px;width:${Math.max(5,(number(cue.end)-number(cue.start))*S.pps)}px" title="${escapeHTML(cue.text)} · ${fmt(cue.start)}"><span class="timeline-item-content"><span class="timeline-item-name">${escapeHTML(cue.text)}</span></span></button>`).join("");
    updatePlayhead();
  }

  function compatibilityText(a) {
    const ext = String(a.extension || "").toLowerCase();
    if ([".ffx","ffx",".aep","aep"].includes(ext)) return "This asset requires Adobe After Effects. It is catalogued as an external reference. Use the native Effects tab for supported montage effects.";
    if ([".setting","setting"].includes(ext)) return "This preset requires DaVinci Resolve / Fusion. It is catalogued as an external reference. You can apply native montage effects from the Effects tab.";
    if ([".py","py"].includes(ext)) return "This script is a reference asset. Framedrop does not import or execute scripts from your media folder.";
    if (a.compatibility && typeof a.compatibility === "string") return a.compatibility;
    if (a.compatibility?.message) return a.compatibility.message;
    return externalAsset(a) ? "This file is available as a reference for its original editing application. It is not a native timeline effect." : "This asset can be used directly in Framedrop.";
  }
  function renderAssetInspector(a) {
    if (!a) { $("inspector-content").innerHTML = '<p class="field-help">Select a library asset to see its details.</p>'; return; }
    $("inspector-kind").textContent = titleCase(a.kind);
    const thumbnail = ["image","video"].includes(a.kind) ? `<img src="/api/thumbnail?id=${encodeURIComponent(a.id)}" alt="">` : icon(kindIcon(a.kind));
    let actions = "";
    if (["video","image"].includes(a.kind)) actions += `<button class="button primary inspector-action" data-add-role="clips" data-asset-id="${escapeHTML(a.id)}">${icon("plus")} Add as video clip</button><button class="button secondary inspector-action" data-add-role="overlays" data-asset-id="${escapeHTML(a.id)}">${icon("layers")} Add as overlay</button>`;
    if (a.kind === "audio" || a.kind === "video" && a.metadata?.has_audio !== false) actions += `<button class="button ${a.kind === "audio" ? "primary" : "secondary"} inspector-action" data-add-role="audio" data-asset-id="${escapeHTML(a.id)}">${icon("music")} Add ${a.category === "sfx" ? "sound effect" : "audio track"}</button>`;
    if (a.kind === "image") actions += `<button class="button secondary inspector-action" data-action="remove-background">${icon("sparkles")} Remove image background</button>`;
    if (a.kind === "font") actions += `<button class="button primary inspector-action" data-action="title-with-font">${icon("type")} Add title with this font</button>${S.selectedTitleId && itemFor("titles",S.selectedTitleId) ? '<button class="button secondary inspector-action" data-action="apply-font">Apply to selected title</button>' : ""}`;
    if (a.kind === "lut") actions += `<button class="button primary inspector-action" data-action="apply-lut" ${selectedClip() ? "" : "disabled"}>${icon("layers")} Apply LUT to selected clip</button>${!selectedClip() ? '<p class="field-help">Select a timeline video clip before applying this lookup table.</p>' : ""}`;
    if (a.kind === "archive") actions += `<button class="button primary inspector-action" data-action="browse-archive">${icon("archive")} Browse archive contents</button><p class="field-help">Choose individual media files to extract. The entire archive is never extracted automatically.</p>`;
    $("inspector-content").innerHTML = `<div class="inspector-source-thumb">${thumbnail}</div><h2 class="inspector-title">${escapeHTML(a.name)}</h2><p class="inspector-subtitle">${escapeHTML(a.relative_path || a.path)}</p>${externalAsset(a) ? notice(compatibilityText(a), true) : ""}${actions}<dl class="property-list"><dt>Type</dt><dd>${escapeHTML(titleCase(a.kind))}</dd><dt>Category</dt><dd>${escapeHTML(titleCase(a.category))}</dd><dt>Size</dt><dd>${bytes(a.size)}</dd>${metadataDuration(a) ? `<dt>Duration</dt><dd>${fmt(metadataDuration(a))}</dd>` : ""}${a.metadata?.width ? `<dt>Resolution</dt><dd>${a.metadata.width} × ${a.metadata.height}</dd>` : ""}${a.metadata?.fps ? `<dt>Frame rate</dt><dd>${round(a.metadata.fps,2)} fps</dd>` : ""}${a.metadata?.video_codec ? `<dt>Video codec</dt><dd>${escapeHTML(a.metadata.video_codec)}</dd>` : ""}${a.metadata?.audio_codec ? `<dt>Audio codec</dt><dd>${escapeHTML(a.metadata.audio_codec)}</dd>` : ""}</dl>${["image","video","audio"].includes(a.kind) ? notice("The viewer plays the original source. Effects and overlays appear in rendered previews.") : ""}`;
  }
  function setNested(obj, path, value) { const keys = path.split("."); let target = obj; for (const key of keys.slice(0,-1)) { target[key] ||= {}; target = target[key]; } target[keys.at(-1)] = value; }
  function handleInspectorChange(event) {
    if (event.target.id === "shape-selection") { selectItem("shapes",event.target.value); return; }
    const control = event.target.closest("[data-field]"); if (!control || !S.project) return;
    const key = control.dataset.field; let value = control.type === "checkbox" ? control.checked : ["number","range"].includes(control.type) ? control.valueAsNumber : control.value;
    if (["number","range"].includes(control.type) && (!Number.isFinite(value) || !control.checkValidity())) { toast("Enter a value inside the shown range.", "error"); renderInspector(); return; }
    if (key === "canvas.fps") value = number(value,30);
    if (key === "transform.rotation") value = number(value,0);
    if (key.endsWith("font_asset_id") && !value) value = null;
    if (key === "name") { value = String(value).trim(); if (!value) { toast("Give the project a name."); renderInspector(); return; } }
    const target = ["project","captions"].includes(S.selection?.type) ? S.project : itemFor(); if (!target) return;
    const keyed = /^(motion|volume_keyframes)\.(\d+)\.time$/.exec(key);
    if (keyed && target[keyed[1]]?.some((frame, index) => index !== Number(keyed[2]) && Math.abs(frame.time - value) < .000001)) { toast("Keyframes need distinct times.", "error"); renderInspector(); return; }
    const windowKey = /^effects\.(\d+)\.(start|end)$/.exec(key);
    if (windowKey) {
      const effect = target.effects[Number(windowKey[1])];
      if (windowKey[2] === "start" && value >= (effect.end ?? clipDuration(target)) || windowKey[2] === "end" && value <= (effect.start ?? 0)) { toast("Effect end must follow its start.", "error"); renderInspector(); return; }
    }
    if (key === "out" && value <= number(target.in)) { toast("Source out must come after source in.", "error"); renderInspector(); return; }
    if (key === "in" && target.out !== undefined && value >= number(target.out)) { toast("Source in must come before source out.", "error"); renderInspector(); return; }
    mutate(() => {
      setNested(target, key, value);
      if (keyed) target[keyed[1]].sort((a, b) => a.time - b.time);
      if (S.selection?.type === "clips" && ["in","out","speed"].includes(key)) {target.segments = [];if(target.fade_in)target.fade_in=Math.min(target.fade_in,clipDuration(target));if(target.fade_out)target.fade_out=Math.min(target.fade_out,clipDuration(target));}
      if (S.selection?.type === "clips" && ["in","out","speed","freeze.duration"].includes(key)) trimTimedProperties(target,clipDuration(target));
      if (key === "caption_style.preset" && value === "neon") Object.assign(target.caption_style,{glow:.7,glow_color:"#ff62c6",animation:"pop",color:"#ffffff",outline_color:"#ff62c6",outline:1});
      if (key === "transition.name") target.transition.duration = value === "cut" ? 0 : target.transition.duration || .3;
      if (key === "loop" && value && S.selection?.type === "audio") target.duration ||= Math.max(.1,projectDuration()-number(target.start));
    });
    if (key === "name") { const summary = S.projects.find((p)=>p.id===S.project.id); if (summary) summary.name = value; renderProjectOptions(); }
  }
  function removeItem() {
    const selection = S.selection; if (!selection || !["clips","audio","overlays","titles","shapes","accents"].includes(selection.type)) return;
    mutate((p) => { p[selection.type] = p[selection.type].filter((item)=>item.id!==selection.id); S.selection={type:"project"}; });
  }
  function moveClip(direction) {
    const clip = itemFor(); if (!clip || S.selection.type !== "clips") return;
    const index = S.project.clips.findIndex((c)=>c.id===clip.id); const target = index + direction; if (target < 0 || target >= S.project.clips.length) return;
    mutate((p) => { p.clips.splice(index,1); p.clips.splice(target,0,clip); });
  }
  async function analyzeAudio() {
    const item = itemFor(); if (!item || S.selection.type !== "audio") return;
    const button = $("inspector-content").querySelector('[data-action="analyze-audio"]'); button.disabled = true; button.textContent = "Analyzing source audio…";
    const analysisStart = number(item.in); const analysisDuration = Math.min(120,Math.max(.1,number(item.out)-analysisStart));
    try {
      const [beats, waveform] = await Promise.all([call("analyze_media", {asset_id:item.asset_id,mode:"beats",start:analysisStart,duration:analysisDuration}), call("analyze_media", {asset_id:item.asset_id,mode:"waveform",start:analysisStart,duration:analysisDuration})]);
      S.analysis.set(item.asset_id,{beats,waveform,start:analysisStart}); renderInspector(); renderTimeline(); toast(`Audio analysis complete: ${beats.beats?.length || 0} candidate beats.`, "success");
    } finally { if (button.isConnected) { button.disabled = false; button.innerHTML = `${icon("wave")} Analyze beats + waveform`; } }
  }
  async function inspectorAction(action) {
    const item = itemFor();
    if (action === "freeze-frame") return freezeDialog();
    if (action === "clear-freeze") return mutate(() => { delete item.freeze; trimTimedProperties(item,clipDuration(item)); });
    if (action === "mute-source") return mutate(() => { item.volume = number(item.volume, 1) === 0 ? 1 : 0; });
    if (action === "motion-push") return mutate(() => { item.motion = [{time:0,zoom:1,x:.5,y:.5,easing:"ease_in_out"},{time:round(clipDuration(item)),zoom:1.2,x:.5,y:.5}]; });
    if (action === "audio-duck") {
      const duration = itemDuration(item, S.selection.type), local = localPlayhead(item, S.selection.type);
      const at = clamp(local || duration / 2, .02, duration);
      return mutate(() => { item.volume_keyframes = [{time:0,volume:1},{time:round(Math.max(.001, at - .01),6),volume:1},{time:round(at,6),volume:0}]; });
    }
    if (action === "align-to-playhead") return mutate(() => { item.start = round(S.playhead); });
    if (action === "remove-background") return removeBackground(S.selection.id);
    if (action === "new-project") return newProjectDialog();
    if (action === "ai-interface") return aiDialog();
    if (action === "browse-effects") return showLibrary("effects");
    if (action === "remove-item") return removeItem();
    if (action === "move-left") return moveClip(-1);
    if (action === "move-right") return moveClip(1);
    if (action === "analyze-audio") return analyzeAudio();
    if (action === "refresh-project") { if (S.dirty && !window.confirm("Discard unsaved changes and load the latest saved version?")) return; await switchProject(S.project.id,true); toast("Loaded the latest saved revision.","success"); return; }
    if (action === "validate") {
      await ensureSaved(); const result = await call("project_validate", {project_id:S.project.id});
      dialog(result.valid ? "Timeline is ready to render" : "Timeline needs attention", `<p>Duration: ${fmt(result.duration)}.</p>${(result.errors || []).map((e)=>`<div class="dialog-error">${escapeHTML(e)}</div>`).join("")}${(result.warnings || []).map((w)=>notice(w,true)).join("")}${result.valid && !result.warnings?.length ? '<p>All referenced assets and timeline settings passed the render engine’s validation.</p>' : ""}`, '<button class="button primary" data-close>Done</button>'); return;
    }
    if (action === "set-in" || action === "set-out") {
      if (!item || S.selection.type !== "clips" || S.viewerMode !== "source" || S.source?.id !== item.asset_id || S.source.kind === "image") { toast("Play or seek this video’s source first."); return; }
      const time = round($("video-player").currentTime); if (action === "set-in" && time >= item.out || action === "set-out" && time <= item.in) throw new Error("In must come before out. Seek to a valid position in the source.");
      mutate(()=>{ item[action === "set-in" ? "in" : "out"] = time; item.segments=[]; }); return;
    }
    if (action === "constant-speed") return mutate(()=>{item.segments=[];});
    if (action === "velocity-ramp") {
      if (item.freeze) throw new Error("Restore motion before adding a velocity ramp.");
      const length = number(item.out)-number(item.in); const first=round(length/3,6), second=round(length*2/3,6);
      if (length < .15) throw new Error("Use a longer source trim for a velocity ramp.");
      return mutate(()=>{ item.segments=[{start:0,end:first,speed:2},{start:first,end:second,speed:.5},{start:second,end:round(length,6),speed:2}]; });
    }
    if (action === "remove-lut") return mutate(()=>{delete item.lut_asset_id;});
    if (action === "apply-lut") { const clip=selectedClip(); if (!clip) throw new Error("Select a video clip first."); const id=S.selection.id; mutate(()=>{clip.lut_asset_id=id;S.selection={type:"clips",id:clip.id};}); toast("Lookup table applied. Render a preview to see its color grade.","success"); return; }
    if (action === "title-with-font") return titleDialog(S.selection.id);
    if (action === "apply-font") { const title=itemFor("titles",S.selectedTitleId); const id=S.selection.id; if(title) mutate(()=>{title.font_asset_id=id;S.selection={type:"titles",id:title.id};}); return; }
    if (action === "browse-archive") return archiveDialog(S.selection.id);
    if (action === "add-beat-markers") {
      const analysis=S.analysis.get(item.asset_id); if (!analysis?.beats?.beats?.length) throw new Error("No beats were detected in this source segment.");
      const markers=analysis.beats.beats.map((t,i)=>({time:round(number(item.start)+number(t)+analysis.start-number(item.in)),label:`Beat ${i+1}`})).filter((m)=>m.time>=0&&m.time<=projectDuration());
      mutate((p)=>{p.markers=(p.markers||[]).concat(markers).sort((a,b)=>a.time-b.time);}); toast(`Added ${markers.length} beat markers within the video timeline.`,"success");
    }
  }

  function itemDuration(item, type) {
    return type === "clips" ? clipDuration(item) : item.loop && item.duration ? number(item.duration) : number(item.out) - number(item.in);
  }
  function shapePreview(shape) {
    const width = 240, height = width * S.project.canvas.height / S.project.canvas.width;
    const x1 = number(shape.x) * width, y1 = number(shape.y) * height, x2 = number(shape.x2) * width, y2 = number(shape.y2) * height;
    const color = /^#[0-9a-f]{6}$/i.test(shape.color) ? shape.color : "#ff3030";
    const stroke = clamp(number(shape.stroke_width,12) * width / S.project.canvas.width,1,16);
    const mark = shape.kind === "arrow" ? `<path d="M${x1} ${y1}L${x2} ${y2}" marker-end="url(#shape-tip)"/>` : shape.kind === "ellipse" ? `<ellipse cx="${(x1+x2)/2}" cy="${(y1+y2)/2}" rx="${Math.abs(x2-x1)/2}" ry="${Math.abs(y2-y1)/2}"/>` : `<rect x="${Math.min(x1,x2)}" y="${Math.min(y1,y2)}" width="${Math.abs(x2-x1)}" height="${Math.abs(y2-y1)}"/>`;
    return `<div class="shape-preview"><svg role="img" aria-label="Shape placement preview" viewBox="0 0 ${width} ${height}"><defs><marker id="shape-tip" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0 0L8 4L0 8Z" fill="${color}"/></marker></defs><g fill="none" stroke="${color}" stroke-width="${stroke}" opacity="${clamp(number(shape.opacity,1),0,1)}">${mark}</g></svg><span>Canvas placement</span></div>`;
  }
  function localPlayhead(item, type) {
    const start = type === "clips" ? clipLayout().find((entry) => entry.clip.id === item.id)?.start || 0 : number(item.start);
    return clamp(S.playhead - start, 0, itemDuration(item, type));
  }
  function keyframeEditor(item, type, key) {
    const motion = key === "motion", duration = itemDuration(item, type), frames = item[key] || [];
    return `<p class="field-help">Times are seconds from this ${type === "clips" ? "clip" : "audio item"}’s start. Easing controls the interval after each keyframe.${motion ? " Zoom and crop anchors replace the static crop while animated." : " Levels multiply the main volume."}</p><div class="keyframe-list">${frames.map((frame, index) => `<div class="keyframe-row"><div class="keyframe-heading"><span>Keyframe ${index + 1}</span><button class="icon-button small" data-remove-keyframe="${key}" data-index="${index}" aria-label="Remove keyframe ${index + 1}">${icon("x")}</button></div><div class="field-row">${field("Time (s)",`${key}.${index}.time`,frame.time,{min:0,max:round(duration,6),step:.001})}${motion ? field("Zoom",`${key}.${index}.zoom`,frame.zoom,{min:1,max:4,step:.01}) : field("Level",`${key}.${index}.volume`,frame.volume,{min:0,max:4,step:.01})}</div>${selectField("Easing to next key",`${key}.${index}.easing`,frame.easing||"linear",[["linear","Linear"],["ease_in","Ease in"],["ease_out","Ease out"],["ease_in_out","Ease in / out"]])}${motion ? `<div class="field-row">${field("X anchor",`${key}.${index}.x`,frame.x,{min:0,max:1,step:.01})}${field("Y anchor",`${key}.${index}.y`,frame.y,{min:0,max:1,step:.01})}</div>` : ""}</div>`).join("")}</div><div class="inline-buttons"><button class="button secondary" data-add-keyframe="${key}">${icon("plus")} Keyframe</button><button class="button quiet" data-action="${motion ? "motion-push" : "audio-duck"}">${motion ? "Slow push" : "Mute after playhead"}</button></div>`;
  }
  function trimTimedProperties(clip, duration) {
    for (const key of ["motion", "volume_keyframes"]) if (clip[key]) clip[key] = clip[key].filter((frame) => frame.time <= duration);
    clip.effects = (clip.effects || []).filter((effect) => (effect.start ?? 0) < duration).map((effect) => ({...effect, ...(effect.end != null ? {end:Math.min(effect.end, duration)} : {})}));
    if (clip.fade_in) clip.fade_in = Math.min(clip.fade_in, duration);
    if (clip.fade_out) clip.fade_out = Math.min(clip.fade_out, duration);
  }
  function freezeDialog() {
    const clip = itemFor(); if (S.selection?.type !== "clips" || !clip || asset(clip.asset_id)?.kind !== "video") return;
    if (clip.segments?.length) throw new Error("Use constant speed before inserting a freeze.");
    const current = S.viewerMode === "source" && S.source?.id === clip.asset_id ? $("video-player").currentTime : number(clip.in);
    const latest = Math.max(number(clip.in), number(clip.out) - 1 / S.project.canvas.fps);
    const frame = clamp(current, number(clip.in), latest);
    dialog("Freeze the moment", `<p>Keep this clip’s footage before the chosen frame, then replace its remaining footage with a hold. Other timeline items keep their current start times.</p><form id="freeze-form"><div class="field-row"><div class="field"><label for="freeze-time">Source frame time (s)</label><input id="freeze-time" type="number" min="${clip.in}" max="${latest}" step="any" value="${round(frame,6)}" required></div><div class="field"><label for="freeze-duration">Hold duration (s)</label><input id="freeze-duration" type="number" min="0.1" max="300" step="0.1" value="3" required></div></div><p class="field-help">The hold has no original clip audio. Add an alarm or other sound on the Audio track.</p><label class="checkbox-field"><input id="freeze-dark" type="checkbox" checked> Darken the frozen frame</label></form>`, '<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="freeze-form">Insert freeze</button>');
    $("freeze-form").onsubmit = (event) => {
      event.preventDefault();
      const time = number($("freeze-time").value), duration = number($("freeze-duration").value), dark = $("freeze-dark").checked;
      const held = clone(clip); held.id = uid(); held.in = time; held.freeze = {time, duration}; held.segments = []; held.speed = 1; held.motion = []; held.volume_keyframes = []; held.effects = (held.effects || []).filter((effect) => effect.start == null && effect.end == null); held.fade_in = 0; held.fade_out = 0;
      held.volume = 0;
      if (dark) held.color = {...held.color, brightness:Math.max(-.5, number(held.color?.brightness) - .23)};
      mutate((p) => {
        const index = p.clips.findIndex((entry) => entry.id === clip.id);
        if (time - number(clip.in) >= 1 / p.canvas.fps) {
          clip.out = time; clip.transition = {name:"cut",duration:0}; trimTimedProperties(clip, clipDuration(clip)); p.clips.splice(index + 1, 0, held);
        } else p.clips.splice(index, 1, held);
      });
      closeDialog(); selectItem("clips", held.id); S.playhead = clipLayout().find((entry) => entry.clip.id === held.id).start;
      toast("Freeze inserted. Add your alarm and shapes at the hold’s start, then render a preview.", "success");
    };
  }
  async function shapeDialog() {
    await ensureProject(); if (!S.project.clips.length) throw new Error("Add footage before placing a shape.");
    const start = round(clamp(S.playhead,0,Math.max(0,projectDuration()-.1)));
    dialog("Point out the moment", `<p>Add an arrow, circle or box. Refine its position and timing in the inspector.</p><form id="shape-form"><div class="field"><label for="shape-kind">Shape</label><select id="shape-kind"><option value="arrow">Pointing arrow</option><option value="ellipse">Circle / ellipse</option><option value="rectangle">Rectangle</option></select></div><div class="field-row"><div class="field"><label for="shape-start">Start (s)</label><input id="shape-start" type="number" min="0" max="${projectDuration()}" step="0.01" value="${start}" required></div><div class="field"><label for="shape-duration">Duration (s)</label><input id="shape-duration" type="number" min="0.05" max="86400" step="0.01" value="${round(Math.min(3,projectDuration()-start))}" required></div></div></form>`, '<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="shape-form">Add shape</button>');
    $("shape-form").onsubmit = (event) => {
      event.preventDefault(); const start = number($("shape-start").value), duration = number($("shape-duration").value);
      if (start + duration > projectDuration() + .001) { dialogError(new Error("Keep the shape inside the video timeline.")); return; }
      const id = uid(), kind = $("shape-kind").value;
      mutate((p) => { p.shapes ||= []; p.shapes.push({id,kind,start,duration,x:kind === "arrow" ? .2 : .35,y:kind === "arrow" ? .2 : .35,x2:kind === "arrow" ? .5 : .65,y2:kind === "arrow" ? .5 : .65,color:"#ff3030",stroke_width:12,opacity:1}); });
      closeDialog(); selectItem("shapes",id);
    };
  }
  function importMediaDialog() {
    dialog("Import local media", '<p>Paste a full file path. Framedrop copies the file into its managed media folder so your project can keep using it.</p><form id="import-form"><div class="field"><label for="import-path">Local file path</label><input id="import-path" type="text" placeholder="/home/you/Downloads/clip.mp4" required autocomplete="off"></div></form>', '<button class="button secondary" data-close>Cancel</button><button class="button primary" id="import-submit" type="submit" form="import-form">Import</button>');
    $("import-form").onsubmit = async (event) => {
      event.preventDefault(); $("import-submit").disabled = true;
      try { const a = await call("asset_import", {path:$("import-path").value.trim()}); rememberAssets([a]); closeDialog(); await loadAssets(); await selectAsset(a.id); toast(`Imported ${a.name}.`, "success"); }
      catch (error) { dialogError(error); } finally { if ($("import-submit")) $("import-submit").disabled = false; }
    }; $("import-path").focus();
  }
  async function removeBackground(id) {
    const status = await call("background_removal_status");
    if (!status.installed || !status.model_ready) throw new Error("Background removal needs its local model installed. Run python3 setup_background.py --python python3.12, then try again.");
    S.job = await call("image_background_remove", {asset_id:id}); renderJob(S.job); pollJob();
    toast("Removing the image background locally. You can keep editing while it runs.");
  }

  function dialog(title, body, footer = '<button class="button secondary" data-close>Close</button>') {
    $("dialog-content").innerHTML = `<div class="dialog-head"><h2>${escapeHTML(title)}</h2><button class="icon-button" data-close aria-label="Close dialog">${icon("x")}</button></div><div class="dialog-body">${body}</div><div class="dialog-foot">${footer}</div>`;
    if (!$("main-dialog").open) $("main-dialog").showModal();
    $("dialog-content").querySelectorAll("[data-close]").forEach((button)=>button.onclick=closeDialog);
  }
  function closeDialog() { $("main-dialog").close(); }
  function dialogError(error) {
    const body=$("dialog-content").querySelector(".dialog-body"); body.querySelector(".dialog-error")?.remove();
    const el=document.createElement("div"); el.className="dialog-error"; el.textContent=error.message || String(error); body.append(el);
  }
  function newProjectDialog() {
    dialog("A new timeline", `<p>Choose a name and canvas. You can change these later.</p><form id="new-project-form"><div class="field"><label for="np-name">Project name</label><input id="np-name" required maxlength="120" placeholder="Friday night highlights" autocomplete="off"></div><div class="field-row"><div class="field"><label for="np-canvas">Canvas</label><select id="np-canvas"><option value="1920,1080">Landscape · 1920 × 1080</option><option value="1080,1920">Portrait · 1080 × 1920</option><option value="1080,1080">Square · 1080 × 1080</option></select></div><div class="field"><label for="np-fps">Frame rate</label><select id="np-fps"><option>24</option><option selected>30</option><option>60</option></select></div></div></form>`, '<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="new-project-form" id="np-submit">Create project</button>');
    $("new-project-form").onsubmit=async(event)=>{
      event.preventDefault(); if(S.dirty&&!window.confirm("Discard unsaved changes and create this new project?")) return;
      const name=$("np-name").value.trim(); if(!name)return; $("np-submit").disabled=true;
      try { const [width,height]=$("np-canvas").value.split(",").map(Number); const result=await call("project_create",{name,width,height,fps:number($("np-fps").value,30)}); closeDialog();setProject(result);toast("Project created. Add your first clip from the library.","success"); }
      catch(error){dialogError(error);}finally{if($("np-submit"))$("np-submit").disabled=false;}
    };
    $("np-name").focus();
  }
  function textMotionFields(item, prefix="") {
    return `${selectField("Animation",prefix+"animation",item.animation||"none",[["none","None"],["fade","Soft fade"],["pop","Smooth pop"],["slide_up","Slide up"]])}${field("Entry time (s)",prefix+"animation_duration",item.animation_duration??.16,{min:.01,max:2,step:.01})}${rangeField("Neon glow",prefix+"glow",item.glow??(item.preset==="neon"?.7:0))}${field("Glow color",prefix+"glow_color",item.glow_color||"#ff62c6",{type:"color"})}<p class="field-help">Animation begins at each cue’s exact start. Use separate cues for separately spoken words. Animated titles use center coordinates; turn off the box for clear neon lettering.</p>`;
  }
  async function accentDialog() {
    await ensureProject();
    const id=uid();
    mutate((p)=>{p.accents||=[];p.accents.push({id,kind:"impact_ring",start:round(S.playhead,3),duration:.4,size:.25,x:.5,y:.5,color:"#ff62c6",opacity:.8,rotation:0});});
    selectItem("accents",id);toast("Accent added at the playhead. Choose its shape and timing in the inspector.");
  }
  async function titleDialog(fontId = null) {
    await ensureProject();
    dialog("Add a title", `<p>Add text to your montage, then refine its timing and style in the inspector.</p><form id="title-form"><div class="field"><label for="new-title-text">Title text</label><textarea id="new-title-text" required maxlength="2000" placeholder="Your moment. Your words."></textarea></div><div class="field-row"><div class="field"><label for="new-title-start">Start (s)</label><input id="new-title-start" type="number" min="0" step="0.01" value="${round(S.playhead)}"></div><div class="field"><label for="new-title-duration">Duration (s)</label><input id="new-title-duration" type="number" min="0.1" max="86400" step="0.1" value="2"></div></div><div class="field"><label for="new-title-font">Font</label><select id="new-title-font">${option("","System default",fontId||"")}${S.fonts.map((f)=>option(f.id,f.name,fontId)).join("")}${fontId&&!S.fonts.some((f)=>f.id===fontId)?option(fontId,assetName(fontId),fontId):""}</select></div></form>`, '<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="title-form">Add title</button>');
    $("title-form").onsubmit=(event)=>{
      event.preventDefault();const text=$("new-title-text").value.trim();if(!text)return;
      const id=uid();const title={id,text,start:number($("new-title-start").value),duration:number($("new-title-duration").value,2),font_asset_id:$("new-title-font").value||null,font_size:64,x:.5,y:.8,color:"#ffffff",box:true,fade:.15};
      mutate((p)=>p.titles.push(title));closeDialog();selectItem("titles",id);toast("Title added. Render a preview to see it on the video.","success");
    };$("new-title-text").focus();
  }
  async function autoMontageDialog() {
    dialog("Build a beat-grid montage", '<p>Loading available footage and music…</p>');
    const [videos,audios]=await Promise.all([call("assets_list",{kind:"video",limit:200}),call("assets_list",{kind:"audio",limit:200})]);rememberAssets(videos.items);rememberAssets(audios.items);
    if(!$("main-dialog").open)return;
    const previous=new Set(S.project?.clips.map((c)=>c.asset_id)||[]);
    dialog("Build a beat-grid montage", `<p>Choose footage and a tempo. Clips are cut to an explicit beat grid; choose music that matches the BPM, or measure it in the audio inspector first.</p><form id="auto-form"><div class="field"><label for="auto-name">Project name</label><input id="auto-name" required maxlength="120" placeholder="My montage"></div><p class="dialog-section-label">Footage · selected in library order</p><div class="asset-choices">${(videos.items||[]).map((a)=>`<label class="asset-choice"><input type="checkbox" name="auto-video" value="${escapeHTML(a.id)}" ${previous.has(a.id)?"checked":""}>${icon("film")}<span>${escapeHTML(a.name)}</span></label>`).join("")||'<p class="dialog-note" style="padding:10px">No video footage found. Add video files to the Editing folder and rescan.</p>'}</div>${videos.total>200?'<p class="dialog-note">Showing the first 200 video assets. Use the CLI or MCP for a larger source selection.</p>':""}<div class="field" style="margin-top:14px"><label for="auto-music">Music (optional)</label><select id="auto-music"><option value="">No music track</option>${(audios.items||[]).map((a)=>option(a.id,a.name,"")).join("")}</select></div><div class="field-row triple"><div class="field"><label for="auto-bpm">BPM</label><input id="auto-bpm" type="number" min="30" max="300" step="0.1" value="120" required></div><div class="field"><label for="auto-duration">Length (s)</label><input id="auto-duration" type="number" min="2" max="300" step="0.1" value="16" required></div><div class="field"><label for="auto-cuts">Beats per cut</label><select id="auto-cuts"><option>1</option><option>2</option><option selected>4</option><option>8</option></select></div></div><div class="field-row"><div class="field"><label for="auto-style">Style</label><select id="auto-style"><option value="clean">Clean cuts</option><option value="impact">Impact</option><option value="cinematic">Cinematic</option></select></div><div class="field"><label for="auto-offset">Beat offset (s)</label><input id="auto-offset" type="number" min="0" max="60" step="0.01" value="0"></div></div></form>`, '<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="auto-form" id="auto-submit">Build montage</button>');
    $("auto-form").onsubmit=async(event)=>{
      event.preventDefault();const ids=[...$("auto-form").querySelectorAll('[name="auto-video"]:checked')].map((el)=>el.value);if(!ids.length){dialogError(new Error("Select at least one video source."));return;}
      if(S.dirty&&!window.confirm("Discard the current unsaved draft and build a new montage?"))return;
      $("auto-submit").disabled=true;$("auto-submit").textContent="Building…";
      try{const args={name:$("auto-name").value.trim(),asset_ids:ids,bpm:number($("auto-bpm").value),duration:number($("auto-duration").value),beats_per_cut:number($("auto-cuts").value),beat_offset:number($("auto-offset").value),style:$("auto-style").value,width:S.project?.canvas.width||1920,height:S.project?.canvas.height||1080,fps:S.project?.canvas.fps||30};if($("auto-music").value)args.music_asset_id=$("auto-music").value;const result=await call("montage_create",args);closeDialog();setProject(result);toast("Montage assembled. Inspect your cuts and render a preview.","success");}
      catch(error){dialogError(error);}finally{if($("auto-submit")){$("auto-submit").disabled=false;$("auto-submit").textContent="Build montage";}}
    };
  }
  async function archiveDialog(assetId) {
    const a=asset(assetId);let entries=[];let total=0;const chosen=new Set();
    dialog(`Archive · ${a?.name||"Contents"}`, '<p>Reading the archive index…</p>');
    const load=async()=>{const result=await call("archive_list",{asset_id:assetId,limit:200,offset:entries.length});entries=entries.concat(result.entries||[]);total=result.total||entries.length;draw();};
    function draw(){
      if(!$("main-dialog").open)return;
      dialog(`Archive · ${a?.name||"Contents"}`, `<p>Select individual media files to extract into the managed media workspace. External application presets remain reference assets.</p><div class="archive-list">${entries.map((e,index)=>{const supported=/\.(mp4|mov|mkv|avi|webm|m4v|mp3|wav|ogg|flac|aac|m4a|png|jpe?g|webp|bmp|gif|ttf|otf|cube|3dl|csp)$/i.test(e.name);return `<label class="archive-entry ${supported?"":"unsupported"}"><input type="checkbox" data-entry="${index}" ${chosen.has(e.name)?"checked":""} ${supported?"":"disabled"}><span>${escapeHTML(e.name)}</span><small>${bytes(e.size)}</small></label>`;}).join("")||'<p class="dialog-note" style="padding:12px">This archive has no visible files.</p>'}</div><p class="dialog-note">Showing ${entries.length} of ${total} entries.</p>${entries.length<total?'<button class="button secondary" id="archive-more">Load more entries</button>':""}`, '<button class="button secondary" data-close>Cancel</button><button class="button primary" id="archive-extract">Extract selected</button>');
      const update=()=>{$("archive-extract").disabled=!chosen.size;$("archive-extract").textContent=`Extract selected (${chosen.size})`;};update();
      $("dialog-content").querySelectorAll("[data-entry]").forEach((el)=>el.onchange=()=>{const name=entries[number(el.dataset.entry)].name;if(el.checked)chosen.add(name);else chosen.delete(name);update();});
      if($("archive-more"))$("archive-more").onclick=async()=>{try{$("archive-more").disabled=true;await load();}catch(error){dialogError(error);if($("archive-more"))$("archive-more").disabled=false;}};
      $("archive-extract").onclick=async()=>{if(!chosen.size)return;$("archive-extract").disabled=true;$("archive-extract").textContent="Extracting…";try{const result=await call("archive_extract",{asset_id:assetId,members:[...chosen]});rememberAssets(result.assets);closeDialog();toast(`Extracted ${result.assets?.length||chosen.size} media files.`,"success");await loadAssets();await loadFonts();}catch(error){dialogError(error);update();}};
    }
    try{await load();}catch(error){dialogError(error);}
  }
  function aiDialog() {
    const projectId=S.project?.id;const show=projectId?`framedrop project show ${projectId}`:"framedrop call project_list --json '{}'";
    const render=projectId?`framedrop render ${projectId} --quality preview --wait`:"framedrop call effects_list --json '{}'";
    const payload={tool:"project_edit",arguments:{project_id:projectId||"PROJECT_ID",expected_revision:S.project?.revision??0,operations:[{op:"set_canvas",canvas:{width:1080,height:1920,fps:30}}]}};
    dialog("One timeline. Three ways to edit.", `<p>This app, the local CLI and MCP use the same saved projects. Save browser changes before handing the timeline to an AI tool, then load the latest saved revision to see its work.</p><div class="code-heading"><span>Ubuntu terminal</span><button class="text-button" data-copy="cli">Copy</button></div><pre id="ai-cli">${escapeHTML(`${show}\n${render}\nframedrop ui\nframedrop mcp`)}</pre><div class="code-heading"><span>MCP / service operation</span><button class="text-button" data-copy="mcp">Copy</button></div><pre id="ai-mcp">${escapeHTML(JSON.stringify(payload,null,2))}</pre><p class="dialog-note">Useful tools: asset_import, assets_list, asset_probe, effects_list, project_edit, image_background_remove, captions_transcribe, render_start, job_status. Revision checks keep concurrent edits from silently overwriting each other.</p>`, '<button class="button primary" data-close>Done</button>');
    $("dialog-content").querySelectorAll("[data-copy]").forEach((button)=>button.onclick=run(async()=>{await navigator.clipboard.writeText($(`ai-${button.dataset.copy}`).textContent);button.textContent="Copied";setTimeout(()=>{if(button.isConnected)button.textContent="Copy";},1800);}));
  }

  function renderJob(job) {
    if(!job||job.kind!=="background_removal"&&job.project_id!==S.project?.id){$("render-banner").hidden=true;syncHeader();return;}
    $("render-banner").hidden=false;$("render-banner").className=`render-banner ${job.status}`;
    const active=["queued","running"].includes(job.status);const completed=job.status==="completed";const failed=job.status==="failed";const transcription=job.kind==="transcription";const cutout=job.kind==="background_removal";
    $("render-heading").textContent=cutout?(completed?"Transparent image ready":failed?"Background removal failed":job.status==="cancelled"?"Background removal cancelled":"Removing image background"):transcription?(completed?"Caption draft ready":failed?"Transcription failed":job.status==="cancelled"?"Transcription cancelled":"Transcribing locally"):completed?`${job.quality==="final"?"Export":"Preview"} ready`:failed?"Render failed":job.status==="cancelled"?"Render cancelled":`${job.status==="queued"?"Queued":"Rendering"} ${job.quality==="final"?"export":"preview"}`;
    $("render-percent").textContent=completed?"100%":active?`${Math.round(clamp(number(job.progress),0,1)*100)}%`:"";
    $("render-progress-fill").style.width=`${completed?100:clamp(number(job.progress),0,1)*100}%`;
    $("render-message").textContent=job.error||job.message||(completed?"Your MP4 is ready to play and download.":"");
    $("render-message").title=job.error||job.message||"";
    $("cancel-render").hidden=!active;$("cancel-render").disabled=false;
    $("download-render").hidden=!completed||transcription||cutout;
    $("review-cutout").hidden=!completed||!cutout||!job.result?.asset?.id;
    $("review-caption-draft").hidden=!completed||!transcription;
    if(completed&&!transcription&&!cutout){$("download-render").href=`/api/output?job=${encodeURIComponent(job.id)}`;$("download-render").download=`${(job.project_name||"montage").replace(/[^a-zA-Z0-9_-]/g,"-")}-${job.quality}.mp4`;}
    syncHeader();
  }
  async function startRender(quality) {
    if(!S.project?.clips.length)throw new Error("Add at least one video clip before rendering.");
    await ensureSaved();const job=await call("render_start",{project_id:S.project.id,quality});S.job=job;renderJob(job);pollJob();toast(`${quality==="final"?"Export":"Preview render"} started. You can keep editing while it runs.`,"info",3500);
  }
  function pollJob() {
    clearTimeout(S.pollTimer);const id=S.job?.id;if(!id)return;
    const poll=async()=>{
      try{const job=await call("job_status",{job_id:id});if(S.job?.id!==id)return;const oldStatus=S.job.status;S.job=job;renderJob(job);
        if(["queued","running"].includes(job.status)){S.pollTimer=setTimeout(poll,1200);return;}
        if(job.status==="completed"&&job.kind==="background_removal") { if(job.result?.asset)rememberAssets([job.result.asset]);if(oldStatus!=="completed"){await loadAssets();toast("Transparent image ready. Use View cutout to inspect or add it as an overlay.","success");} }
        else if(job.status==="completed"&&job.project_id===S.project?.id){if(job.kind==="transcription"){if(oldStatus!=="completed")toast("Your caption draft is ready to review.","success");}else{S.rendered=job;$("view-render").disabled=false;showRendered(job);if(oldStatus!=="completed")toast(`${job.quality==="final"?"Export":"Preview"} is ready.`,"success");}}
        else if(job.status==="failed"&&oldStatus!=="failed")toast(`${job.kind==="transcription"?"Transcription":job.kind==="background_removal"?"Background removal":"Render"} failed: ${String(job.error||job.message||"Unknown error").slice(0,600)}`,"error",15000);
      }catch(error){report(error);S.pollTimer=setTimeout(poll,4500);}
    };S.pollTimer=setTimeout(poll,500);
  }
  async function loadProjectJobs() {
    const projectId=S.project?.id;if(!projectId)return;const result=await call("jobs_list");if(S.project?.id!==projectId)return;
    const jobs=(result.jobs||[]).filter((j)=>j.project_id===projectId).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
    const active=(result.jobs||[]).find((j)=>["queued","running"].includes(j.status));
    S.rendered=jobs.find((j)=>j.status==="completed"&&j.kind!=="transcription"&&["preview","final"].includes(j.quality))||null;$("view-render").disabled=!S.rendered;
    if(active){S.job=active;renderJob(active);pollJob();}else if(jobs[0]){S.job=jobs[0];renderJob(jobs[0]);}else{$("render-banner").hidden=true;S.job=null;syncHeader();}
  }

  async function loadFonts() { const result=await call("assets_list",{kind:"font",limit:200});S.fonts=result.items||[];rememberAssets(S.fonts);if(["titles","captions"].includes(S.selection?.type))renderInspector(); }
  function moreLibraryDialog() {
    const kinds=[["preset","Application presets"],["project","Editing projects"],["archive","Archives"],["lut","Color lookup tables"],["recipe","Recipes"],["reference","Other references"]];
    dialog("More from your library", `<p>Browse effect packs and files for their original editing applications.</p><div class="preset-grid">${kinds.map(([kind,label])=>`<button class="button secondary" data-kind="${kind}" style="white-space:normal;min-height:62px">${escapeHTML(label)}</button>`).join("")}</div>`);
    $("dialog-content").querySelectorAll("[data-kind]").forEach((button)=>button.onclick=run(async()=>{S.filter="other";S.otherKind=button.dataset.kind;closeDialog();document.querySelectorAll("[data-filter]").forEach((el)=>el.classList.toggle("active",el.dataset.filter==="other"));await loadAssets();}));
  }
  function bindEvents() {
    $("import-media").onclick=importMediaDialog;$("add-shape").onclick=run(shapeDialog);
    $("new-project").onclick=newProjectDialog;$("empty-create").onclick=newProjectDialog;
    $("project-select").onchange=run((event)=>switchProject(event.target.value));
    $("save").onclick=run(async()=>{await saveProject();toast("Project saved.","success",2300);});
    $("undo").onclick=run(undo);$("ai-interface").onclick=aiDialog;
    $("review-cutout").onclick=run(async()=>{const a=S.job?.result?.asset;if(a?.id){rememberAssets([a]);showLibrary("assets");await selectAsset(a.id);}});
    $("render-preview").onclick=run(()=>startRender("preview"));$("render-final").onclick=run(()=>startRender("final"));
    $("cancel-render").onclick=run(async()=>{if(!S.job)return;$("cancel-render").disabled=true;try{S.job=await call("job_cancel",{job_id:S.job.id});renderJob(S.job);if(["queued","running"].includes(S.job.status))pollJob();}finally{$("cancel-render").disabled=false;}});
    $("render-message").onclick=()=>{if(S.job?.error)dialog("Render error",`<pre>${escapeHTML(S.job.error)}</pre>`);};
    $("assets-tab").onclick=()=>showLibrary("assets");$("effects-tab").onclick=()=>showLibrary("effects");
    let searchTimer;$("library-search").oninput=(event)=>{clearTimeout(searchTimer);S.query=event.target.value;searchTimer=setTimeout(()=>loadAssets().catch(report),220);};
    document.querySelectorAll("[data-filter]").forEach((button)=>button.onclick=run(async()=>{if(button.dataset.filter==="other"){moreLibraryDialog();return;}S.filter=button.dataset.filter;document.querySelectorAll("[data-filter]").forEach((el)=>el.classList.toggle("active",el===button));await loadAssets();}));
    $("load-more").onclick=run(()=>loadAssets(true));
    $("scan-library").onclick=run(async()=>{const button=$("scan-library");button.disabled=true;button.querySelector(".icon")?.classList.add("busy");try{const result=await call("library_scan",{},600000);await loadAssets();await loadFonts();toast(`Library refreshed · ${number(result.total).toLocaleString()} assets.`,"success");$("connection-status").textContent=`Engine ready · ${number(result.total).toLocaleString()} assets`;}finally{button.disabled=false;button.querySelector(".icon")?.classList.remove("busy");}});
    $("asset-grid").addEventListener("click",run(async(event)=>{const add=event.target.closest("[data-add-asset]");if(add){await addAsset(add.dataset.addAsset);return;}const effect=event.target.closest("[data-effect]");if(effect){applyEffect(effect.dataset.effect);return;}const card=event.target.closest("[data-asset]");if(card)await selectAsset(card.dataset.asset);}));
    $("asset-grid").addEventListener("keydown",(event)=>{if(["Enter"," "].includes(event.key)&&event.target.matches("[data-asset]")){event.preventDefault();selectAsset(event.target.dataset.asset).catch(report);}});
    $("inspector-content").addEventListener("change",handleInspectorChange);
    $("inspector-content").addEventListener("input",(event)=>{const range=event.target.closest('input[type="range"]');if(range){const output=range.closest(".field")?.querySelector("output");if(output)output.textContent=range.dataset.unit==="%"?`${Math.round(number(range.value)*100)}%`:`${round(range.value,2)}${range.dataset.unit||""}`;}});
    $("inspector-content").addEventListener("click",run(async(event)=>{
      const add=event.target.closest("[data-add-role]");if(add){add.disabled=true;try{await addAsset(add.dataset.assetId,add.dataset.addRole);}finally{if(add.isConnected)add.disabled=false;}return;}
      const addKeyframe=event.target.closest("[data-add-keyframe]");
      if(addKeyframe){const item=itemFor(),key=addKeyframe.dataset.addKeyframe,duration=itemDuration(item,S.selection.type);let time=round(localPlayhead(item,S.selection.type),3);const existing=item[key]||[];if(existing.some((f)=>Math.abs(f.time-time)<.001))time=round(duration,6);if(existing.some((f)=>Math.abs(f.time-time)<.001)){toast("Move the playhead to a different time before adding a keyframe.");return;}mutate(()=>{item[key]||=[];item[key].push(key==="motion"?{time,zoom:item.transform?.zoom||1,x:item.transform?.x??.5,y:item.transform?.y??.5}:{time,volume:1});item[key].sort((a,b)=>a.time-b.time);});return;}
      const removeKeyframe=event.target.closest("[data-remove-keyframe]");if(removeKeyframe){const item=itemFor();mutate(()=>item[removeKeyframe.dataset.removeKeyframe].splice(number(removeKeyframe.dataset.index),1));return;}
      const effect=event.target.closest("[data-remove-effect]");if(effect){const clip=itemFor();mutate(()=>clip.effects.splice(number(effect.dataset.removeEffect),1));return;}
      const size=event.target.closest("[data-size]");if(size){const dimensions={landscape:[1920,1080],portrait:[1080,1920],square:[1080,1080]}[size.dataset.size];mutate((p)=>{[p.canvas.width,p.canvas.height]=dimensions;});return;}
      const action=event.target.closest("[data-action]");if(action)await inspectorAction(action.dataset.action);
    }));
    $("canvas-shortcut").onclick=()=>{S.selection={type:"project"};renderInspector();renderTimeline();};
    $("play-pause").onclick=run(togglePlayback);$("playback-seek").oninput=(event)=>{const player=$("video-player");if(player.readyState>=1)player.currentTime=number(event.target.value);};
    $("view-source").onclick=()=>{if(S.source)setSource(S.source);else{const clip=selectedClip()||S.project?.clips[0];if(clip)selectItem("clips",clip.id);else resetViewer();}};
    $("view-render").onclick=()=>showRendered();
    $("fullscreen").onclick=run(async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await $("preview-stage").requestFullscreen();});
    const player=$("video-player");
    player.addEventListener("loadedmetadata",()=>{const duration=Number.isFinite(player.duration)?player.duration:0;$("playback-seek").max=String(duration||1);$("playback-seek").disabled=!duration;$("play-duration").textContent=fmt(duration);$("media-error").hidden=true;});
    player.addEventListener("timeupdate",()=>{$("play-time").textContent=fmt(player.currentTime);$("playback-seek").value=String(player.currentTime);updatePlayhead();});
    player.addEventListener("play",()=>{$("play-pause").innerHTML=icon("pause");});player.addEventListener("pause",()=>{$("play-pause").innerHTML=icon("play");});
    player.addEventListener("error",()=>{if(player.getAttribute("src"))$("media-error").hidden=false;});
    $("image-player").addEventListener("error",()=>{$("media-error").hidden=false;});
    $("add-accent").onclick=run(()=>accentDialog());$("add-title").onclick=run(()=>titleDialog());$("auto-montage").onclick=run(autoMontageDialog);
    $("timeline-zoom").oninput=(event)=>{S.zoom=number(event.target.value,1);renderTimeline();};
    const zoomBy=(amount)=>{S.zoom=clamp(round(S.zoom+amount,1),.6,5);$("timeline-zoom").value=S.zoom;renderTimeline();};
    $("zoom-in").onclick=()=>zoomBy(.2);$("zoom-out").onclick=()=>zoomBy(-.2);$("fit-timeline").onclick=()=>{S.zoom=1;$("timeline-zoom").value=1;$("timeline-scroll").scrollLeft=0;renderTimeline();};
    $("timeline-surface").addEventListener("click",run(async(event)=>{const item=event.target.closest("[data-item]");if(item){selectItem(item.dataset.type,item.dataset.item);return;}if(event.target.closest("#timeline-ruler")){const rect=$("timeline-ruler").getBoundingClientRect();await seekTimeline((event.clientX-rect.left-12)/S.pps);}}));
    $("timeline-surface").addEventListener("keydown",(event)=>{if(["Enter"," "].includes(event.key)&&event.target.matches("[data-item]")){event.preventDefault();selectItem(event.target.dataset.type,event.target.dataset.item);}});
    let drag=null;
    $("asset-grid").addEventListener("dragstart",(event)=>{const card=event.target.closest("[data-asset]");const a=card&&asset(card.dataset.asset);if(!a||!["video","audio","image"].includes(a.kind)){event.preventDefault();return;}drag={kind:"asset",id:a.id};event.dataTransfer.effectAllowed="copy";event.dataTransfer.setData("application/x-montage",JSON.stringify(drag));});
    $("timeline-surface").addEventListener("dragstart",(event)=>{const item=event.target.closest('[data-type="clips"]');if(!item){event.preventDefault();return;}drag={kind:"clip",id:item.dataset.item};event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("application/x-montage",JSON.stringify(drag));item.classList.add("dragging");});
    const clearDrag=()=>{document.querySelectorAll(".dragging,.dragover,.drop-before,.drop-after").forEach((el)=>el.classList.remove("dragging","dragover","drop-before","drop-after"));};
    document.addEventListener("dragend",()=>{drag=null;clearDrag();});
    $("timeline-surface").addEventListener("dragover",(event)=>{const lane=event.target.closest("[data-lane]");if(!lane||(!drag&&!event.dataTransfer.types.includes("application/x-montage")))return;if(drag?.kind==="clip"&&lane.dataset.lane!=="clips")return;event.preventDefault();clearDrag();lane.classList.add("dragover");const target=event.target.closest('[data-type="clips"]');if(drag?.kind==="clip"&&target&&target.dataset.item!==drag.id){const rect=target.getBoundingClientRect();target.classList.add(event.clientX<rect.left+rect.width/2?"drop-before":"drop-after");}});
    $("timeline-surface").addEventListener("dragleave",(event)=>{if(!$("timeline-surface").contains(event.relatedTarget))clearDrag();});
    $("timeline-surface").addEventListener("drop",run(async(event)=>{
      const lane=event.target.closest("[data-lane]");if(!lane)return;event.preventDefault();const data=drag;clearDrag();drag=null;if(!data)return;
      if(data.kind==="asset"){if(lane.dataset.lane==="titles")throw new Error("Use Add title for text, or drop media on a video, overlay or audio track.");await addAsset(data.id,lane.dataset.lane);return;}
      if(data.kind==="clip"&&lane.dataset.lane==="clips"){
        const clips=S.project?.clips;if(!clips)return;const index=clips.findIndex((c)=>c.id===data.id);if(index<0)return;
        const target=event.target.closest('[data-type="clips"]');if(target?.dataset.item===data.id)return;
        let destination=target?clips.findIndex((c)=>c.id===target.dataset.item):clips.length;if(target){const rect=target.getBoundingClientRect();if(event.clientX>=rect.left+rect.width/2)destination++;}if(index<destination)destination--;
        mutate((p)=>{const [moved]=p.clips.splice(index,1);p.clips.splice(destination,0,moved);});
      }
    }));
    window.addEventListener("keydown",(event)=>{
      const typing=event.target instanceof HTMLElement&&event.target.matches("input,textarea,select,[contenteditable]");
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();if(typing)event.target.blur();saveProject().then(()=>{if(S.project)toast("Project saved.","success",1800);}).catch(report);return;}
      if($("main-dialog").open||typing)return;
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="z"){event.preventDefault();undo().catch(report);return;}
      if(event.key===" "&&!event.target.closest("button")){event.preventDefault();togglePlayback().catch(report);}
      if(event.key==="/"){event.preventDefault();$("library-search").focus();}
      if(["Delete","Backspace"].includes(event.key)&&S.selection&&["clips","audio","overlays","titles","shapes","accents"].includes(S.selection.type)){event.preventDefault();removeItem();}
    });
    window.addEventListener("beforeunload",(event)=>{if(S.dirty){event.preventDefault();event.returnValue="";}});
    let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderTimeline,120);});
    $("retry-connect").onclick=boot;
  }
  async function boot() {
    $("boot-error").hidden=true;
    try {
      const response=await fetch("/api/bootstrap");if(!response.ok)throw new Error(`Server returned HTTP ${response.status}.`);const data=await response.json();
      S.csrf=data.csrf_token;if(!S.csrf)throw new Error("The server did not provide a session token. Restart Framedrop and reload this page.");
      S.status=data.status||{};S.projects=Array.isArray(data.projects)?data.projects:data.projects?.projects||[];S.effects=Array.isArray(data.effects)?data.effects:data.effects?.effects||[];S.transitions=data.transitions||data.effects?.transitions||["cut","fade","dissolve"];
      S.assets=data.assets?.items||[];S.total=data.assets?.total||0;rememberAssets(S.assets);renderProjectOptions();renderAssets();renderInspector();syncHeader();renderTimeline();
      $("media-root").textContent=S.status.media_root||"Editing";$("media-root").title=S.status.media_root||"Media source folder";
      $("connection-dot").className="status-dot ready";$("connection-status").textContent=`Engine ready · ${number(S.status.asset_count,S.total).toLocaleString()} assets`;
      $("status-version").textContent=`FRAMEDROP ${S.status.version?`· ${S.status.version}`:""}`;
      $("status-detail").textContent="Local media · shared CLI + MCP timeline";
      let savedId;try{savedId=localStorage.getItem("montage-project");}catch(_){}
      const initial=S.projects.find((p)=>p.id===savedId)||S.projects[0];if(initial)await switchProject(initial.id,true);
      loadFonts().catch(report);
    } catch(error) { $("boot-error").hidden=false;$("boot-error-message").textContent=error.message;$("connection-dot").className="status-dot error";$("connection-status").textContent="Disconnected"; }
  }

  const option = (value, label, chosen) => `<option value="${escapeHTML(value)}" ${String(value) === String(chosen) ? "selected" : ""}>${escapeHTML(label)}</option>`;
  function field(label, key, value, {type = "number", min, max, step = .01, help, disabled = false} = {}) {
    const id = `field-${key.replace(/\./g, "-")}`;
    return `<div class="field"><label for="${id}">${escapeHTML(label)}</label><input id="${id}" data-field="${escapeHTML(key)}" type="${type}" value="${escapeHTML(value)}" ${min !== undefined ? `min="${min}"` : ""} ${max !== undefined ? `max="${max}"` : ""} ${type === "number" ? `step="${step}"` : ""} ${disabled ? "disabled" : ""}>${help ? `<span class="field-help">${escapeHTML(help)}</span>` : ""}</div>`;
  }
  function selectField(label, key, value, options) {
    const id = `field-${key.replace(/\./g, "-")}`;
    return `<div class="field"><label for="${id}">${escapeHTML(label)}</label><select id="${id}" data-field="${escapeHTML(key)}">${options.map((o) => option(Array.isArray(o) ? o[0] : o, Array.isArray(o) ? o[1] : titleCase(o), value)).join("")}</select></div>`;
  }
  function rangeField(label, key, value, min = 0, max = 1, step = .01, unit = "%") {
    const id = `field-${key.replace(/\./g, "-")}`; const shown = unit === "%" ? `${Math.round(number(value) * 100)}%` : `${round(value, 2)}${unit}`;
    return `<div class="field"><div class="range-heading"><label for="${id}">${escapeHTML(label)}</label><output>${shown}</output></div><input id="${id}" data-field="${escapeHTML(key)}" data-unit="${escapeHTML(unit)}" type="range" min="${min}" max="${max}" step="${step}" value="${number(value)}"></div>`;
  }
  function checkboxField(label, key, value) { const id = `field-${key}`; return `<div class="checkbox-field"><input id="${id}" type="checkbox" data-field="${key}" ${value ? "checked" : ""}><label for="${id}">${escapeHTML(label)}</label></div>`; }
  const section = (heading, contents, action = "") => `<section class="inspector-section"><div class="section-heading"><h3>${escapeHTML(heading)}</h3>${action}</div>${contents}</section>`;
  const stat = (label) => `<span class="detail-stat">${escapeHTML(label)}</span>`;
  const notice = (text, warning = false) => `<div class="inspector-notice ${warning ? "warning" : ""}">${icon("info")}<span>${escapeHTML(text)}</span></div>`;
  const removeButton = () => `<div class="danger-zone"><button data-action="remove-item">${icon("x")} Remove from timeline</button></div>`;
  const timeFields = (item, maxDuration=86400) => `<div class="field-row">${field("Timeline start (s)", "start", item.start, {min:0,max:86400})}${field("Duration (s)", "duration", item.duration, {min:.02,max:maxDuration})}</div>`;
  function renderInspector() {
    const selection = S.selection; const p = S.project; let html = "";
    if(selection?.type === "captions") { renderCaptionsInspector(); return; }
    if (selection?.type === "asset") { renderAssetInspector(asset(selection.id)); return; }
    if (!p || !selection || selection.type === "project") {
      $("inspector-kind").textContent = "Project";
      if (!p) {
        html = `<h2 class="inspector-title">A workspace for your next montage.</h2><p class="inspector-subtitle">Start with a project, then add clips from your Editing folder.</p>${notice("Your AI tools and this app work with the same saved timeline. Every save keeps a recoverable revision.")}<button class="button primary inspector-action" data-action="new-project">${icon("plus")} New project</button>${section("Connected workflows", `<p class="field-help">Use the local CLI or MCP server to assemble edits, apply native effects, analyze audio and render. Inspect and adjust the result here.</p><button class="button secondary inspector-action" data-action="ai-interface">${icon("terminal")} Open AI tool reference</button>`)}`;
      } else {
        const c = p.canvas; const shape = c.width === c.height ? "square" : c.width > c.height ? "landscape" : "portrait";
        html = `<h2 class="inspector-title">Project settings</h2><p class="inspector-subtitle">Your canvas, your format.</p>${field("Project name", "name", p.name, {type:"text"})}${section("Canvas", `<div class="preset-grid"><button class="canvas-preset ${shape === "landscape" ? "active" : ""}" data-size="landscape"><i></i>Landscape</button><button class="canvas-preset ${shape === "portrait" ? "active" : ""}" data-size="portrait"><i></i>Portrait</button><button class="canvas-preset ${shape === "square" ? "active" : ""}" data-size="square"><i></i>Square</button></div><div class="field-row">${field("Width", "canvas.width", c.width, {min:64,max:4096,step:2})}${field("Height", "canvas.height", c.height, {min:64,max:4096,step:2})}</div><div class="field-row">${selectField("Frame rate", "canvas.fps", c.fps, [...new Set([24,25,30,50,60,number(c.fps)])].sort((a,b)=>a-b).map((fps)=>[fps,`${fps} fps`]))}${field("Background", "canvas.background", c.background || "#101014", {type:"color"})}</div>${selectField("Default framing", "canvas.fit", c.fit || "cover", [["cover","Fill canvas (crop)"],["contain","Fit inside canvas"]])}`)}${section("Export quality",selectField("Final export","export_profile",p.export_profile||"standard",[["standard","Standard"],["high","High quality · larger files"]])+`<p class="field-help">High quality preserves more detail through effect passes. Exports use the canvas resolution; preview renders stay small.</p>`)}${section("Audio", `${checkboxField("Normalize the final audio mix", "normalize_audio", p.normalize_audio !== false)}<p class="field-help">All exports use stereo audio. Adjust music and clip levels in their own inspectors.</p>`)}${section("Project", `<dl class="property-list"><dt>Revision</dt><dd>${p.revision}${S.dirty ? " + unsaved changes" : ""}</dd><dt>Clips</dt><dd>${p.clips.length}</dd><dt>Timeline</dt><dd>${fmt(projectDuration())}</dd><dt>Project ID</dt><dd>${escapeHTML(p.id)}</dd></dl><button class="button secondary inspector-action" data-action="validate">${icon("check")} Validate timeline</button><button class="button quiet inspector-action" data-action="refresh-project">${icon("refresh")} Load latest saved version</button>`)}`;
      }
    } else {
      const item = itemFor();
      if (!item) { S.selection = {type:"project"}; renderInspector(); return; }
      const a = asset(item.asset_id); const sourceDuration = metadataDuration(a); const name = selection.type === "titles" ? "Title" : ["shapes","accents"].includes(selection.type) ? titleCase(item.kind) : a?.name || "Timeline item";
      $("inspector-kind").textContent = ({clips:"Video",audio:"Audio",overlays:"Overlay",titles:"Title",shapes:"Shape",accents:"Accent"})[selection.type];
      html = `<h2 class="inspector-title">${escapeHTML(name)}</h2><p class="inspector-subtitle">${selection.type === "titles" ? "Text is composited into your rendered video." : selection.type === "accents" ? "Animated graphics timed to your montage." : selection.type === "shapes" ? "Point out the moment. Shapes appear in rendered previews." : escapeHTML(a?.relative_path || "Source metadata loads on demand.")}</p>`;
      if (selection.type === "clips") {
        html += `<div class="detail-stat-row">${stat(`${seconds(clipDuration(item))} on timeline`)}${a?.metadata?.width ? stat(`${a.metadata.width} × ${a.metadata.height}`) : ""}${sourceDuration ? stat(`${seconds(sourceDuration)} source`) : ""}</div>`;
        if (!item.freeze) html += section("Trim", `<div class="field-row">${field("Source in (s)", "in", item.in, {min:0,max:sourceDuration || 86400})}${field("Source out (s)", "out", item.out, {min:.01,max:a?.kind === "image" ? 86400 : sourceDuration || 86400})}</div><div class="inline-buttons"><button class="button secondary" data-action="set-in">${icon("scissors")} Set in at playhead</button><button class="button secondary" data-action="set-out">Set out</button></div><p class="field-help">In and out are positions in the original source. Still images use their out value as duration.</p>`);
        html += section("Freeze frame", item.freeze ? `<div class="field-row">${field("Source frame (s)","freeze.time",item.freeze.time,{min:0,max:sourceDuration ? Math.max(0,sourceDuration-1/p.canvas.fps) : 86400,step:"any"})}${field("Hold (s)","freeze.duration",item.freeze.duration,{min:.1,max:300,step:.1})}</div><button class="button quiet inspector-action" data-action="clear-freeze">Restore source motion</button><p class="field-help">This clip holds one source frame with no original clip audio. Dedicated audio tracks still play.</p>` : `<button class="button secondary inspector-action" data-action="freeze-frame" ${a?.kind === "video" ? "" : "disabled"}>${icon("frame")} Freeze from source playhead</button><p class="field-help">Keeps footage before the chosen frame, then inserts a muted hold.</p>`);
        html += section("Playback", `<div class="field-row">${item.freeze ? "" : field("Speed", "speed", item.speed || 1, {min:.25,max:8,step:.05})}${selectField("Framing", "fit", item.fit || "cover", [["cover","Fill (crop)"],["contain","Fit"]])}</div>${item.freeze ? "" : item.segments?.length ? `<div class="inspector-notice">${icon("bolt")}<span>Velocity ramp · ${item.segments.length} segments<br>${item.segments.map((seg)=>`${round(seg.start,2)}–${round(seg.end,2)}s at ${seg.speed}×`).join("<br>")}</span></div><button class="button quiet inspector-action" data-action="constant-speed">Use constant speed</button>` : `<button class="button quiet inspector-action" data-action="velocity-ramp">${icon("bolt")} Fast → slow → fast ramp</button>`}${item.freeze ? '<p class="field-help">Frozen clips are silent. Sound effects on the Audio track play normally.</p>' : `${rangeField("Source volume", "volume", item.volume ?? 1, 0, 4)}<button class="button secondary inspector-action" data-action="mute-source">${icon("volume")} ${number(item.volume,1) === 0 ? "Unmute original audio" : "Mute original audio"}</button>${a?.metadata?.has_audio === false ? '<p class="field-help">This source has no audio stream.</p>' : ""}`} `);
        if (!item.freeze) html += section("Slow-motion smoothness", `${selectField("Missing frames","interpolation",item.interpolation||"duplicate",[["duplicate","Repeat source frames"],["optical_flow","Optical flow · slower render"]])}<p class="field-help">Optical flow generates intermediate frames only when source cadence falls below the output rate. Inspect fast turns and HUD edges for warping. Real-time 60 fps footage is often the cleanest choice.</p>${rangeField("Motion blur","motion_blur",item.motion_blur??0)}<p class="field-help">Blends two closely spaced motion samples per frame. Optical flow supplies extra samples when needed. Keep subtle for readable gameplay.</p>`);
        if (!item.freeze) html += section("Audio keyframes", keyframeEditor(item,"clips","volume_keyframes"));
        const transform=item.transform||{}, color=item.color||{};
        html += section("Crop & reframe", `${rangeField("Zoom", "transform.zoom", transform.zoom??1, 1,4,.01,"×")}${rangeField("Horizontal crop anchor", "transform.x", transform.x??.5)}${rangeField("Vertical crop anchor", "transform.y", transform.y??.5)}${selectField("Rotation", "transform.rotation", transform.rotation||0, [[0,"None"],[90,"90° clockwise"],[-90,"90° counterclockwise"],[180,"180°"]])}<div class="field-row">${checkboxField("Flip horizontal", "transform.flip_x", transform.flip_x)}${checkboxField("Flip vertical", "transform.flip_y", transform.flip_y)}</div>`);
        html += section("Motion keyframes", keyframeEditor(item,"clips","motion"));
        html += section("Color correction", `${rangeField("Brightness", "color.brightness", color.brightness??0,-.5,.5,.01,"")}${rangeField("Contrast", "color.contrast", color.contrast??1,.25,3,.01,"×")}${rangeField("Saturation", "color.saturation", color.saturation??1,0,3,.01)}${rangeField("Gamma", "color.gamma", color.gamma??1,.25,3,.01,"×")}`);
        html += section("Video fades", `<div class="field-row">${field("Fade in (s)","fade_in",item.fade_in||0,{min:0,max:round(clipDuration(item),3)})}${field("Fade out (s)","fade_out",item.fade_out||0,{min:0,max:round(clipDuration(item),3)})}</div>`);
        html += section("Outgoing transition", `${selectField("Transition", "transition.name", item.transition?.name || "cut", S.transitions.map((t) => typeof t === "string" ? [t,titleCase(t)] : [t.name,t.label || titleCase(t.name)]))}${item.transition?.name && item.transition.name !== "cut" ? field("Overlap (s)", "transition.duration", item.transition.duration || .3, {min:.01,max:2,step:.01}) : ""}<p class="field-help">${p.clips.at(-1)?.id === item.id ? "This is the last clip. Its outgoing transition takes effect when another clip follows it." : "Transitions overlap adjacent clips and shorten the timeline. Leave enough footage for both incoming and outgoing transitions."}</p>`);
        html += section("Effects", `<div class="effect-stack">${item.effects?.length ? item.effects.map((effect, index) => { const descriptor = S.effects.find((e)=>e.name===effect.name); return `<div class="stack-effect"><div class="range-heading"><span>${escapeHTML(descriptor?.label || titleCase(effect.name))}</span><button class="icon-button" data-remove-effect="${index}" aria-label="Remove ${escapeHTML(effect.name)}">${icon("x")}</button></div>${rangeField("Strength", `effects.${index}.strength`, effect.strength ?? descriptor?.strength?.default ?? .7, descriptor?.strength?.min ?? 0, descriptor?.strength?.max ?? 1)}<div class="field-row">${field("Start (s)",`effects.${index}.start`,effect.start ?? 0,{min:0,max:round(clipDuration(item),6),step:.001})}${field("End (s)",`effects.${index}.end`,effect.end ?? round(clipDuration(item),6),{min:.001,max:round(clipDuration(item),6),step:.001})}</div><p class="field-help">Times are local to this clip.</p></div>`; }).join("") : '<div class="empty-stack">Give this clip a look.<br><button class="text-button" data-action="browse-effects">Browse native effects</button></div>'}</div>${item.lut_asset_id ? `<div class="inspector-notice">${icon("layers")}<span>LUT: ${escapeHTML(assetName(item.lut_asset_id))}<br><button class="text-button" data-action="remove-lut">Remove lookup table</button></span></div>` : ""}`, '<button class="text-button" data-action="browse-effects">+ Add effect</button>');
        html += `<div class="inline-buttons"><button class="button secondary" data-action="move-left">${icon("left")} Move earlier</button><button class="button secondary" data-action="move-right">Move later ${icon("right")}</button></div>`;
      } else if (selection.type === "audio") {
        html += section("Placement", `${field("Timeline start (s)", "start", item.start, {min:0,max:86400})}<button class="button quiet inspector-action" data-action="align-to-playhead">Start at timeline playhead</button><div class="field-row">${field("Source in (s)", "in", item.in, {min:0,max:sourceDuration || 86400})}${field("Source out (s)", "out", item.out, {min:.01,max:sourceDuration || 86400})}</div>${checkboxField("Loop audio", "loop", item.loop)}${item.loop ? field("Timeline duration (s)", "duration", item.duration || Math.max(.1,projectDuration()-item.start), {min:.05,max:86400}) : ""}`);
        html += section("Mix", `${rangeField("Volume", "volume", item.volume ?? .7, 0, 4)}<div class="field-row">${field("Fade in (s)", "fade_in", item.fade_in || 0, {min:0,max:60})}${field("Fade out (s)", "fade_out", item.fade_out || 0, {min:0,max:60})}</div>`);
        html += section("Volume keyframes", keyframeEditor(item,"audio","volume_keyframes"));
        const beats = S.analysis.get(item.asset_id)?.beats;
        html += section("Audio analysis", `<p class="field-help">Analyze up to 120 seconds of the selected source for an approximate beat grid and waveform.</p><button class="button secondary inspector-action" data-action="analyze-audio">${icon("wave")} Analyze beats + waveform</button>${beats ? `<div class="detail-stat-row">${stat(`${beats.beats?.length || 0} detected beats`)}${beats.bpm ? stat(`${round(beats.bpm,1)} BPM`) : ""}</div><button class="button quiet inspector-action" data-action="add-beat-markers">Add detected beats as markers</button>` : ""}`);
      } else if (selection.type === "overlays") {
        html += section("Placement", `${timeFields(item)}${field("Source in (s)", "in", item.in || 0, {min:0,max:sourceDuration || 86400})}${checkboxField("Loop source while overlay is active", "loop", item.loop)}`);
        html += section("Composite", `${selectField("Blend mode", "blend", item.blend || "screen", [["normal","Normal"],["screen","Screen (black transparent)"],["add","Add / light"],["lighten","Lighten"],["chroma","Chroma key"]])}${rangeField("Opacity", "opacity", item.opacity ?? .7)}${rangeField("Width of canvas", "width", item.width ?? 1, .05, 3)}${item.blend === "chroma" ? `<div class="field-row">${field("Key color", "key_color", item.key_color || "#00ff00", {type:"color"})}${field("Similarity", "key_similarity", item.key_similarity ?? .15, {min:.01,max:1,step:.01})}</div>` : ""}${rangeField("Horizontal position", "x", item.x ?? .5)}${rangeField("Vertical position", "y", item.y ?? .5)}<p class="field-help">Position moves the overlay within the available space. Render a preview to inspect the composite.</p>`);
      } else if (selection.type === "shapes") {
        html += `<div class="field"><label for="shape-selection">Selected shape</label><select id="shape-selection">${p.shapes.map((shape,index)=>option(shape.id,`${index+1} · ${titleCase(shape.kind)} · ${fmt(shape.start)}`,item.id)).join("")}</select><span class="field-help">Select overlapping arrows and circles here.</span></div>`;
        html += section("Timing", `${timeFields(item)}<button class="button quiet inspector-action" data-action="align-to-playhead">Start at timeline playhead</button>`);
        html += section("Appearance", `${selectField("Shape","kind",item.kind,[["arrow","Pointing arrow"],["ellipse","Circle / ellipse"],["rectangle","Rectangle"]])}<div class="field-row">${field("Color","color",item.color||"#ff3030",{type:"color"})}${field("Stroke (px)","stroke_width",item.stroke_width??12,{min:1,max:256,step:1})}</div>${rangeField("Opacity","opacity",item.opacity??1)}`);
        html += section("Position", `<p class="field-help">Coordinates run from 0 to 1 across the canvas. ${item.kind === "arrow" ? "The arrow runs from its tail to its tip." : "The two corners set the shape’s bounds."}</p><div class="field-row">${field(item.kind==="arrow"?"Tail X":"Corner 1 X","x",item.x,{min:0,max:1,step:.01})}${field(item.kind==="arrow"?"Tail Y":"Corner 1 Y","y",item.y,{min:0,max:1,step:.01})}</div><div class="field-row">${field(item.kind==="arrow"?"Tip X":"Corner 2 X","x2",item.x2,{min:0,max:1,step:.01})}${field(item.kind==="arrow"?"Tip Y":"Corner 2 Y","y2",item.y2,{min:0,max:1,step:.01})}</div>${shapePreview(item)}`);
      } else if (selection.type === "accents") {
        html += section("Timing",`${timeFields(item,10)}<button class="button quiet inspector-action" data-action="align-to-playhead">Start at timeline playhead</button>`);
        html += section("Accent",`${selectField("Kind","kind",item.kind,[["impact_ring","Impact ring"],["spark_burst","Spark burst"],["light_sweep","Light sweep"]])}${field("Color","color",item.color||"#ff62c6",{type:"color"})}${rangeField("Opacity","opacity",item.opacity??.8)}${rangeField("Size / canvas width","size",item.size??.25,.02,2)}${rangeField("Horizontal center","x",item.x??.5)}${rangeField("Vertical center","y",item.y??.5)}${field("Rotation","rotation",item.rotation??0,{min:-180,max:180,step:1})}<p class="field-help">Native animated graphics. No overlay file is needed. Place an accent at a kill or beat marker, then render a preview.</p>`);
      } else if (selection.type === "titles") {
        html += `<div class="field"><label for="title-text">Text</label><textarea id="title-text" data-field="text" maxlength="2000">${escapeHTML(item.text)}</textarea></div>${section("Timing", timeFields(item))}`;
        const fonts = [["","System default"], ...S.fonts.map((f)=>[f.id,f.name])]; if (item.font_asset_id && !S.fonts.some((f)=>f.id===item.font_asset_id)) fonts.push([item.font_asset_id,assetName(item.font_asset_id)]);
        html += section("Typography", `${selectField("Font", "font_asset_id", item.font_asset_id || "", fonts)}<div class="field-row">${field("Font size (px)", "font_size", item.font_size || 64, {min:8,max:512,step:1})}${field("Color", "color", item.color || "#ffffff", {type:"color"})}</div>${checkboxField("Background box", "box", item.box !== false)}${field("Fade in / out (s)", "fade", item.fade ?? .15, {min:0,max:5})}<p class="field-help">Font sizes use the full canvas. Previews scale text with the video.</p>`);
        html += section("Text animation",textMotionFields(item));
        html += section("Position", `${rangeField("Horizontal", "x", item.x ?? .5)}${rangeField("Vertical", "y", item.y ?? .8)}`);
      }
      html += removeButton();
    }
    $("inspector-content").innerHTML = html;
  }

  function renderCaptionsInspector() {
    $("inspector-kind").textContent="Captions";const p=S.project;
    if(!p){$("inspector-content").innerHTML=`<h2 class="inspector-title">Captions</h2><p class="inspector-subtitle">Create a project before adding captions.</p><button class="button primary inspector-action" data-action="new-project">${icon("plus")} New project</button>`;return;}
    const style=p.caption_style||{preset:"clean",font_size:52,color:"#ffffff",outline_color:"#000000",outline:3,position:"bottom",margin:80};const cues=p.captions||[];const limit=S.captionLimit||50;
    $("inspector-content").innerHTML=`<h2 class="inspector-title">Say it on screen.</h2><p class="inspector-subtitle">${cues.length} caption ${cues.length===1?"cue":"cues"} · burned into rendered video</p><button class="button primary inspector-action" data-caption-action="auto">${icon("sparkles")} Auto captions</button><div class="inline-buttons"><button class="button secondary" data-caption-action="add">${icon("plus")} Add cue</button><button class="button secondary" data-caption-action="import">Import SRT / VTT</button></div><div class="inline-buttons"><button class="button quiet" data-caption-action="export-srt" ${cues.length?"":"disabled"}>${icon("download")} SRT</button><button class="button quiet" data-caption-action="export-vtt" ${cues.length?"":"disabled"}>${icon("download")} VTT</button></div>${section("Caption style",`${selectField("Preset","caption_style.preset",style.preset||"clean",[["clean","Clean outline"],["bold","Bold"],["boxed","Background box"],["neon","Neon lyrics"]])}${selectField("Font","caption_style.font_asset_id",style.font_asset_id||"",[["","System default"],...S.fonts.map((f)=>[f.id,f.name])])}<div class="field-row">${field("Size (px)","caption_style.font_size",style.font_size||52,{min:8,max:300,step:1})}${selectField("Position","caption_style.position",style.position||"bottom",[["bottom","Bottom"],["center","Center"],["top","Top"]])}</div><div class="field-row">${field("Text color","caption_style.color",style.color||"#ffffff",{type:"color"})}${field("Outline color","caption_style.outline_color",style.outline_color||"#000000",{type:"color"})}</div><div class="field-row">${field("Outline (px)","caption_style.outline",style.outline??3,{min:0,max:12,step:.5})}${field("Margin (px)","caption_style.margin",style.margin??80,{min:0,max:1000,step:1})}</div>`)}${section("Lyric animation",textMotionFields(style,"caption_style."))}${section("Caption cues",`<div class="caption-cue-list">${cues.slice(0,limit).map((cue,index)=>`<article class="caption-cue" data-cue="${escapeHTML(cue.id)}"><div class="caption-cue-heading"><button class="text-button" data-caption-seek="${escapeHTML(cue.id)}">${String(index+1).padStart(2,"0")} · ${fmt(cue.start)}</button><button class="icon-button small" data-caption-delete="${escapeHTML(cue.id)}" aria-label="Delete caption ${index+1}">${icon("x")}</button></div><div class="field-row"><div class="field"><label>Start (s)</label><input type="number" min="0" step="0.01" value="${cue.start}" data-cue-field="start" aria-label="Caption ${index+1} start"></div><div class="field"><label>End (s)</label><input type="number" min="0.01" step="0.01" value="${cue.end}" data-cue-field="end" aria-label="Caption ${index+1} end"></div></div><textarea data-cue-field="text" aria-label="Caption ${index+1} text" maxlength="2000">${escapeHTML(cue.text)}</textarea></article>`).join("")||'<div class="empty-stack">Import a subtitle file, add a cue, or transcribe a rendered preview.</div>'}</div>${cues.length>limit?'<button class="button quiet inspector-action" data-caption-action="more">Show more cues</button>':""}`)}`;
  }
  function addCaptionDialog() {
    if(!S.project)return;
    dialog("Add a caption cue",`<form id="caption-add-form"><div class="field"><label for="caption-add-text">Caption text</label><textarea id="caption-add-text" required maxlength="2000" placeholder="What should the viewer read?"></textarea></div><div class="field-row"><div class="field"><label for="caption-add-start">Start (s)</label><input id="caption-add-start" type="number" min="0" step="0.01" value="${round(S.playhead)}" required></div><div class="field"><label for="caption-add-end">End (s)</label><input id="caption-add-end" type="number" min="0.01" step="0.01" value="${round(S.playhead+2)}" required></div></div></form>`,'<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="caption-add-form">Add caption</button>');
    $("caption-add-form").onsubmit=(event)=>{event.preventDefault();const start=number($("caption-add-start").value),end=number($("caption-add-end").value),text=$("caption-add-text").value.trim();if(!text||end<=start){dialogError(new Error("Enter caption text and an end time after the start."));return;}mutate((p)=>{p.captions||=[];p.captions.push({id:uid(),start,end,text});p.captions.sort((a,b)=>a.start-b.start);});closeDialog();};$("caption-add-text").focus();
  }
  function captionImportDialog() {
    if(!S.project)return;
    dialog("Import captions",`<p>Open an SRT or WebVTT file, or paste its full text. Times stay aligned to the montage timeline.</p><form id="caption-import-form"><div class="field"><label for="caption-file">Subtitle file</label><input id="caption-file" type="file" accept=".srt,.vtt,text/vtt,text/plain"></div><div class="field"><label for="caption-import-text">Subtitle text</label><textarea id="caption-import-text" required rows="8" placeholder="Paste SRT or WEBVTT here…"></textarea></div><div class="field-row"><div class="field"><label for="caption-format">Format</label><select id="caption-format"><option value="srt">SRT</option><option value="vtt">WebVTT</option></select></div><div class="field"><label for="caption-offset">Time offset (s)</label><input id="caption-offset" type="number" step="0.01" value="0"></div></div><label class="checkbox-field"><input type="checkbox" id="caption-replace" checked>Replace existing captions</label></form>`,'<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="caption-import-form" id="caption-import-submit">Import captions</button>');
    $("caption-file").onchange=run(async(event)=>{const file=event.target.files?.[0];if(!file)return;if(file.size>4*1024*1024)throw new Error("Use a subtitle file smaller than 4 MB.");$("caption-import-text").value=await file.text();$("caption-format").value=/\.vtt$/i.test(file.name)?"vtt":"srt";});
    $("caption-import-form").onsubmit=async(event)=>{event.preventDefault();$("caption-import-submit").disabled=true;try{await ensureSaved();const result=await call("captions_import",{project_id:S.project.id,expected_revision:S.project.revision,format:$("caption-format").value,text:$("caption-import-text").value,offset:number($("caption-offset").value),replace:$("caption-replace").checked});closeDialog();setProject(result);S.selection={type:"captions"};renderInspector();toast(`Imported ${result.captions?.length||0} caption cues.`,"success");}catch(error){dialogError(error);}finally{if($("caption-import-submit"))$("caption-import-submit").disabled=false;}};
  }
  async function exportCaptions(format) {
    if(!S.project)return;await ensureSaved();const result=await call("captions_export",{project_id:S.project.id,format});const blob=new Blob([result.text],{type:format==="vtt"?"text/vtt;charset=utf-8":"text/plain;charset=utf-8"});const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=`${S.project.name.replace(/[^a-zA-Z0-9_-]/g,"-")}.${format}`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);toast(`${format.toUpperCase()} captions downloaded.`,"success");
  }
  async function autoCaptionsDialog() {
    if(!S.project)return;await ensureSaved();
    dialog("Auto captions",'<p>Checking local transcription and available renders…</p>');
    try{
      const [status,result]=await Promise.all([call("transcription_status"),call("jobs_list")]);
      const renders=(result.jobs||[]).filter((j)=>j.project_id===S.project.id&&j.status==="completed"&&j.kind!=="transcription"&&["preview","final"].includes(j.quality)).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
      if(!status.installed||(!status.model_ready&&!status.models?.length)){dialog("Offline transcription setup",`<p>The local speech recognition model is not ready yet. Finish its setup before transcribing. You can add or import captions now.</p>${notice(`Runtime installed: ${status.installed?"yes":"no"}. Model ready: ${status.model_ready?"yes":"no"}.`)}<p class="dialog-note">${escapeHTML(typeof status.model==="string"?status.model:"")}</p>`);return;}
      if(!renders.length){dialog("Render a preview first",'<p>Auto captions transcribes the audio of a completed montage render so speech stays aligned with cuts and retiming. Render a preview of this project first.</p>','<button class="button secondary" data-close>Close</button><button class="button primary" id="caption-render-first">Render preview</button>');$("caption-render-first").onclick=run(async()=>{closeDialog();await startRender("preview");});return;}
      dialog("Auto captions",`<p>Transcribe the audio from a render of this timeline using the local speech model. Review the draft before applying it. Re-render first if you changed cuts, speed or audio.</p><form id="caption-transcribe-form"><div class="field"><label for="caption-render-source">Rendered audio source</label><select id="caption-render-source">${renders.map((j)=>option(j.id,`${j.quality==="final"?"Export":"Preview"} · revision ${j.revision} · ${String(j.created_at).slice(0,16).replace("T"," ")}`,renders[0].id)).join("")}</select></div><div class="field"><label for="caption-model">Speech model</label><select id="caption-model">${(status.models?.length ? status.models : [status.default_model || status.model || "base"]).map((name)=>option(name,titleCase(name),status.default_model || status.model || "base")).join("")}</select><span class="field-help">Installed local models. Larger models may improve accuracy and take longer.</span></div><div class="field"><label for="caption-mode">Caption grouping</label><select id="caption-mode"><option value="phrases">Short phrases</option><option value="words">One word at a time</option></select></div><div class="field"><label for="caption-language">Spoken language</label><select id="caption-language"><option value="auto">Detect automatically</option><option value="en">English</option><option value="fi">Finnish</option><option value="sv">Swedish</option><option value="de">German</option><option value="es">Spanish</option><option value="fr">French</option><option value="ja">Japanese</option></select></div></form><p class="dialog-note">Speech recognition may make mistakes, especially over music or game audio. The transcript is saved as a reviewable draft.</p>`,'<button class="button secondary" data-close>Cancel</button><button class="button primary" type="submit" form="caption-transcribe-form" id="caption-transcribe-submit">Transcribe locally</button>');
      $("caption-transcribe-form").onsubmit=async(event)=>{event.preventDefault();$("caption-transcribe-submit").disabled=true;try{S.job=await call("captions_transcribe",{project_id:S.project.id,render_job_id:$("caption-render-source").value,language:$("caption-language").value,mode:$("caption-mode").value,model:$("caption-model").value});closeDialog();renderJob(S.job);pollJob();toast("Local transcription started. Review the caption draft when it completes.");}catch(error){dialogError(error);}finally{if($("caption-transcribe-submit"))$("caption-transcribe-submit").disabled=false;}};
    }catch(error){dialogError(error);}
  }
  function reviewCaptionDraft(job=S.job) {
    if(!job||job.kind!=="transcription"||job.status!=="completed")return;const cues=job.result?.captions||[];
    dialog("Review the caption draft",`<p>${cues.length} cues from local speech recognition. Applying this draft replaces the project’s current captions; you can then edit every cue in the Captions inspector.</p><div class="transcript-review">${cues.map((cue)=>`<div><span>${fmt(cue.start)} → ${fmt(cue.end)}</span><p>${escapeHTML(cue.text)}</p></div>`).join("")||'<p class="dialog-note">No speech captions were returned.</p>'}</div>`,'<button class="button secondary" data-close>Keep as draft</button><button class="button primary" id="caption-apply-draft">Apply captions</button>');
    $("caption-apply-draft").disabled=!cues.length;$("caption-apply-draft").onclick=async()=>{$("caption-apply-draft").disabled=true;try{await ensureSaved();const project=await call("captions_apply",{project_id:S.project.id,job_id:job.id,expected_revision:S.project.revision,replace:true});closeDialog();setProject(project);S.selection={type:"captions"};renderInspector();toast(`Applied ${cues.length} captions. Review wording and render a fresh preview.`,"success");}catch(error){dialogError(error);if($("caption-apply-draft"))$("caption-apply-draft").disabled=false;}};
  }
  function bindCaptionEvents() {
    $("open-captions").onclick=()=>{S.selection={type:"captions"};renderInspector();renderTimeline();};
    $("review-caption-draft").onclick=()=>reviewCaptionDraft();
    $("inspector-content").addEventListener("click",run(async(event)=>{
      const action=event.target.closest("[data-caption-action]")?.dataset.captionAction;
      if(action==="add")addCaptionDialog();if(action==="import")captionImportDialog();if(action==="export-srt")await exportCaptions("srt");if(action==="export-vtt")await exportCaptions("vtt");if(action==="auto")await autoCaptionsDialog();if(action==="more"){S.captionLimit=(S.captionLimit||50)+50;renderInspector();}
      const remove=event.target.closest("[data-caption-delete]");if(remove)mutate((p)=>{p.captions=p.captions.filter((c)=>c.id!==remove.dataset.captionDelete);});
      const seek=event.target.closest("[data-caption-seek]");if(seek){const cue=S.project.captions.find((c)=>c.id===seek.dataset.captionSeek);if(cue){await seekTimeline(cue.start);S.selection={type:"captions"};renderInspector();}}
    }));
    $("inspector-content").addEventListener("change",(event)=>{const control=event.target.closest("[data-cue-field]");if(!control)return;const id=control.closest("[data-cue]").dataset.cue;const cue=S.project?.captions?.find((c)=>c.id===id);if(!cue)return;const key=control.dataset.cueField,value=key==="text"?control.value.trim():number(control.value,-1);if(key==="text"&&!value||key==="start"&&(value<0||value>=cue.end)||key==="end"&&value<=cue.start){toast("Caption text is required, and its end must follow its start.","error");renderInspector();return;}mutate((p)=>{cue[key]=value;p.captions.sort((a,b)=>a.start-b.start);});});
    $("caption-track").addEventListener("click",run(async(event)=>{const el=event.target.closest("[data-caption]");if(!el)return;const cue=S.project.captions.find((c)=>c.id===el.dataset.caption);if(cue)await seekTimeline(cue.start);S.selection={type:"captions"};renderInspector();}));
  }
  hydrateIcons();bindEvents();bindCaptionEvents();boot();
})();
