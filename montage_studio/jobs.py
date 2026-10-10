from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import threading
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

from .config import Config, StudioError, atomic_json, utcnow
from .projects import identifier, new_id


def process_identity(pid):
    """Linux start ticks prevent mistaking a recycled PID for this render worker."""
    try:
        fields=Path(f"/proc/{int(pid)}/stat").read_text().rsplit(") ",1)[1].split()
        return fields[0],fields[19]
    except (OSError,ValueError,IndexError):
        return None,None


class JobManager:
    def __init__(self,config: Config,library,projects):
        self.config=config; self.library=library; self.projects=projects

    def directory(self,job_id: str) -> Path:
        return self.config.jobs_dir/identifier(job_id)

    @contextmanager
    def lock(self,path: Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("a+") as handle:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    def get(self,job_id: str,check_process: bool=True) -> dict:
        directory=self.directory(job_id);path=directory/"job.json"
        if not path.is_file(): raise StudioError("Render job not found","job_not_found",404)
        job=json.loads(path.read_text())
        if check_process and job["status"] in {"queued","running"}:
            dead=False
            if job.get("pid"):
                try: os.kill(job["pid"],0)
                except ProcessLookupError: dead=True
                except PermissionError: pass
                state,identity=process_identity(job["pid"])
                dead=dead or state in {"Z","X"} or bool(identity and job.get("pid_identity") and identity!=job["pid_identity"])
            elif (datetime.now(timezone.utc)-datetime.fromisoformat(job["created_at"])).total_seconds()>30:
                dead=True
            if dead:
                with self.lock(directory/"write.lock"):
                    current=self.get(job_id,check_process=False)
                    if current["status"] in {"queued","running"} and current.get("pid")==job.get("pid") and current.get("pid_identity")==job.get("pid_identity"):
                        current.update(status="cancelled" if (directory/"cancel.request").exists() else "failed",message="Worker stopped before completion",error="The worker exited. See the worker log for details.",updated_at=utcnow())
                        atomic_json(directory/"job.json",current)
                    job=current
        return job

    def update(self,job_id: str,**values) -> dict:
        directory=self.directory(job_id)
        with self.lock(directory/"write.lock"):
            job=self.get(job_id,check_process=False)
            job.update(values);job["updated_at"]=utcnow()
            atomic_json(directory/"job.json",job)
            return job

    def list(self) -> list[dict]:
        result=[]
        for directory in self.config.jobs_dir.iterdir():
            if not directory.is_dir() or not (directory/"job.json").is_file(): continue
            try: result.append(self.get(directory.name))
            except (OSError,ValueError): continue
        return sorted(result,key=lambda x:x["created_at"],reverse=True)[:100]

    def start(self,project_id: str,quality: str="preview") -> dict:
        from .engine import validate_project
        if quality not in {"preview","final"}: raise StudioError("Quality must be preview or final")
        project=self.projects.get(project_id)
        if not project["clips"]: raise StudioError("Add at least one footage clip before rendering")
        validation=validate_project(project,self.library.get)
        if not validation["valid"]: raise StudioError("Cannot render: "+"; ".join(str(e) for e in validation.get("errors",[])),"invalid_project")
        with self.lock(self.config.state_dir/"render-start.lock"):
            active=[j for j in self.list() if j["status"] in {"queued","running"}]
            if active: raise StudioError(f"A render is already active ({active[0]['id']}). Wait or cancel it before starting another.","render_busy",409)
            jid=new_id("job");directory=self.directory(jid);directory.mkdir(parents=True)
            slug=re.sub(r"[^a-zA-Z0-9_-]+","-",project["name"]).strip("-")[:50] or "montage"
            output=self.config.renders_dir/f"{slug}_{jid}_{quality}.mp4"
            job={"id":jid,"kind":"render","project_id":project_id,"project_name":project["name"],"revision":project["revision"],"quality":quality,"status":"queued","progress":0,"message":"Waiting for renderer","created_at":utcnow(),"updated_at":utcnow(),"output_path":str(output)}
            atomic_json(directory/"job.json",job);atomic_json(directory/"project.json",project);atomic_json(directory/"config.json",self.config.as_dict())
            source=str(Path(__file__).resolve().parent.parent)
            env=os.environ.copy();env["PYTHONPATH"]=source+os.pathsep+env.get("PYTHONPATH","")
            with (directory/"worker.log").open("ab") as log:
                try:
                    process=subprocess.Popen([sys.executable,"-m","montage_studio","_worker",str(directory)],cwd=source,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
                except OSError as exc:
                    self.update(jid,status="failed",error=str(exc),message="Could not start render worker")
                    raise StudioError("Could not start render worker: "+str(exc),"render_failed",500) from exc
            created=self.update(jid,pid=process.pid,pid_identity=process_identity(process.pid)[1])
            threading.Thread(target=process.wait,daemon=True,name="montage-worker-reaper").start()
            return created

    def cancel(self,job_id: str) -> dict:
        job=self.get(job_id)
        if job["status"] not in {"queued","running"}: return job
        (self.directory(job_id)/"cancel.request").touch()
        return self.update(job_id,message="Cancellation requested")

    def output(self,job_id: str) -> Path:
        job=self.get(job_id)
        if job.get("kind","render")!="render": raise StudioError("This job does not contain a video export","not_video_output",400)
        if job["status"]!="completed": raise StudioError("The render is not complete","output_not_ready",409)
        path=Path(job["output_path"]).resolve()
        if not path.is_relative_to(self.config.renders_dir.resolve()) or not path.is_file(): raise StudioError("Render output is missing","output_missing",404)
        return path


def run_worker(directory: str) -> int:
    from .assets import AssetLibrary
    from .projects import ProjectStore
    from .engine import render_project
    location=Path(directory).resolve()
    config=Config.from_dict(json.loads((location/"config.json").read_text()))
    if location.parent!=config.jobs_dir.resolve(): raise StudioError("Invalid render job directory")
    config.ensure();library=AssetLibrary(config);manager=JobManager(config,library,ProjectStore(config,library))
    jid=location.name;job=manager.get(jid,check_process=False)
    if job["status"] not in {"queued","running"}: return 0
    work=config.cache_dir/"renders"/jid;work.mkdir(parents=True,exist_ok=True)
    output=Path(job["output_path"]).resolve()
    if not output.is_relative_to(config.renders_dir.resolve()): raise StudioError("Invalid render destination")
    cancelled=lambda:(location/"cancel.request").exists()
    last=[0.0]
    def progress(fraction,message):
        now=time.monotonic()
        if now-last[0]>=.2 or fraction>=1:
            manager.update(jid,progress=max(0,min(.999,float(fraction))),message=str(message));last[0]=now
    try:
        with (config.state_dir/"render-worker.lock").open("a+") as lock:
            try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc: raise StudioError("Another renderer is already working") from exc
            if cancelled(): raise InterruptedError("Render cancelled")
            manager.update(jid,status="running",pid=os.getpid(),pid_identity=process_identity(os.getpid())[1],message="Preparing media")
            project=json.loads((location/"project.json").read_text())
            result=render_project(project,library.get,str(output),str(work),quality=job["quality"],progress=progress,cancelled=cancelled)
            if cancelled(): raise InterruptedError("Render cancelled")
            if not output.is_file() or output.stat().st_size==0: raise RuntimeError("Renderer did not produce an output file")
            manager.update(jid,status="completed",progress=1,message="Render complete",result=result)
            return 0
    except BaseException as exc:
        output.unlink(missing_ok=True)
        was_cancelled=cancelled() or isinstance(exc,InterruptedError)
        manager.update(jid,status="cancelled" if was_cancelled else "failed",error=str(exc),message="Render cancelled" if was_cancelled else "Render failed")
        traceback.print_exc()
        return 0 if was_cancelled else 1
    finally:
        # Preserve diagnostic logs and command manifests, remove regenerable intermediate video.
        logs=location/"render-logs"
        for file in work.rglob("*"):
            if file.is_file() and file.suffix.lower() in {".log",".json",".jsonl",".txt",".ass"}:
                target=logs/file.relative_to(work);target.parent.mkdir(parents=True,exist_ok=True)
                try: shutil.copy2(file,target)
                except OSError: pass
        shutil.rmtree(work,ignore_errors=True)
