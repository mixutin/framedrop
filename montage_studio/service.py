from __future__ import annotations

import json
import math
import subprocess

from . import __version__
from .assets import AssetLibrary
from .config import Config, StudioError
from .jobs import JobManager
from .projects import ProjectStore
from .tools import BY_NAME


COMPATIBILITY={
    "native":"Footage, images, music, sound effects, screen/add/alpha/chroma overlays, fonts, LUTs and built-in FFmpeg effects.",
    "external_presets":"After Effects .ffx/.aep and Resolve/Fusion .setting files are catalogued with their host/plugin requirements. They cannot be executed natively by this editor.",
    "recipes":"Existing Python/JSON effect templates are catalogued as references. Native equivalents are recreated implementations, not exact preset conversion; arbitrary scripts are not executed.",
    "preview":"The source player shows original media. Render Preview to see the complete timeline, compositing, speed effects and audio mix.",
}


def validate_arguments(value,schema,path="arguments"):
    expected=schema.get("type")
    matches={"object":isinstance(value,dict),"array":isinstance(value,list),"string":isinstance(value,str),"number":isinstance(value,(int,float)) and not isinstance(value,bool),"integer":isinstance(value,int) and not isinstance(value,bool),"boolean":isinstance(value,bool)}
    if expected and not matches.get(expected,True): raise StudioError(f"{path} must be {expected}")
    if expected in {"integer","number"}:
        if not math.isfinite(value): raise StudioError(f"{path} must be finite")
        if "minimum" in schema and value<schema["minimum"]: raise StudioError(f"{path} must be at least {schema['minimum']}")
        if "maximum" in schema and value>schema["maximum"]: raise StudioError(f"{path} must be at most {schema['maximum']}")
    if "enum" in schema and value not in schema["enum"]: raise StudioError(f"{path} must be one of: {', '.join(map(str,schema['enum']))}")
    if expected=="string":
        if len(value)<schema.get("minLength",0) or len(value)>schema.get("maxLength",20000): raise StudioError(f"{path} has an invalid length")
    if expected=="object":
        for required in schema.get("required",[]):
            if required not in value: raise StudioError(f"Missing required field: {path}.{required}")
        props=schema.get("properties",{})
        if schema.get("additionalProperties") is False:
            unknown=set(value)-set(props)
            if unknown: raise StudioError("Unknown field(s): "+", ".join(sorted(unknown)))
        for name,item in value.items():
            if name in props: validate_arguments(item,props[name],path+"."+name)
    if expected=="array":
        if len(value)<schema.get("minItems",0) or len(value)>schema.get("maxItems",10000): raise StudioError(f"{path} has an invalid number of items")
        for index,item in enumerate(value): validate_arguments(item,schema.get("items",{}),f"{path}[{index}]")


class Service:
    def __init__(self,config: Config|None=None):
        self.config=config or Config.load();self.config.ensure()
        self.library=AssetLibrary(self.config)
        self.projects=ProjectStore(self.config,self.library)
        self.jobs=JobManager(self.config,self.library,self.projects)

    def status(self) -> dict:
        deps=self.config.dependency_status()
        return {"app":"Framedrop","version":__version__,"media_root":str(self.config.media_root),"workspace":str(self.config.workspace),"ffmpeg":deps["ffmpeg"],"ffprobe":deps["ffprobe"],"asset_count":self.library.list(limit=1)["total"],"project_count":len(self.projects.list()),"running_jobs":len([j for j in self.jobs.list() if j["status"] in {"queued","running"}]),"capabilities":["Non-destructive JSON timelines","MCP stdio","CLI automation","Local visual editor","Sequential FFmpeg exports","Effects and overlays","Native freeze frames","Animated pan and zoom","Timed effects","Animated neon lyrics and titles","Native kill accents and light sweeps","Eased keyframes","Word-level transcription","Optional optical-flow slow motion","Motion-compensated two-sample blur","High-quality export profile","Native arrows, circles and rectangles","Audio gain keyframes","Local file import","Optional offline background removal","Velocity segments","Music and SFX","Text and fonts","Color correction and LUTs","Crop, zoom, rotation and flips","Audio fades and loudness normalization","Manual captions and SRT/VTT import/export","Optional offline speech transcription","Tempo-grid montages","Asset archive browsing"],"limits":{"parallel_renders":1,"default_ffmpeg_threads":self.config.threads,"preview_longest_edge":960},"compatibility":COMPATIBILITY}

    def call(self,name: str,arguments: dict|None=None) -> dict:
        definition=BY_NAME.get(name)
        if not definition: raise StudioError("Unknown tool: "+str(name),"unknown_tool",404)
        args={} if arguments is None else arguments
        validate_arguments(args,definition["inputSchema"])
        if name=="system_status": return self.status()
        if name=="library_scan": return self.library.scan()
        if name=="assets_list": return self.library.list(**args)
        if name=="asset_import":
            from .media_tools import import_asset
            return import_asset(self.library,**args)
        if name=="background_removal_status":
            from .media_tools import background_status
            return background_status(self.config)
        if name=="image_background_remove":
            from .media_tools import background_remove
            return background_remove(self,**args)
        if name=="asset_probe": return self.library.probe(args["asset_id"])
        if name=="asset_preview":
            path=self.library.thumbnail(args["asset_id"],args.get("time",0))
            return {"path":str(path),"mime_type":"image/jpeg","asset_id":args["asset_id"],"time":args.get("time",0),"note":"Local preview image; inspect with the host's image viewer."}
        if name=="effects_list":
            from .effects import list_effects, TRANSITIONS
            from .graphics import ACCENTS, ANIMATIONS
            from .automation import EASINGS
            return {"effects":list_effects(),"transitions":list(TRANSITIONS),"accents":list(ACCENTS),
                    "text_animations":list(ANIMATIONS),"caption_presets":["clean","bold","boxed","neon"],
                    "easing":list(EASINGS),"interpolation":["duplicate","optical_flow"],
                    "export_profiles":{"standard":{"intermediate_crf":16,"final_crf":18},"high":{"intermediate_crf":12,"final_crf":16}},
                    "compatibility":COMPATIBILITY}
        if name=="project_list": return {"projects":self.projects.list()}
        if name=="project_create": return self.projects.create(**args)
        if name=="project_get": return self.projects.get(**args)
        if name=="project_save": return self.projects.save(**args)
        if name=="project_edit": return self.projects.edit(**args)
        if name=="project_history": return self.projects.history(**args)
        if name=="project_restore": return self.projects.restore(**args)
        if name=="project_validate":
            from .engine import validate_project
            return validate_project(self.projects.get(args["project_id"]),self.library.get)
        if name=="analyze_media":
            from .analysis import analyze
            asset=self.library.get(args["asset_id"])
            if asset["kind"] not in {"video","audio"}: raise StudioError("Analysis requires a video or audio asset")
            return analyze(asset["path"],args.get("mode","beats"),start=args.get("start",0),duration=args.get("duration",120),work_dir=str(self.config.cache_dir/"analysis"))
        if name=="montage_create": return self.projects.montage(**args)
        if name=="render_plan":
            from .engine import render_plan
            return render_plan(self.projects.get(args["project_id"]),self.library.get,args.get("quality","preview"))
        if name=="render_start": return self.jobs.start(**args)
        if name=="job_status": return self.jobs.get(**args)
        if name=="jobs_list": return {"jobs":self.jobs.list()}
        if name=="job_cancel": return self.jobs.cancel(**args)
        if name=="archive_list": return self.library.archive_list(**args)
        if name=="archive_extract": return self.library.archive_extract(**args)
        if name=="captions_import":
            from .captions import import_project
            return import_project(self.projects,**args)
        if name=="captions_export":
            from .captions import export_project
            return export_project(self.projects,**args)
        if name=="transcription_status":
            from .transcription import status
            return status(self.config)
        if name=="captions_transcribe":
            from .transcription import start
            return start(self,**args)
        if name=="captions_apply":
            from .transcription import apply
            return apply(self,**args)
        raise StudioError("Tool has no implementation: "+name,"internal_error",500)
