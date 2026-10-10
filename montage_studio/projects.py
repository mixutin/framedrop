from __future__ import annotations

import copy
import fcntl
import json
import math
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import Config, StudioError, atomic_json, utcnow


def identifier(value: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",value):
        raise StudioError("Invalid identifier")
    return value


def new_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:16]


def finite(value, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value,bool): raise StudioError(f"{name} must be a number")
    try: number=float(value)
    except (ValueError,TypeError) as exc: raise StudioError(f"{name} must be a number") from exc
    if not math.isfinite(number) or not minimum<=number<=maximum:
        raise StudioError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


class ProjectStore:
    def __init__(self, config: Config, library):
        self.config=config
        self.library=library

    def path(self, project_id: str) -> Path:
        return self.config.projects_dir / (identifier(project_id)+".json")

    @contextmanager
    def lock(self, project_id: str):
        location=self.config.history_dir/identifier(project_id)
        location.mkdir(parents=True,exist_ok=True)
        with (location/"write.lock").open("a+") as handle:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    def get(self, project_id: str) -> dict:
        path=self.path(project_id)
        if not path.is_file(): raise StudioError("Project not found", "project_not_found",404)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _canvas(canvas: dict) -> dict:
        if not isinstance(canvas,dict): raise StudioError("Canvas must be an object")
        width=int(finite(canvas.get("width",1920),"Width",64,4096))
        height=int(finite(canvas.get("height",1080),"Height",64,4096))
        if width%2 or height%2: raise StudioError("Canvas dimensions must be even numbers for H.264")
        fps=finite(canvas.get("fps",30),"Frame rate",1,120)
        fit=canvas.get("fit","cover")
        if fit not in {"cover","contain"}: raise StudioError("Canvas fit must be cover or contain")
        background=canvas.get("background","#101014")
        if not isinstance(background,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",background): raise StudioError("Canvas background must be a six-digit hex color")
        return {"width":width,"height":height,"fps":fps,"fit":fit,"background":background}

    def _prepare(self, document: dict) -> dict:
        if not isinstance(document,dict): raise StudioError("Project must be an object")
        try: data=json.loads(json.dumps(document,allow_nan=False))
        except (ValueError,TypeError) as exc: raise StudioError("Project must contain finite JSON values") from exc
        if data.get("schema_version",1)!=1: raise StudioError("Unsupported project schema version")
        data["schema_version"]=1
        name=data.get("name","")
        if not isinstance(name,str) or not name.strip() or len(name)>120: raise StudioError("Choose a project name from 1 to 120 characters")
        data["name"]=name.strip()
        data["canvas"]=self._canvas(data.get("canvas",{}))
        for collection,limit in [("clips",150),("audio",64),("overlays",64),("shapes",64),("titles",64),("captions",2000),("accents",128),("markers",300)]:
            data.setdefault(collection,[])
            if not isinstance(data[collection],list) or len(data[collection])>limit: raise StudioError(f"{collection} must be an array with at most {limit} items")
            if any(not isinstance(x,dict) for x in data[collection]): raise StudioError(f"Each {collection} entry must be an object")
            if collection!="markers":
                ids=[identifier(item.get("id","")) for item in data[collection]]
                if len(ids)!=len(set(ids)): raise StudioError(f"Duplicate IDs in {collection}")
        data["normalize_audio"]=bool(data.get("normalize_audio",True))
        from .captions import DEFAULT_STYLE
        data.setdefault("caption_style",DEFAULT_STYLE.copy())
        from .engine import validate_project
        validation=validate_project(data,self.library.get)
        if not validation["valid"]:
            raise StudioError("Invalid project: "+"; ".join(str(e) for e in validation.get("errors",[])[:8]),"invalid_project")
        return data

    def _new_document(self,name: str,width: int=1920,height: int=1080,fps: float=30) -> dict:
        """Build a new project without touching persistent storage."""
        now=utcnow()
        data={"schema_version":1,"id":new_id("p"),"name":name,"revision":0,"created_at":now,"updated_at":now,"canvas":self._canvas({"width":width,"height":height,"fps":fps}),"clips":[],"audio":[],"overlays":[],"shapes":[],"titles":[],"accents":[],"markers":[],"normalize_audio":True}
        if not isinstance(name,str) or not name.strip() or len(name)>120: raise StudioError("Choose a project name from 1 to 120 characters")
        data["name"]=name.strip()
        return data

    def _persist_new(self,data: dict) -> dict:
        with self.lock(data["id"]):
            atomic_json(self.path(data["id"]),data)
            atomic_json(self.config.history_dir/data["id"]/"0.json",data)
        return data

    def create(self,name: str,width: int=1920,height: int=1080,fps: float=30) -> dict:
        return self._persist_new(self._new_document(name,width,height,fps))

    def list(self) -> list[dict]:
        from .engine import project_duration
        summaries=[]
        for path in self.config.projects_dir.glob("*.json"):
            try:
                p=json.loads(path.read_text())
                summaries.append({k:p[k] for k in ["id","name","revision","canvas","updated_at"]}|{"clip_count":len(p.get("clips",[])),"duration":project_duration(p)})
            except (OSError,ValueError,KeyError): continue
        return sorted(summaries,key=lambda x:x["updated_at"],reverse=True)

    def save(self,project: dict,expected_revision: int) -> dict:
        if not isinstance(project,dict): raise StudioError("Project must be an object")
        project_id=identifier(project.get("id",""))
        if not isinstance(expected_revision,int) or isinstance(expected_revision,bool): raise StudioError("expected_revision must be the current integer revision")
        prepared=self._prepare(project)
        with self.lock(project_id):
            current=self.get(project_id)
            if current["revision"]!=expected_revision:
                raise StudioError(f"Project changed since it was loaded (current revision {current['revision']}, supplied {expected_revision}). Reload before applying your changes.","revision_conflict",409)
            prepared.update({"id":project_id,"created_at":current["created_at"],"updated_at":utcnow(),"revision":current["revision"]+1})
            atomic_json(self.config.history_dir/project_id/(str(current["revision"])+".json"),current)
            atomic_json(self.path(project_id),prepared)
            atomic_json(self.config.history_dir/project_id/(str(prepared["revision"])+".json"),prepared)
        return prepared

    def history(self,project_id: str) -> dict:
        self.get(project_id)
        records=[]
        for path in (self.config.history_dir/project_id).glob("*.json"):
            try:
                p=json.loads(path.read_text());records.append({"revision":p["revision"],"updated_at":p["updated_at"],"name":p["name"],"clip_count":len(p.get("clips",[]))})
            except (OSError,ValueError,KeyError): continue
        return {"revisions":sorted(records,key=lambda p:p["revision"],reverse=True)}

    def restore(self,project_id: str,revision: int,expected_revision: int) -> dict:
        identifier(project_id)
        if not isinstance(revision,int) or revision<0: raise StudioError("Invalid revision")
        path=self.config.history_dir/project_id/(str(revision)+".json")
        if not path.is_file(): raise StudioError("Saved revision not found","revision_not_found",404)
        return self.save(json.loads(path.read_text()),expected_revision)

    def _default_clip(self,clip: dict) -> dict:
        asset=self.library.probe(clip.get("asset_id",""))
        if asset["kind"] not in {"video","image"}: raise StudioError("Clips require a video or image asset")
        metadata=asset.get("metadata") or {}
        source_duration=metadata.get("duration") or 4
        defaults={"id":new_id("c"),"in":0,"out":min(4,source_duration),"speed":1,"volume":1,"fit":"cover","effects":[],"transition":{"name":"cut","duration":0},"segments":[]}
        return defaults|clip

    def edit(self,project_id: str,expected_revision: int,operations: list[dict]) -> dict:
        data=self.get(project_id)
        if not isinstance(operations,list) or not operations or len(operations)>300: raise StudioError("Provide between 1 and 300 edit operations")
        for op in operations:
            if not isinstance(op,dict): raise StudioError("Every operation must be an object")
            action=op.get("op","")
            if action=="set_canvas": data["canvas"]={**data["canvas"],**op.get("canvas",{})};continue
            if action=="set_export_profile": data["export_profile"]=op.get("export_profile");continue
            if action=="set_caption_style": data["caption_style"]={**data.get("caption_style",{}),**op.get("caption_style",{})};continue
            if action=="rename": data["name"]=op.get("name");continue
            if action=="set_markers": data["markers"]=op.get("markers");continue
            if action=="reorder_clips":
                ids=op.get("clip_ids",[]); existing={x["id"]:x for x in data["clips"]}
                if len(ids)!=len(existing) or len(set(ids))!=len(ids) or set(ids)!=set(existing): raise StudioError("reorder_clips must list every clip ID exactly once")
                data["clips"]=[existing[x] for x in ids];continue
            match=re.fullmatch(r"(add|update|remove)_(clip|audio|overlay|shape|title|caption|accent)",action)
            if not match: raise StudioError("Unknown edit operation: "+str(action))
            mode,kind=match.groups(); collection={"clip":"clips","audio":"audio","overlay":"overlays","shape":"shapes","title":"titles","caption":"captions","accent":"accents"}[kind]
            data.setdefault(collection,[])
            if mode=="add":
                value=op.get(kind)
                if not isinstance(value,dict): raise StudioError(f"add_{kind} requires a {kind} object")
                if kind=="clip": value=self._default_clip(value)
                else:
                    defaults={"id":new_id(kind[0]),"start":0}
                    if kind=="audio":
                        a=self.library.probe(value.get("asset_id","")); duration=(a.get("metadata") or {}).get("duration") or 4
                        defaults|={"in":0,"out":min(10,duration),"volume":.7,"fade_in":.1,"fade_out":.3,"loop":False}
                    if kind=="overlay": defaults|={"in":0,"duration":2,"opacity":.6,"blend":"screen","width":1,"x":.5,"y":.5,"loop":False}
                    if kind=="shape": defaults|={"kind":"ellipse","duration":2,"x":.3,"y":.3,"x2":.7,"y2":.7,"color":"#ff3030","stroke_width":12,"opacity":1}
                    if kind=="accent": defaults|={"kind":"impact_ring","duration":.4,"size":.25,"x":.5,"y":.5,"color":"#ff62c6","opacity":.8,"rotation":0}
                    if kind=="title": defaults|={"text":"Title","duration":2,"font_asset_id":None,"font_size":64,"x":.5,"y":.8,"color":"#ffffff","box":True,"fade":.15}
                    if kind=="caption": defaults|={"text":"Caption","end":2}
                    value=defaults|value
                position=int(op.get("index",len(data[collection])))
                if not 0<=position<=len(data[collection]): raise StudioError("Insert index is out of range")
                data[collection].insert(position,value)
            else:
                key=kind+"_id"; selected=next((item for item in data[collection] if item["id"]==op.get(key)),None)
                if selected is None: raise StudioError(f"Unknown {kind} ID", "item_not_found",404)
                if mode=="remove": data[collection].remove(selected)
                else:
                    changes=op.get("changes",{})
                    if not isinstance(changes,dict) or "id" in changes: raise StudioError("Changes must be an object without an id field")
                    selected.update(changes)
        return self.save(data,expected_revision)

    def montage(self,name: str,asset_ids: list[str],music_asset_id: str|None=None,bpm: float=120,beat_offset: float=0,beats_per_cut: float=4,duration: float=16,width: int=1920,height: int=1080,fps: float=30,style: str="clean") -> dict:
        if not isinstance(asset_ids,list) or not asset_ids or len(asset_ids)>100: raise StudioError("Select 1 to 100 source videos or images")
        bpm=finite(bpm,"BPM",30,300);duration=finite(duration,"Duration",1,300)
        interval=60/bpm*finite(beats_per_cut,"Beats per cut",.25,16)
        beat_offset=finite(beat_offset,"Beat offset",0,600)
        if style not in {"clean","impact","cinematic"}: raise StudioError("Unknown montage style")
        assets=[self.library.probe(aid) for aid in asset_ids]
        if any(a["kind"] not in {"video","image"} for a in assets): raise StudioError("Montage sources must be video or image assets")
        # Validate soundtrack before creating a project, avoiding partial projects on invalid input.
        music=self.library.probe(music_asset_id) if music_asset_id else None
        if music and music["kind"] not in {"video","audio"}: raise StudioError("Soundtrack must contain audio")
        if music and not (music.get("metadata") or {}).get("has_audio"): raise StudioError("Soundtrack has no audio stream")
        available=((music.get("metadata") or {}).get("duration") or 0) if music else 0
        if music and available<=beat_offset: raise StudioError("Soundtrack offset is past the end of the audio")
        project=self._new_document(name,width,height,fps)
        cursor=0; index=0
        while cursor<duration-.001:
            if index>=150: raise StudioError("Beat spacing would create more than 150 clips; increase beats_per_cut")
            asset=assets[index%len(assets)]; source_duration=(asset.get("metadata") or {}).get("duration") or duration
            timed_media=asset["kind"]=="video" or asset.get("extension")==".gif"
            length=min(interval,duration-cursor,source_duration) if timed_media else min(interval,duration-cursor)
            if length<.05: raise StudioError("A source clip is too short for montage generation")
            start=round(max(0,source_duration-length)*.18,4) if timed_media else 0
            effects=[]
            if style=="impact": effects=[{"name":"punchy","strength":.55},{"name":"impact","strength":.5}] if index%2==0 else [{"name":"punchy","strength":.5}]
            if style=="cinematic": effects=[{"name":"cinematic","strength":.6},{"name":"vignette","strength":.4}]
            project["clips"].append(self._default_clip({"asset_id":asset["id"],"in":start,"out":start+length,"volume":0 if music else 1,"effects":effects}))
            project["markers"].append({"time":round(cursor,4),"label":f"Cut {index+1}"})
            cursor+=length;index+=1
        if music:
            project["audio"].append({"id":new_id("a"),"asset_id":music["id"],"start":0,"in":beat_offset,"out":min(available,beat_offset+duration),"duration":duration,"volume":.8,"fade_in":.08,"fade_out":.4,"loop":available-beat_offset<duration})
        project["montage_grid"]={"bpm":bpm,"beats_per_cut":beats_per_cut,"beat_offset":beat_offset,"method":"Explicit tempo grid. Analyze music first to choose BPM and offset."}
        # All montage construction and render validation finish before the first
        # write, so rejected settings cannot leave behind empty projects/history.
        return self._persist_new(self._prepare(project))
