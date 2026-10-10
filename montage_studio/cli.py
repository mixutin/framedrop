from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .config import StudioError


FORMATS={"landscape":(1920,1080),"portrait":(1080,1920),"square":(1080,1080)}


def output(data):
    print(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))


def read_json(value=None,file=None):
    if value is not None: return json.loads(value)
    if file=="-": return json.load(sys.stdin)
    if file:return json.loads(Path(file).expanduser().read_text(encoding="utf-8"))
    return {}


def document_args(parser):
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json",dest="json_text",help="Inline JSON")
    group.add_argument("--file",help="JSON file, or - for stdin")


def canvas_args(parser):
    parser.add_argument("--format",choices=FORMATS,default="landscape")
    parser.add_argument("--width",type=int);parser.add_argument("--height",type=int)
    parser.add_argument("--fps",type=float,default=30)


def canvas_values(args):
    width,height=FORMATS[args.format]
    return {"width":args.width or width,"height":args.height or height,"fps":args.fps}


def build_parser():
    parser=argparse.ArgumentParser(prog="framedrop",description="Framedrop — local video editing through CLI, MCP and a visual workspace.")
    parser.add_argument("--version",action="version",version=f"Framedrop {__version__}")
    parser.add_argument("--config",help="Use an explicit configuration JSON file")
    parser.add_argument("--media-root",help="Override the source media folder")
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("status",help="Inspect dependencies, assets and workspace")
    commands.add_parser("scan",help="Index source media and effect assets")
    commands.add_parser("effects",help="List native effects and compatibility")
    commands.add_parser("tools",help="Print the shared MCP/CLI tool schemas")
    assets=commands.add_parser("assets",help="Search the asset catalog")
    assets.add_argument("query",nargs="?",default="");assets.add_argument("--kind");assets.add_argument("--category");assets.add_argument("--limit",type=int,default=60);assets.add_argument("--offset",type=int,default=0)
    probe=commands.add_parser("probe",help="Probe source media streams");probe.add_argument("asset_id")
    preview=commands.add_parser("preview",help="Create a source preview JPEG");preview.add_argument("asset_id");preview.add_argument("--time",type=float,default=0)
    analyze=commands.add_parser("analyze",help="Estimate beats or find waveform/scene cuts");analyze.add_argument("asset_id");analyze.add_argument("--mode",choices=["beats","waveform","scenes"],default="beats");analyze.add_argument("--start",type=float,default=0);analyze.add_argument("--duration",type=float,default=120)
    call=commands.add_parser("call",help="Call any tool with JSON arguments");call.add_argument("tool");group=call.add_mutually_exclusive_group();group.add_argument("--json",dest="json_text");group.add_argument("--file")
    project=commands.add_parser("project",help="Create, inspect and edit timelines");pc=project.add_subparsers(dest="action",required=True)
    pc.add_parser("list")
    new=pc.add_parser("new");new.add_argument("name");canvas_args(new)
    for name in ["show","validate","history"]:
        sub=pc.add_parser(name);sub.add_argument("project_id")
    edit=pc.add_parser("edit");edit.add_argument("project_id");edit.add_argument("--revision",type=int,required=True);document_args(edit)
    save=pc.add_parser("save");save.add_argument("file");save.add_argument("--revision",type=int,required=True)
    restore=pc.add_parser("restore");restore.add_argument("project_id");restore.add_argument("revision",type=int);restore.add_argument("--expected-revision",type=int,required=True)
    auto=commands.add_parser("auto",help="Create an editable montage on a tempo grid");auto.add_argument("--name",required=True);auto.add_argument("--assets",nargs="+",required=True);auto.add_argument("--music");auto.add_argument("--bpm",type=float,default=120);auto.add_argument("--beat-offset",type=float,default=0);auto.add_argument("--beats-per-cut",type=float,default=4);auto.add_argument("--duration",type=float,default=16);auto.add_argument("--style",choices=["clean","impact","cinematic"],default="clean");canvas_args(auto)
    render=commands.add_parser("render",help="Start an export from a fixed timeline revision");render.add_argument("project_id");render.add_argument("--quality",choices=["preview","final"],default="preview");render.add_argument("--wait",action="store_true");render.add_argument("--plan",action="store_true")
    jobs=commands.add_parser("jobs",help="List jobs or inspect one export");jobs.add_argument("job_id",nargs="?")
    cancel=commands.add_parser("cancel",help="Cancel an active render");cancel.add_argument("job_id")
    archive=commands.add_parser("archive",help="Browse ZIP packs and import selected assets");ac=archive.add_subparsers(dest="action",required=True)
    al=ac.add_parser("list");al.add_argument("asset_id");al.add_argument("--offset",type=int,default=0);al.add_argument("--limit",type=int,default=200)
    ax=ac.add_parser("extract");ax.add_argument("asset_id");ax.add_argument("--member",dest="members",action="append",required=True)
    commands.add_parser("mcp",help="Run the stdio MCP server (stdout is protocol only)")
    captions=commands.add_parser("captions",help="Import, export and generate editable captions");cc=captions.add_subparsers(dest="action",required=True)
    cc.add_parser("status")
    ci=cc.add_parser("import");ci.add_argument("project_id");ci.add_argument("file");ci.add_argument("--revision",type=int,required=True);ci.add_argument("--format",choices=["srt","vtt"]);ci.add_argument("--offset",type=float,default=0);ci.add_argument("--append",action="store_true")
    ce=cc.add_parser("export");ce.add_argument("project_id");ce.add_argument("--format",choices=["srt","vtt"],default="srt")
    ct=cc.add_parser("transcribe");ct.add_argument("project_id");ct.add_argument("--render-job",required=True);ct.add_argument("--language",default="auto");ct.add_argument("--model",choices=["tiny","base","small","medium","large-v3"])
    ca=cc.add_parser("apply");ca.add_argument("project_id");ca.add_argument("job_id");ca.add_argument("--revision",type=int,required=True);ca.add_argument("--append",action="store_true")
    ui=commands.add_parser("ui",help="Run the local visual editor");ui.add_argument("--port",type=int);ui.add_argument("--open",action="store_true",dest="open_browser")
    worker=commands.add_parser("_worker",help=argparse.SUPPRESS);worker.add_argument("directory")
    transcriber=commands.add_parser("_transcribe_worker",help=argparse.SUPPRESS);transcriber.add_argument("directory")
    cutout=commands.add_parser("_cutout_worker",help=argparse.SUPPRESS);cutout.add_argument("directory")
    return parser


def main(argv=None):
    args=build_parser().parse_args(argv)
    if args.config:
        config_path=str(Path(args.config).expanduser().resolve())
        os.environ["FRAMEDROP_CONFIG"]=config_path
        os.environ["MONTAGE_CONFIG"]=config_path
    if args.media_root:os.environ["MONTAGE_MEDIA_ROOT"]=str(Path(args.media_root).expanduser().resolve())
    try:
        if args.command=="_worker":
            from .jobs import run_worker
            return run_worker(args.directory)
        if args.command=="_transcribe_worker":
            from .transcription import run_worker
            return run_worker(args.directory)
        if args.command=="_cutout_worker":
            from .media_tools import run_cutout_worker
            return run_cutout_worker(args.directory)
        if args.command=="mcp":
            from .mcp import serve
            serve();return 0
        if args.command=="tools":
            from .tools import TOOLS
            output({"tools":TOOLS});return 0
        from .service import Service
        service=Service()
        command=args.command;result=None
        if command=="ui":
            from .web import serve
            serve(service,port=args.port,open_browser=args.open_browser);return 0
        if command in {"status","scan","effects"}:result=service.call({"status":"system_status","scan":"library_scan","effects":"effects_list"}[command],{})
        elif command=="assets":result=service.call("assets_list",{k:v for k,v in {"query":args.query,"kind":args.kind,"category":args.category,"limit":args.limit,"offset":args.offset}.items() if v is not None})
        elif command=="probe":result=service.call("asset_probe",{"asset_id":args.asset_id})
        elif command=="preview":result=service.call("asset_preview",{"asset_id":args.asset_id,"time":args.time})
        elif command=="analyze":result=service.call("analyze_media",{"asset_id":args.asset_id,"mode":args.mode,"start":args.start,"duration":args.duration})
        elif command=="call":result=service.call(args.tool,read_json(args.json_text,args.file))
        elif command=="project":
            if args.action=="list":result=service.call("project_list",{})
            elif args.action=="new":result=service.call("project_create",{"name":args.name,**canvas_values(args)})
            elif args.action in {"show","validate","history"}:result=service.call({"show":"project_get","validate":"project_validate","history":"project_history"}[args.action],{"project_id":args.project_id})
            elif args.action=="edit":result=service.call("project_edit",{"project_id":args.project_id,"expected_revision":args.revision,"operations":read_json(args.json_text,args.file)})
            elif args.action=="save":result=service.call("project_save",{"project":read_json(file=args.file),"expected_revision":args.revision})
            elif args.action=="restore":result=service.call("project_restore",{"project_id":args.project_id,"revision":args.revision,"expected_revision":args.expected_revision})
        elif command=="auto":
            values={"name":args.name,"asset_ids":args.assets,"bpm":args.bpm,"beat_offset":args.beat_offset,"beats_per_cut":args.beats_per_cut,"duration":args.duration,"style":args.style,**canvas_values(args)}
            if args.music:values["music_asset_id"]=args.music
            result=service.call("montage_create",values)
        elif command=="render":
            result=service.call("render_plan" if args.plan else "render_start",{"project_id":args.project_id,"quality":args.quality})
            if args.wait and not args.plan:
                last=""
                while result["status"] in {"queued","running"}:
                    message=f"{result['progress']:.0%} {result['message']}"
                    if message!=last:print(message,file=sys.stderr,flush=True);last=message
                    time.sleep(.5)
                    result=service.call("job_status",{"job_id":result["id"]})
                output(result);return 0 if result["status"]=="completed" else 1
        elif command=="jobs":result=service.call("job_status",{"job_id":args.job_id}) if args.job_id else service.call("jobs_list",{})
        elif command=="cancel":result=service.call("job_cancel",{"job_id":args.job_id})
        elif command=="archive":
            result=service.call("archive_list",{"asset_id":args.asset_id,"limit":args.limit,"offset":args.offset}) if args.action=="list" else service.call("archive_extract",{"asset_id":args.asset_id,"members":args.members})
        elif command=="captions":
            if args.action=="status":result=service.call("transcription_status",{})
            elif args.action=="import":result=service.call("captions_import",{"project_id":args.project_id,"expected_revision":args.revision,"text":Path(args.file).expanduser().read_text(encoding="utf-8-sig"),"format":args.format or ("vtt" if Path(args.file).suffix.lower()==".vtt" else "srt"),"offset":args.offset,"replace":not args.append})
            elif args.action=="export":result=service.call("captions_export",{"project_id":args.project_id,"format":args.format})
            elif args.action=="transcribe":result=service.call("captions_transcribe",{"project_id":args.project_id,"render_job_id":args.render_job,"language":args.language,**({"model":args.model} if args.model else {})})
            elif args.action=="apply":result=service.call("captions_apply",{"project_id":args.project_id,"job_id":args.job_id,"expected_revision":args.revision,"replace":not args.append})
        output(result);return 0
    except KeyboardInterrupt:
        print("Stopped waiting. A background export, if started, continues; use montage jobs or montage cancel.",file=sys.stderr)
        return 130
    except Exception as exc:
        error={"ok":False,"error":str(exc),"code":getattr(exc,"code","operation_failed")}
        if args.command=="_cutout_worker":
            from .media_tools import run_cutout_worker
            return run_cutout_worker(args.directory)
        if args.command=="mcp": print(json.dumps(error),file=sys.stderr)
        else:output(error)
        return 1
