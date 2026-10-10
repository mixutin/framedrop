from __future__ import annotations

import hmac
import json
import mimetypes
import re
import secrets
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from .config import StudioError
from .service import Service


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

    def __init__(self,address,service):
        self.service=service
        self.csrf_token=secrets.token_urlsafe(32)
        super().__init__(address,StudioHandler)


class StudioHandler(BaseHTTPRequestHandler):
    server_version="Framedrop/0.2"
    protocol_version="HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self,format,*args):
        print("[web] "+format%args,file=sys.stderr)

    def end_headers(self):
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","same-origin")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("X-Frame-Options","DENY")
        super().end_headers()

    def _host_ok(self):
        port=self.server.server_address[1]
        return self.headers.get("Host","").lower() in {f"127.0.0.1:{port}",f"localhost:{port}"}

    def _check_host(self):
        if not self._host_ok():
            self._json({"ok":False,"error":"Invalid host","code":"invalid_host"},421)
            return False
        return True

    def _json(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        if self.command!="HEAD": self.wfile.write(body)

    def _error(self,exc):
        if isinstance(exc,StudioError): self._json({"ok":False,"error":str(exc),"code":exc.code},exc.status)
        elif isinstance(exc,(ValueError,KeyError,TypeError)): self._json({"ok":False,"error":str(exc),"code":"invalid_request"},400)
        else:
            print(f"[web] {type(exc).__name__}: {exc}",file=sys.stderr)
            self._json({"ok":False,"error":str(exc),"code":"operation_failed"},500)

    def _file(self,path: Path,mime: str|None=None,head=False):
        if not path.is_file(): raise StudioError("File not found","file_not_found",404)
        size=path.stat().st_size
        start=0;end=size-1;status=200
        range_header=self.headers.get("Range")
        if range_header:
            match=re.fullmatch(r"bytes=(\d*)-(\d*)",range_header.strip())
            if not match or not any(match.groups()):
                self.send_response(416);self.send_header("Content-Range",f"bytes */{size}");self.send_header("Content-Length","0");self.end_headers();return
            left,right=match.groups()
            if left:
                start=int(left);end=min(size-1,int(right)) if right else size-1
            else:
                start=max(0,size-int(right));end=size-1
            if start>=size or start>end:
                self.send_response(416);self.send_header("Content-Range",f"bytes */{size}");self.send_header("Content-Length","0");self.end_headers();return
            status=206
        length=max(0,end-start+1)
        self.send_response(status)
        self.send_header("Content-Type",mime or mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length",str(length));self.send_header("Accept-Ranges","bytes")
        self.send_header("Cache-Control","private, max-age=60" if "/api/" in self.path else "no-cache")
        if status==206: self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
        if path.suffix==".html":
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.end_headers()
        if head:return
        with path.open("rb") as handle:
            handle.seek(start);remaining=length
            while remaining:
                chunk=handle.read(min(256*1024,remaining))
                if not chunk:break
                self.wfile.write(chunk);remaining-=len(chunk)

    def do_GET(self):
        if not self._check_host():return
        try:
            parsed=urlsplit(self.path);query=parse_qs(parsed.query);service=self.server.service
            value=lambda key,default="":query.get(key,[default])[0]
            if parsed.path=="/api/bootstrap":
                effect_info=service.call("effects_list",{})
                self._json({"status":service.status(),"projects":service.projects.list(),"effects":effect_info["effects"],"transitions":effect_info["transitions"],"compatibility":effect_info["compatibility"],"assets":service.library.list(limit=60),"csrf_token":self.server.csrf_token})
            elif parsed.path=="/api/thumbnail": self._file(service.library.thumbnail(value("id"),float(value("time","0"))),"image/jpeg",self.command=="HEAD")
            elif parsed.path=="/api/media":
                asset=service.library.get(value("id"))
                if asset["kind"] not in {"video","image","audio","font"}: raise StudioError("This asset type cannot be streamed","unsupported_preview",400)
                self._file(Path(asset["path"]),head=self.command=="HEAD")
            elif parsed.path=="/api/output": self._file(service.jobs.output(value("job")),"video/mp4",self.command=="HEAD")
            elif parsed.path=="/api/health": self._json({"ok":True,"app":"Framedrop"})
            else:
                allowed={"/":"index.html","/index.html":"index.html","/app.js":"app.js","/style.css":"style.css","/icon.svg":"icon.svg","/favicon.ico":"icon.svg"}
                if parsed.path not in allowed: raise StudioError("Page not found","not_found",404)
                self._file(Path(__file__).parent/"static"/allowed[parsed.path],head=self.command=="HEAD")
        except (BrokenPipeError,ConnectionResetError,socket.timeout): pass
        except Exception as exc: self._error(exc)

    def do_HEAD(self): self.do_GET()

    def do_POST(self):
        if not self._check_host():return
        try:
            if urlsplit(self.path).path!="/api/call": raise StudioError("Endpoint not found","not_found",404)
            token=self.headers.get("X-Montage-Token","")
            if not hmac.compare_digest(token,self.server.csrf_token): raise StudioError("Reload the editor to refresh its session token","invalid_token",403)
            origin=self.headers.get("Origin")
            port=self.server.server_address[1]
            if origin and origin not in {f"http://127.0.0.1:{port}",f"http://localhost:{port}"}: raise StudioError("Request origin is not allowed","invalid_origin",403)
            if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json": raise StudioError("Use application/json","invalid_content_type",415)
            length=int(self.headers.get("Content-Length","0"))
            if length<1 or length>4*1024*1024: raise StudioError("Request must contain 1 byte to 4 MiB of JSON","request_too_large",413)
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict) or not isinstance(body.get("tool"),str): raise StudioError("Request must contain a tool name and arguments")
            result=self.server.service.call(body["tool"],body.get("arguments",{}))
            self._json({"ok":True,"result":result})
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        except Exception as exc:
            self.close_connection=True
            self._error(exc)


def serve(service: Service|None=None,port: int|None=None,open_browser: bool=False):
    service=service or Service()
    port=service.config.port if port is None else port
    if open_browser and port:
        url=f"http://127.0.0.1:{port}"
        try:
            with urlopen(url+"/api/health",timeout=2) as response:
                existing=json.load(response)
            if existing.get("app") in {"Framedrop","Montage Studio"}:
                webbrowser.open(url)
                return
        except (OSError,ValueError):pass
    with StudioHTTPServer(("127.0.0.1",port),service) as server:
        url=f"http://127.0.0.1:{server.server_address[1]}"
        print(f"Framedrop: {url}",file=sys.stderr,flush=True)
        if open_browser:
            threading.Timer(.4,lambda:webbrowser.open(url)).start()
        try:server.serve_forever(poll_interval=.3)
        except KeyboardInterrupt:pass
