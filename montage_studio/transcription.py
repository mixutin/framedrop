"""Optional offline Whisper caption drafting from a completed timeline render."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from .captions import DEFAULT_STYLE,export_captions
from .config import Config,StudioError,atomic_json,utcnow
from .jobs import process_identity
from .projects import new_id


MODELS = ("tiny", "base", "small", "medium", "large-v3")


def status(config: Config) -> dict:
    path=config.state_dir/"transcription.json"
    if not path.is_file():
        return {"installed":False,"model_ready":False,"model":"base","message":"Optional offline caption transcription is not installed. SRT/VTT import and manual caption editing are available."}
    data=json.loads(path.read_text())
    data["installed"]=bool(data.get("installed") and Path(data.get("python","")).is_file())
    data["model_ready"]=bool(data["installed"] and data.get("model_ready") and Path(data.get("download_root","")).is_dir())
    root=Path(data.get("download_root", ""))
    data["models"]=[name for name in MODELS if any(all((snapshot/f).is_file() for f in ("model.bin","config.json","tokenizer.json")) for snapshot in (root/("models--Systran--faster-whisper-"+name)/"snapshots").glob("*"))]
    data["model_ready"]=bool(data["installed"] and data.get("model","base") in data["models"])
    return data


def timeline_signature(project: dict) -> str:
    # Captions, appearance-only title layers and naming do not alter spoken timing.
    value={key:project.get(key) for key in ["clips","audio","canvas","normalize_audio"]}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def start(service,project_id: str,render_job_id: str,language: str="auto",model: str|None=None) -> dict:
    settings=status(service.config)
    if not settings["installed"] or (model is None and not settings["model_ready"]):raise StudioError(settings.get("message","Offline caption model is not ready"),"transcription_unavailable",409)
    selected_model=model or settings.get("model","base")
    if model is not None and (model not in MODELS or model not in settings.get("models",[])):
        raise StudioError("Requested model is not cached. Run setup_transcription.py --model "+str(model),"model_unavailable",409)
    if language!="auto" and not re.fullmatch(r"[a-z]{2,3}",language):raise StudioError("Language must be auto or an ISO code such as en, fi or ja")
    project=service.projects.get(project_id);render=service.jobs.get(render_job_id)
    if render.get("kind","render")!="render" or render["status"]!="completed" or render["project_id"]!=project_id:
        raise StudioError("Choose a completed preview or export of this project","render_required",409)
    snapshot=json.loads((service.jobs.directory(render_job_id)/"project.json").read_text())
    if timeline_signature(project)!=timeline_signature(snapshot):raise StudioError("The timeline has changed since this render. Render a fresh preview before generating captions.","preview_outdated",409)
    source=service.jobs.output(render_job_id)
    with service.jobs.lock(service.config.state_dir/"render-start.lock"):
        if any(j["status"] in {"queued","running"} for j in service.jobs.list()):raise StudioError("Wait for the active export or transcription to finish, or cancel it first.","render_busy",409)
        jid=new_id("job");directory=service.jobs.directory(jid);directory.mkdir(parents=True)
        job={"id":jid,"kind":"transcription","project_id":project_id,"project_name":project["name"],"revision":project["revision"],"quality":"transcription","status":"queued","progress":0,"message":"Preparing offline captions","created_at":utcnow(),"updated_at":utcnow(),"language":language,"model":selected_model,"source_render_job_id":render_job_id,"source_path":str(source),"timeline_signature":timeline_signature(project)}
        atomic_json(directory/"job.json",job);atomic_json(directory/"project.json",project);atomic_json(directory/"config.json",service.config.as_dict())
        code_root=str(Path(__file__).resolve().parent.parent)
        env=os.environ.copy();env["PYTHONPATH"]=code_root+os.pathsep+env.get("PYTHONPATH","")
        env["OMP_NUM_THREADS"]="4";env["HF_HUB_OFFLINE"]="1"
        with (directory/"worker.log").open("ab") as log:
            try:process=subprocess.Popen([settings["python"],"-m","montage_studio","_transcribe_worker",str(directory)],cwd=code_root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
            except OSError as exc:
                service.jobs.update(jid,status="failed",message="Could not start transcription",error=str(exc));raise
        created=service.jobs.update(jid,pid=process.pid,pid_identity=process_identity(process.pid)[1])
        threading.Thread(target=process.wait,daemon=True,name="montage-transcription-reaper").start()
        return created


def apply(service,project_id: str,job_id: str,expected_revision: int,replace: bool=True) -> dict:
    project=service.projects.get(project_id);job=service.jobs.get(job_id)
    if job.get("kind")!="transcription" or job["status"]!="completed" or job["project_id"]!=project_id:
        raise StudioError("Choose a completed caption transcription for this project")
    if timeline_signature(project)!=job["timeline_signature"]:raise StudioError("Timeline timing changed since transcription. Generate captions from a fresh preview.","transcript_outdated",409)
    cues=job.get("result",{}).get("captions",[])
    if not cues:raise StudioError("No speech captions were detected. Existing captions were kept.","no_speech_detected",409)
    project["captions"]=cues if replace else sorted(project.get("captions",[])+cues,key=lambda c:(c["start"],c["end"]))
    project.setdefault("caption_style",DEFAULT_STYLE.copy())
    return service.projects.save(project,expected_revision)


def segment_cues(segment) -> list[dict]:
    words=getattr(segment,"words",None)
    cues=[];buffer=[];start=None;end=None
    def append_cue(text,start,end):
        start=round(max(0,float(start)),3);end=round(float(end),3)
        # Word timestamps can collapse after rounding. Keep only intervals that
        # satisfy the editor's 10 ms minimum instead of creating invalid drafts.
        if text and end>=start+.01:cues.append({"id":new_id("cap"),"start":start,"end":end,"text":text})
    def flush():
        nonlocal buffer,start,end
        if buffer and start is not None and end is not None:
            text="".join(buffer).strip()
            append_cue(text,start,end)
        buffer=[];start=None;end=None
    if words:
        for word in words:
            text=str(word.word)
            if start is not None and (len("".join(buffer))+len(text)>44 or len(buffer)>=8 or float(word.end)-start>3.5):flush()
            if start is None:start=float(word.start)
            end=float(word.end);buffer.append(text)
        flush()
    elif segment.text.strip():
        append_cue(segment.text.strip(),segment.start,segment.end)
    return cues


def run_worker(directory: str) -> int:
    from .service import Service
    location=Path(directory).resolve();config=Config.from_dict(json.loads((location/"config.json").read_text()))
    if location.parent!=config.jobs_dir.resolve():raise StudioError("Invalid transcription job directory")
    service=Service(config);jobs=service.jobs;jid=location.name;job=jobs.get(jid,check_process=False)
    if job["status"] not in {"queued","running"}:return 0
    stopped=threading.Event()
    def cancellation_monitor():
        # CTranslate2 can spend time inside a native call; monitor cancellation independently.
        while not stopped.wait(.2):
            if (location/"cancel.request").exists():
                jobs.update(jid,status="cancelled",message="Caption transcription cancelled")
                os._exit(0)
    monitor=threading.Thread(target=cancellation_monitor,daemon=True)
    try:
        with (config.state_dir/"render-worker.lock").open("a+") as lock:
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise StudioError("Another media worker is already active") from exc
            jobs.update(jid,status="running",pid=os.getpid(),pid_identity=process_identity(os.getpid())[1],message="Loading offline speech model",progress=.03)
            monitor.start()
            from faster_whisper import WhisperModel
            from .engine import probe
            settings=status(config)
            source=jobs.output(job["source_render_job_id"])
            if str(source)!=job["source_path"]:raise StudioError("Source render path changed")
            duration=probe(str(source))["duration"]
            model=WhisperModel(job.get("model",settings.get("model","base")),device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,download_root=settings["download_root"],local_files_only=True)
            jobs.update(jid,message="Listening for speech",progress=.08)
            segments,info=model.transcribe(str(source),language=None if job["language"]=="auto" else job["language"],beam_size=5,word_timestamps=True,vad_filter=True,condition_on_previous_text=False)
            cues=[]
            for segment in segments:
                cues.extend(segment_cues(segment))
                if len(cues)>2000:raise StudioError("Transcript exceeds 2000 caption cues; transcribe a shorter edit")
                jobs.update(jid,progress=min(.97,.08+.89*float(segment.end)/max(.1,duration)),message=f"Transcribing speech · {len(cues)} caption cues")
            text=export_captions(cues,"srt");caption_path=location/"draft.srt";caption_path.write_text(text,encoding="utf-8")
            result={"captions":cues,"cue_count":len(cues),"language":info.language,"language_probability":float(info.language_probability),"model":job.get("model",settings.get("model","base")),"draft":True,"path":str(caption_path),"message":"Review transcription text and timing before applying. Music, effects, accents and overlapping speech can reduce accuracy."}
            atomic_json(location/"transcript.json",result)
            jobs.update(jid,status="completed",progress=1,message=f"Caption draft ready · {len(cues)} cues",result=result)
            return 0
    except BaseException as exc:
        was_cancelled=(location/"cancel.request").exists()
        jobs.update(jid,status="cancelled" if was_cancelled else "failed",error=str(exc),message="Caption transcription cancelled" if was_cancelled else "Caption transcription failed")
        traceback.print_exc();return 0 if was_cancelled else 1
    finally:stopped.set()
