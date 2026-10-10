"""Explicit media imports and optional local background-removal jobs."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import threading
import traceback

from .assets import VIDEO, AUDIO, IMAGE, FONT, LUT
from .config import Config, StudioError, atomic_json, utcnow
from .jobs import process_identity
from .projects import new_id


def import_asset(library, path: str) -> dict:
    """Copy a deliberately selected regular file; never mutate the source."""
    source = Path(path).expanduser()
    if not source.is_absolute():
        raise StudioError("Import requires the absolute path of a user-selected file")
    source = source.resolve(strict=True)
    if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
        raise StudioError("Import requires a regular media file")
    suffix = source.suffix.lower()
    with source.open("rb") as handle:
        signature = handle.read(16)
    if suffix not in VIDEO | AUDIO | IMAGE | FONT | LUT:
        if signature.startswith(b"\xff\xd8\xff"): suffix = ".jpg"
        elif signature.startswith(b"\x89PNG\r\n\x1a\n"): suffix = ".png"
        elif signature[:4] == b"RIFF" and signature[8:12] == b"WEBP": suffix = ".webp"
        else: raise StudioError("Unsupported media, font or LUT file")
    if not 0 < source.stat().st_size <= 20 * 1024**3:
        raise StudioError("Import files must be nonempty and at most 20 GiB")
    if source.is_relative_to(library.config.media_root) and source.suffix.lower() == suffix:
        target = source
    else:
        directory = library.config.media_root / "MontageImports" / "media"
        # A configured library can contain symlinks; validate before any writes.
        library._contain(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w .-]", "_", source.stem)[:90] or "media"
        target = directory / f"{stem}-{new_id('import')}{suffix}"
        before = source.stat()
        created = False
        try:
            with source.open("rb") as src, target.open("xb") as dst:
                created = True
                shutil.copyfileobj(src, dst, length=1024*1024)
            after = source.stat()
            if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
                raise StudioError("Source changed during import; retry after it finishes saving")
        except BaseException:
            if created: target.unlink(missing_ok=True)
            raise
    with library.connect() as connection:
        asset_id, _ = library._add(connection, target)
    if not asset_id: raise StudioError("Could not index imported media")
    return library.get(asset_id)


def background_status(config: Config) -> dict:
    settings_file = config.state_dir / "background-removal.json"
    if not settings_file.is_file():
        return {"installed":False,"model_ready":False,"model":"isnet-general-use",
                "message":"Install the optional local cutout engine with python3 setup_background.py --python python3.12"}
    settings = json.loads(settings_file.read_text())
    settings["installed"] = Path(settings.get("python", "")).is_file()
    settings["model_ready"] = bool(settings["installed"] and any(Path(settings.get("model_dir", "")).glob("**/isnet-general-use.onnx")))
    return settings


def background_remove(service, asset_id: str) -> dict:
    settings = background_status(service.config)
    if not settings["model_ready"]:
        raise StudioError(settings.get("message", "Local cutout model is not installed"), "cutout_unavailable", 409)
    asset = service.library.probe(asset_id)
    if asset["kind"] != "image" or asset["extension"] == ".gif":
        raise StudioError("Background removal requires a still image")
    meta = asset["metadata"]
    if meta["width"] * meta["height"] > 24_000_000:
        raise StudioError("Cutouts are limited to 24 megapixels")
    with service.jobs.lock(service.config.state_dir / "render-start.lock"):
        if any(j["status"] in {"queued", "running"} for j in service.jobs.list()):
            raise StudioError("Wait for the current media job or cancel it first", "render_busy", 409)
        jid = new_id("job")
        directory = service.jobs.directory(jid)
        directory.mkdir()
        job = {"id":jid,"kind":"background_removal","project_id":None,"project_name":asset["name"],
               "status":"queued","quality":"cutout","progress":0,"message":"Preparing image cutout",
               "created_at":utcnow(),"updated_at":utcnow(),"asset_id":asset_id}
        atomic_json(directory/"job.json", job)
        atomic_json(directory/"config.json", service.config.as_dict())
        atomic_json(directory/"settings.json", settings)
        root = str(Path(__file__).resolve().parent.parent)
        env = os.environ.copy()
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        env["U2NET_HOME"] = settings["model_dir"]
        env["OMP_NUM_THREADS"] = str(service.config.threads)
        with (directory/"worker.log").open("ab") as log:
            try:
                process = subprocess.Popen([settings["python"], "-m", "montage_studio", "_cutout_worker", str(directory)],
                                           cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           start_new_session=True, close_fds=True)
            except OSError as exc:
                service.jobs.update(jid,status="failed",error=str(exc),message="Could not start cutout worker")
                raise
        result = service.jobs.update(jid,pid=process.pid,pid_identity=process_identity(process.pid)[1])
        threading.Thread(target=process.wait, daemon=True).start()
        return result


def run_cutout_worker(directory: str) -> int:
    from .service import Service
    location = Path(directory).resolve()
    config = Config.from_dict(json.loads((location/"config.json").read_text()))
    if location.parent != config.jobs_dir.resolve(): raise StudioError("Invalid cutout job directory")
    service = Service(config)
    jobs, jid = service.jobs, location.name
    job = jobs.get(jid,check_process=False)
    if job["status"] not in {"queued","running"}: return 0
    stopped = threading.Event()
    output = None
    created = False
    def monitor():
        while not stopped.wait(.2):
            if (location/"cancel.request").exists():
                if output and created: output.unlink(missing_ok=True)
                jobs.update(jid,status="cancelled",message="Image cutout cancelled")
                os._exit(0)
    try:
        with (config.state_dir/"render-worker.lock").open("a+") as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            if (location/"cancel.request").exists(): raise InterruptedError("Image cutout cancelled")
            threading.Thread(target=monitor,daemon=True).start()
            jobs.update(jid,status="running",progress=.1,message="Loading local cutout model")
            settings = json.loads((location/"settings.json").read_text())
            model_dir = Path(settings["model_dir"])
            if not any(model_dir.glob("**/isnet-general-use.onnx")): raise StudioError("Cutout model is missing; run setup_background.py")
            os.environ["U2NET_HOME"] = str(model_dir)
            from rembg import new_session, remove
            from PIL import Image
            image = Image.open(service.library.get(job["asset_id"])["path"])
            if image.width*image.height > 24_000_000: raise StudioError("Image exceeds 24 megapixels")
            session = new_session("isnet-general-use",providers=["CPUExecutionProvider"])
            jobs.update(jid,progress=.35,message="Removing image background")
            cutout = remove(image.convert("RGBA"), session=session)
            out_dir = config.media_root/"MontageImports"/"overlays"
            service.library._contain(out_dir)
            out_dir.mkdir(parents=True,exist_ok=True)
            output = out_dir/f"cutout-{jid}.png"
            # Exclusive destination: repeated jobs never overwrite an existing asset.
            with output.open("xb") as handle:
                created = True
                cutout.save(handle,format="PNG")
            with service.library.connect() as connection: aid,_ = service.library._add(connection,output)
            result={"asset":service.library.get(aid),"path":str(output),"model":"isnet-general-use",
                    "message":"Review the cutout edges before compositing; originals are preserved."}
            jobs.update(jid,status="completed",progress=1,message="Transparent cutout ready",result=result)
            return 0
    except BaseException as exc:
        if output and created: output.unlink(missing_ok=True)
        cancelled=(location/"cancel.request").exists() or isinstance(exc,InterruptedError)
        jobs.update(jid,status="cancelled" if cancelled else "failed",error=str(exc),message="Image cutout cancelled" if cancelled else "Image cutout failed")
        traceback.print_exc()
        return 0 if cancelled else 1
    finally: stopped.set()
