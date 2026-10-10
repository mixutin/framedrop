from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath

from .config import Config, StudioError, utcnow

VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".mts", ".m2ts"}
AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus", ".aiff"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif"}
FONT = {".ttf", ".otf"}
LUT = {".cube", ".3dl", ".csp"}
PRESET = {".ffx", ".setting", ".drfx", ".prfpset"}
PROJECT = {".aep", ".aepx", ".drp", ".prproj", ".veg", ".fcpxml"}
_thumbnail_slots = threading.BoundedSemaphore(2)


def classify(relative: str) -> tuple[str, str, bool, str]:
    p = PurePosixPath(relative)
    ext = p.suffix.lower()
    folders = [part.lower() for part in p.parts[:-1]]
    context = "/".join(folders)
    if ext in VIDEO:
        category = "overlay" if any("overlay" in f or "ident background" in f for f in folders) else "footage"
        if category == "footage" and any(f in {"references", "trendy edits"} for f in folders): category = "reference"
        if category == "footage" and any(f in {"renders", "master", "preview"} for f in folders): category = "render"
        return "video", category, True, "Native video; browser playback depends on codec. Rendered previews use H.264."
    if ext in AUDIO:
        return "audio", "sfx" if any(f in {"sfx", "sound effects"} for f in folders) else "music", True, "Native audio"
    if ext in IMAGE:
        category = "overlay" if any(f in {"overlays", "free overlays", "idents", "ident backgrounds"} for f in folders) else "reference"
        return "image", category, True, "Native still image / overlay"
    if ext in FONT: return "font", "font", True, "Native title font"
    if ext in LUT: return "lut", "lut", True, "Native 3D color LUT"
    if ext in PRESET:
        requirement = "After Effects animation preset; requires After Effects and its original plugins" if ext == ".ffx" else "DaVinci Resolve/Fusion preset; requires its original OFX/plugins" if ext in {".setting", ".drfx"} else "Premiere Pro effect preset"
        return "preset", "preset", False, requirement + ". Catalog reference; not directly executable in Framedrop."
    if ext in PROJECT: return "project", "project", False, "External editor project. Catalog reference; use original editing application."
    if ext == ".zip": return "archive", "archive", False, "Browse and import selected media or fonts without extracting the whole archive."
    if ext == ".json" and "templates" in folders: return "recipe", "recipe", False, "Documented local effect recipe. See native equivalents; source scripts are not executed."
    if ext == ".py" and "templates" in folders: return "reference", "recipe", False, "Local effect implementation source. Catalog reference; source scripts are not executed."
    return "", "", False, ""


class AssetLibrary:
    def __init__(self, config: Config):
        self.config = config
        self.db = config.state_dir / "assets.sqlite3"
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, relative_path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, category TEXT NOT NULL, extension TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, supported INTEGER NOT NULL, compatibility TEXT NOT NULL, metadata TEXT, present INTEGER NOT NULL DEFAULT 1)")
            conn.execute("CREATE INDEX IF NOT EXISTS asset_kind ON assets(kind,category,present)")

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _contain(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.config.media_root):
            raise StudioError("Asset resolves outside the configured media folder", "path_not_allowed", 403)
        return resolved

    @staticmethod
    def _dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["supported"] = bool(item["supported"])
        item["metadata"] = json.loads(item["metadata"]) if item.get("metadata") else None
        item["modified_at"] = item.pop("mtime_ns") / 1e9
        item.pop("present", None)
        return item

    def _add(self, conn, path: Path) -> tuple[str | None, bool]:
        resolved = self._contain(path)
        if not resolved.is_file(): return None, False
        rel = str(path.relative_to(self.config.media_root))
        kind, category, supported, compatibility = classify(rel)
        if not kind: return None, False
        info = path.stat()
        aid = hashlib.sha256(rel.encode()).hexdigest()[:24]
        previous = conn.execute("SELECT size,mtime_ns FROM assets WHERE id=?", (aid,)).fetchone()
        changed = not previous or previous["size"] != info.st_size or previous["mtime_ns"] != info.st_mtime_ns
        conn.execute("""INSERT INTO assets (id,path,relative_path,name,kind,category,extension,size,mtime_ns,supported,compatibility,present)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET path=excluded.path,name=excluded.name,kind=excluded.kind,category=excluded.category,size=excluded.size,mtime_ns=excluded.mtime_ns,supported=excluded.supported,compatibility=excluded.compatibility,present=1""",
            (aid,str(path),rel,path.name,kind,category,path.suffix.lower(),info.st_size,info.st_mtime_ns,int(supported),compatibility))
        if changed: conn.execute("UPDATE assets SET metadata=NULL WHERE id=?",(aid,))
        return aid, changed

    def scan(self) -> dict:
        started = time.monotonic(); added = updated = ignored = 0
        with self.connect() as conn:
            previous = {r[0] for r in conn.execute("SELECT id FROM assets")}
            conn.execute("UPDATE assets SET present=0")
            for base, dirs, names in os.walk(self.config.media_root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__" and (Path(base)/d).resolve() != self.config.workspace and not (Path(base)/d).is_symlink())
                for name in sorted(names):
                    if name.startswith("."): continue
                    try:
                        aid, changed = self._add(conn, Path(base)/name)
                        if aid and aid not in previous: added += 1
                        elif changed: updated += 1
                        elif aid is None: ignored += 1
                    except (OSError, StudioError): ignored += 1
            missing = conn.execute("SELECT count(*) FROM assets WHERE present=0").fetchone()[0]
        summary = self.list(limit=1)
        return {"total":summary["total"],"counts":summary["counts"],"added":added,"updated":updated,"missing":missing,"ignored":ignored,"elapsed":round(time.monotonic()-started,3)}

    def list(self, query: str = "", kind: str = "", category: str = "", limit: int = 60, offset: int = 0) -> dict:
        limit = max(1,min(200,int(limit))); offset = max(0,int(offset))
        where = ["present=1"]; values = []
        if query:
            query = str(query)[:500].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("relative_path LIKE ? ESCAPE '\\'"); values.append("%"+query+"%")
        if kind: where.append("kind=?"); values.append(kind)
        if category: where.append("category=?"); values.append(category)
        clause = " AND ".join(where)
        with self.connect() as conn:
            count = conn.execute("SELECT count(*) FROM assets WHERE "+clause, values).fetchone()[0]
            rows = conn.execute("SELECT * FROM assets WHERE "+clause+" ORDER BY CASE category WHEN 'footage' THEN 0 WHEN 'overlay' THEN 1 WHEN 'music' THEN 2 WHEN 'sfx' THEN 3 ELSE 4 END,relative_path COLLATE NOCASE LIMIT ? OFFSET ?",[*values,limit,offset]).fetchall()
            counts = {r[0]:r[1] for r in conn.execute("SELECT category,count(*) FROM assets WHERE present=1 GROUP BY category")}
        return {"items":[self._dict(r) for r in rows],"total":count,"counts":counts}

    def get(self, asset_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM assets WHERE id=? AND present=1", (asset_id,)).fetchone()
        if not row: raise StudioError("Unknown asset ID. Scan the media folder and use assets_list to find the asset.","asset_not_found",404)
        asset = self._dict(row); path=self._contain(Path(asset["path"]))
        if not path.is_file(): raise StudioError("Asset file is missing; rescan the library.", "asset_missing",404)
        return asset

    def probe(self, asset_id: str) -> dict:
        from .engine import probe
        item = self.get(asset_id)
        if item["kind"] not in {"video","audio","image"}: return item
        info = Path(item["path"]).stat()
        if item["metadata"] and info.st_size == item["size"] and abs(info.st_mtime-item["modified_at"]) < .001: return item
        metadata = probe(item["path"])
        with self.connect() as conn:
            conn.execute("UPDATE assets SET metadata=?,size=?,mtime_ns=? WHERE id=?", (json.dumps(metadata),info.st_size,info.st_mtime_ns,asset_id))
        item["metadata"] = metadata
        return item

    def thumbnail(self, asset_id: str, at: float = 0) -> Path:
        item=self.get(asset_id)
        if item["kind"] not in {"video","image","audio"}: raise StudioError("This asset has no visual preview", "no_preview",404)
        at=max(0,float(at))
        signature=f"{asset_id}-{item['modified_at']}-{at:.2f}"
        target=self.config.cache_dir/(hashlib.sha256(signature.encode()).hexdigest()[:32]+".jpg")
        if target.is_file(): return target
        with _thumbnail_slots:
            if target.is_file(): return target
            args=[self.config.ffmpeg,"-nostdin","-hide_banner","-loglevel","error","-threads","2","-filter_threads","1","-y"]
            if item["kind"] == "video": args += ["-ss",str(at)]
            if item["kind"] == "audio":
                args += ["-t","30","-i",item["path"],"-filter_complex_threads","1","-filter_complex","showwavespic=s=480x240:colors=0xbca4ff","-frames:v","1"]
            else:
                args += ["-i",item["path"],"-vf","scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2:color=0x111217","-frames:v","1"]
            args += ["-q:v","4",str(target)]
            try: result=subprocess.run(args,capture_output=True,timeout=35)
            except subprocess.TimeoutExpired as exc: raise StudioError("Preview took too long", "preview_timeout",504) from exc
            if result.returncode or not target.is_file():
                target.unlink(missing_ok=True)
                raise StudioError("Cannot create a preview: "+result.stderr.decode(errors="replace")[-600:],"preview_failed")
        return target

    def archive_list(self, asset_id: str, limit: int = 200, offset: int = 0) -> dict:
        item=self.get(asset_id)
        if item["extension"]!=".zip": raise StudioError("Only ZIP archives are supported")
        with zipfile.ZipFile(item["path"]) as archive:
            infos=[i for i in archive.infolist() if not i.is_dir()]
            entries=[{"name":i.filename,"size":i.file_size,"kind":classify(i.filename)[0] or "other","supported":classify(i.filename)[0] in {"video","audio","image","font","lut"}} for i in infos[max(0,int(offset)):max(0,int(offset))+max(1,min(200,int(limit)))]]
        return {"entries":entries,"total":len(infos)}

    def archive_extract(self, asset_id: str, members: list[str]) -> dict:
        item=self.get(asset_id)
        if item["extension"]!=".zip": raise StudioError("Only ZIP archives are supported")
        if not members or len(members)>50: raise StudioError("Choose between 1 and 50 archive members")
        destination=self.config.media_root/"MontageImports"/asset_id
        plans=[]

        def existing_matches(target: Path, info: zipfile.ZipInfo) -> bool:
            if not target.exists(): return False
            mismatch="An imported file already exists with different contents: "+info.filename
            if not target.is_file() or target.stat().st_size!=info.file_size: raise StudioError(mismatch)
            checksum=0; size=0
            with target.open("rb") as existing:
                while chunk:=existing.read(1024*1024):
                    size+=len(chunk)
                    checksum=zlib.crc32(chunk,checksum)
                    if size>info.file_size: raise StudioError(mismatch)
            if size!=info.file_size or (checksum & 0xffffffff)!=info.CRC: raise StudioError(mismatch)
            return True

        with zipfile.ZipFile(item["path"]) as archive:
            for name in dict.fromkeys(members):
                part=PurePosixPath(name)
                if part.is_absolute() or ".." in part.parts or "\\" in name or re.match(r"^[A-Za-z]:",name): raise StudioError("Unsafe archive member path")
                info=archive.getinfo(name)
                if info.is_dir() or stat.S_ISLNK(info.external_attr>>16): raise StudioError("Archive directories and symbolic links are not imported")
                if classify(name)[0] not in {"video","audio","image","font","lut"}: raise StudioError("Only video, audio, images, fonts and LUTs may be imported")
                target=self._contain(destination/name)
                if info.file_size>2*1024**3: raise StudioError("Selected archive member exceeds the 2 GiB import limit")
                plans.append((info,target))
            if sum(i.file_size for i,p in plans)>4*1024**3: raise StudioError("Selected files exceed the 4 GiB batch import limit")
            ids=[]
            for info,target in plans:
                target.parent.mkdir(parents=True,exist_ok=True)
                if not existing_matches(target,info):
                    fd,temporary_name=tempfile.mkstemp(prefix=".montage-import-",suffix=".tmp",dir=target.parent)
                    temporary=Path(temporary_name)
                    try:
                        written=0
                        with os.fdopen(fd,"wb") as dest, archive.open(info) as source:
                            while chunk:=source.read(1024*1024):
                                written+=len(chunk)
                                if written>info.file_size: raise StudioError("Archive member exceeded its declared size")
                                dest.write(chunk)
                            if written!=info.file_size: raise StudioError("Archive member did not match its declared size")
                            dest.flush();os.fsync(dest.fileno())
                        # Atomic no-replace publication: a concurrent import or
                        # user-created destination must never be overwritten.
                        try: os.link(temporary,target)
                        except FileExistsError: existing_matches(target,info)
                    finally: temporary.unlink(missing_ok=True)
                with self.connect() as conn:
                    aid,_=self._add(conn,target)
                    ids.append(aid)
        return {"assets":[self.get(aid) for aid in ids]}
