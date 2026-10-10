#!/usr/bin/env python3
"""Install optional CPU background removal and cache its model locally."""
import argparse
import shutil
import subprocess
import sys
from montage_studio.config import Config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python",default=sys.executable)
    args=parser.parse_args()
    state=Config.load().state_dir
    state.mkdir(parents=True,exist_ok=True)
    environment=state/"cutout-env"
    python=environment/"bin/python"
    uv=shutil.which("uv")
    if not python.exists():
        subprocess.run([uv,"venv","--python",args.python,str(environment)] if uv else [args.python,"-m","venv",str(environment)],check=True)
    requirements=["rembg[cpu]==2.0.85"]
    subprocess.run([uv,"pip","install","--python",str(python),*requirements] if uv else [str(python),"-m","pip","install",*requirements],check=True)
    code='''
import os,json,sys
from pathlib import Path
state=Path(sys.argv[1]); model_dir=state/"cutout-models"
model_dir.mkdir(exist_ok=True); os.environ["U2NET_HOME"]=str(model_dir);os.environ["OMP_NUM_THREADS"]="4"
from rembg import new_session
new_session("isnet-general-use",providers=["CPUExecutionProvider"])
settings={"python":sys.executable,"model_dir":str(model_dir),"model":"isnet-general-use"}
path=state/"background-removal.json"; temporary=path.with_suffix(".tmp")
temporary.write_text(json.dumps(settings,indent=2)+"\\n");temporary.replace(path)
print(json.dumps(settings,indent=2))
'''
    subprocess.run([str(python),"-c",code,str(state)],check=True)
    return 0


if __name__=="__main__": raise SystemExit(main())
