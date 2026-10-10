#!/usr/bin/env python3
"""Install this checkout for the current Linux user, without sudo or downloads."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def write_managed(path: Path,text: str,marker: str|tuple[str,...],mode=0o644):
    markers=(marker,) if isinstance(marker,str) else marker
    if path.exists() and not any(m in path.read_text(errors="replace") for m in markers):
        raise SystemExit(f"Refusing to replace an unrelated existing file: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding="utf-8");path.chmod(mode)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root",help="Media folder (keeps your existing library when omitted)")
    parser.add_argument("--port",type=int,default=8741)
    parser.add_argument("--register-mcp",action="store_true")
    parser.add_argument("--start",action="store_true",help="Enable and start the local editor service")
    args=parser.parse_args()
    if sys.version_info<(3,11):raise SystemExit("Python 3.11+ is required")
    source=Path(__file__).resolve().parent;home=Path.home()
    for command in ["ffmpeg","ffprobe"]:
        if not shutil.which(command):raise SystemExit(f"Install FFmpeg first: {command} is missing")
    config_path=home/".config/framedrop/config.json"
    legacy_config=home/".config/montage-studio/config.json"
    config_path.parent.mkdir(parents=True,exist_ok=True)
    existing_config=config_path if config_path.exists() else legacy_config
    config=json.loads(existing_config.read_text()) if existing_config.exists() else None
    root=Path(args.media_root or (config or {}).get("media_root",home/"Editing")).expanduser().resolve()
    if not root.is_dir():raise SystemExit(f"Media folder does not exist: {root}")
    if config is not None:
        if Path(config.get("media_root","")).expanduser().resolve()!=root:
            raise SystemExit("The existing editor configuration uses another media folder; update it explicitly before reinstalling")
    else:
        config={"media_root":str(root),"workspace":str(root/"Framedrop"),"state_dir":str(home/".local/share/framedrop"),"ffmpeg":shutil.which("ffmpeg"),"ffprobe":shutil.which("ffprobe"),"threads":4,"port":args.port}
    config_path.write_text(json.dumps(config,indent=2)+"\n");config_path.chmod(0o600)
    port=int(config.get("port",args.port));binary=home/".local/bin/framedrop"
    legacy_binary=home/".local/bin/montage"
    launcher=f"#!/bin/sh\n# Framedrop launcher\nexport PYTHONPATH={shlex.quote(str(source))}${{PYTHONPATH:+:$PYTHONPATH}}\nexec {shlex.quote(sys.executable)} -m montage_studio \"$@\"\n"
    write_managed(binary,launcher,"# Framedrop launcher",0o755)
    legacy_managed=legacy_binary.is_file() and any(m in legacy_binary.read_text(errors="replace") for m in ("# Montage Studio launcher","# Framedrop launcher"))
    if not legacy_binary.exists() or legacy_managed:
        write_managed(legacy_binary,launcher,("# Montage Studio launcher","# Framedrop launcher"),0o755)
    desktop=home/".local/share/applications/framedrop.desktop"
    quoted_binary='"'+str(binary).replace('\\','\\\\').replace('"','\\"')+'"'
    entry=f"[Desktop Entry]\nType=Application\nName=Framedrop\nComment=AI-assisted video editor\nExec={quoted_binary} ui --open\nIcon={source}/montage_studio/static/icon.svg\nTerminal=false\nCategories=AudioVideo;Video;AudioVideoEditing;\nStartupNotify=true\nKeywords=framedrop;video;editor;MCP;AI;\n"
    write_managed(desktop,entry,"Name=Framedrop")
    legacy_desktop=home/".local/share/applications/montage-studio.desktop"
    if legacy_desktop.is_file() and "Name=Montage Studio" in legacy_desktop.read_text() and "montage_studio/static/icon.svg" in legacy_desktop.read_text():
        legacy_desktop.unlink()
    service_path=home/".config/systemd/user/framedrop.service"
    service_text=f"[Unit]\nDescription=Framedrop local editor\nAfter=default.target\n\n[Service]\nType=simple\nExecStart={quoted_binary} ui --port {port}\nWorkingDirectory={source}\nRestart=on-failure\nRestartSec=3\nNice=5\nUMask=0077\nNoNewPrivileges=true\n\n[Install]\nWantedBy=default.target\n"
    write_managed(service_path,service_text,"Description=Framedrop local editor")
    result={"source":str(source),"command":str(binary),"desktop_entry":str(desktop),"config":str(config_path),"url":f"http://127.0.0.1:{port}","mcp_registered":False,"service_started":False}
    if args.register_mcp:
        codex=shutil.which("codex") or str(home/".local/bin/codex")
        listed=subprocess.run([codex,"mcp","list","--json"],capture_output=True,text=True,check=True)
        servers=json.loads(listed.stdout)
        existing=next((item for item in servers if item.get("name")=="framedrop"),None)
        if existing:
            transport=existing.get("transport",{})
            if transport.get("command")!=str(binary) or transport.get("args")!=["mcp"]:
                raise SystemExit("An unrelated framedrop MCP entry already exists; it was preserved")
        else:subprocess.run([codex,"mcp","add","framedrop","--",str(binary),"mcp"],check=True,stdout=sys.stderr)
        legacy=next((item for item in servers if item.get("name")=="montage-studio"),None)
        if legacy_managed and legacy and legacy.get("transport",{}).get("command")==str(legacy_binary) and legacy.get("transport",{}).get("args")==["mcp"]:
            subprocess.run([codex,"mcp","remove","montage-studio"],check=True,stdout=sys.stderr)
        result["mcp_registered"]=True
    if args.start:
        env=os.environ.copy();runtime=Path(f"/run/user/{os.getuid()}")
        if (runtime/"bus").exists():
            env.setdefault("XDG_RUNTIME_DIR",str(runtime));env.setdefault("DBUS_SESSION_BUS_ADDRESS",f"unix:path={runtime}/bus")
        subprocess.run(["systemctl","--user","daemon-reload"],check=True,env=env)
        legacy_service=home/".config/systemd/user/montage-studio.service"
        if legacy_service.is_file() and "Description=Montage Studio local editor" in legacy_service.read_text() and str(legacy_binary) in legacy_service.read_text():
            subprocess.run(["systemctl","--user","disable","--now","montage-studio.service"],check=True,env=env)
        subprocess.run(["systemctl","--user","enable","--now","framedrop.service"],check=True,env=env)
        subprocess.run(["systemctl","--user","restart","framedrop.service"],check=True,env=env)
        result["service_started"]=True
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
