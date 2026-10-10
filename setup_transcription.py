#!/usr/bin/env python3
"""Install the optional offline speech caption engine in an isolated environment."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from montage_studio.config import Config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python",default=sys.executable,help="Python interpreter supported by Faster Whisper wheels (3.12 was tested)")
    parser.add_argument("--model",choices=["tiny","base","small","medium","large-v3"],default="base",help="Download this multilingual model and make it the default")
    args=parser.parse_args()
    state=Config.load().state_dir;state.mkdir(parents=True,exist_ok=True)
    environment=state/"transcription-env";python=environment/"bin/python"
    uv=shutil.which("uv")
    if not python.exists():
        subprocess.run([uv,"venv","--python",args.python,str(environment)] if uv else [args.python,"-m","venv",str(environment)],check=True)
    # Faster Whisper 1.2.1 uses an av.open argument removed by PyAV 19.
    # Pin the compatible decoder; see SYSTRAN/faster-whisper issue 1589.
    requirements=["faster-whisper==1.2.1","av==18.1.0"]
    install=[uv,"pip","install","--python",str(python),*requirements] if uv else [str(python),"-m","pip","install",*requirements]
    subprocess.run(install,check=True)
    code='''
from faster_whisper import WhisperModel
from pathlib import Path
import importlib.metadata,json,sys
state=Path(sys.argv[1]); selected=sys.argv[2]
print("Downloading and validating "+selected+"...",flush=True)
WhisperModel(selected,device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,download_root=str(state/"models"))
settings={"installed":True,"model_ready":True,"model":selected,"device":"cpu","compute_type":"int8","cpu_threads":4,"python":sys.executable,"download_root":str(state/"models"),"faster_whisper_version":importlib.metadata.version("faster-whisper"),"av_version":importlib.metadata.version("av")}
path=state/"transcription.json";temporary=path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(settings,indent=2)+"\\n");temporary.replace(path)
print(json.dumps(settings,indent=2))
'''
    subprocess.run([str(python),"-c",code,str(state),args.model],check=True)
    freeze=subprocess.run([uv,"pip","freeze","--python",str(python)] if uv else [str(python),"-m","pip","freeze"],capture_output=True,text=True,check=True)
    (state/"transcription-requirements.lock.txt").write_text(freeze.stdout)
    return 0


if __name__=="__main__":raise SystemExit(main())
