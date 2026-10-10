from __future__ import annotations

import html
import math
import re
from pathlib import Path

from .config import StudioError
from .projects import new_id, identifier, finite

DEFAULT_STYLE={"preset":"clean","font_size":52,"font_asset_id":None,"color":"#ffffff","outline_color":"#000000","outline":3,"position":"bottom","margin":80}
_TIME=re.compile(r"^(?:(\d{1,4}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})$")


def parse_time(value: str) -> float:
    match=_TIME.fullmatch(value.strip())
    if not match:raise StudioError("Invalid caption timestamp: "+value)
    hours,minutes,seconds,milliseconds=match.groups()
    if int(minutes)>59 or int(seconds)>59:raise StudioError("Caption minutes and seconds must be from 00 to 59")
    return int(hours or 0)*3600+int(minutes)*60+int(seconds)+int(milliseconds.ljust(3,"0"))/1000


def timestamp(value: float,format: str="srt") -> str:
    milliseconds=round(finite(value,"Caption time",0,14400)*1000)
    hours,remainder=divmod(milliseconds,3600000);minutes,remainder=divmod(remainder,60000);seconds,ms=divmod(remainder,1000)
    sep="," if format=="srt" else "."
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{sep}{ms:03d}"


def parse_captions(text: str,format: str="srt",offset: float=0) -> list[dict]:
    if format not in {"srt","vtt"}:raise StudioError("Caption format must be srt or vtt")
    if not isinstance(text,str) or len(text)>2*1024*1024:raise StudioError("Caption import must contain at most 2 MiB of text")
    offset=finite(offset,"Caption offset",-14400,14400)
    text=text.lstrip("\ufeff").replace("\r\n","\n").replace("\r","\n")
    if format=="vtt":
        header=text.split("\n",1)[0]
        if not re.fullmatch(r"WEBVTT(?:[ \t].*)?",header) or "-->" in header:
            raise StudioError("WebVTT input must begin with WEBVTT followed by a line ending, space, or tab")
    blocks=re.split(r"\n\s*\n",text.strip());cues=[]
    for block_index,block in enumerate(blocks):
        lines=block.splitlines()
        if not lines:continue
        if format=="vtt" and (block_index==0 or lines[0] in {"STYLE","REGION"} or re.match(r"^NOTE(?:[ \t]|$)",lines[0])):continue
        timing_index=next((i for i,line in enumerate(lines[:2]) if "-->" in line),None)
        if timing_index is None:raise StudioError("Caption block has no timing line: "+lines[0][:100])
        timing=lines[timing_index].split("-->")
        if len(timing)!=2:raise StudioError("Malformed caption timing line")
        start=parse_time(timing[0])+offset
        end_text=timing[1].strip().split()[0] if timing[1].strip() else ""
        end=parse_time(end_text)+offset
        if end<=start or start<0 or end>14400:raise StudioError("Each caption must start at or after zero, end after its start, and fit within four hours")
        content="\n".join(lines[timing_index+1:]).strip()
        # Import visual caption text; WebVTT cue markup/settings are not executable styling.
        content=html.unescape(re.sub(r"<[^>]*>","",content))
        if not content:continue
        if "\x00" in content or len(content)>4000:raise StudioError("Caption text is too long or contains a NUL character")
        cues.append({"id":new_id("cap"),"start":round(start,3),"end":round(end,3),"text":content})
        if len(cues)>2000:raise StudioError("At most 2000 caption cues can be imported")
    if not cues:raise StudioError("No caption cues found")
    return sorted(cues,key=lambda cue:(cue["start"],cue["end"]))


def export_captions(cues: list[dict],format: str="srt") -> str:
    if format not in {"srt","vtt"}:raise StudioError("Caption format must be srt or vtt")
    blocks=["WEBVTT"] if format=="vtt" else []
    for index,cue in enumerate(sorted(cues,key=lambda c:(c["start"],c["end"])),1):
        start,end=timestamp(cue["start"],format),timestamp(cue["end"],format)
        if parse_time(end)<=parse_time(start):raise StudioError("Caption end must remain after its start when rounded to milliseconds")
        content=str(cue["text"]).replace("\r\n","\n").replace("\r","\n")
        # Both formats may interpret markup. Escape plain text before serialization.
        content=html.escape(content,quote=False)
        block=(f"{index}\n" if format=="srt" else "")+f"{start} --> {end}\n{content}"
        blocks.append(block)
    return "\n\n".join(blocks)+"\n"


def import_project(store,project_id: str,expected_revision: int,text: str,format: str="srt",offset: float=0,replace: bool=True) -> dict:
    cues=parse_captions(text,format,offset)
    project=store.get(project_id)
    project["captions"]=cues if replace else sorted(project.get("captions",[])+cues,key=lambda c:(c["start"],c["end"]))
    project.setdefault("caption_style",DEFAULT_STYLE.copy())
    return store.save(project,expected_revision)


def export_project(store,project_id: str,format: str="srt") -> dict:
    project=store.get(project_id);text=export_captions(project.get("captions",[]),format)
    directory=store.config.workspace/"captions";directory.mkdir(parents=True,exist_ok=True)
    path=directory/f"{identifier(project_id)}_r{project['revision']}.{format}"
    # Revision-qualified deterministic export; never overwrite differing existing content.
    try:
        with path.open("x",encoding="utf-8") as handle:handle.write(text)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=text:raise StudioError("A different caption export already occupies this path")
    return {"format":format,"text":text,"path":str(path),"cue_count":len(project.get("captions",[])),"revision":project["revision"]}
