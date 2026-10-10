"""A small, explicit MCP 2025 stdio transport for Framedrop.

This module deliberately implements the initialize-based MCP protocol family.
It does not claim support for the stateless 2026 protocol. Application behavior,
argument validation and persistent render jobs belong to :mod:`service`.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import json
import base64
from pathlib import Path
import sys
from typing import Any, BinaryIO, TextIO


SERVER_NAME = "framedrop"
from . import __version__

SERVER_VERSION = __version__
SUPPORTED_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
MAX_INPUT_BYTES = 4 * 1024 * 1024

INSTRUCTIONS = (
    "Framedrop edits local media through persistent, non-destructive projects. "
    "Use library_scan and assets_list to discover asset IDs; use effects_list for "
    "supported native effects and external preset compatibility. Fetch the current "
    "project revision before editing and pass expected_revision when saving. "
    "Validate or inspect render_plan before exporting. render_start returns an "
    "asynchronous job immediately: retain its id and poll job_status until its "
    "status is completed, failed or cancelled. Use job_cancel to cancel an export. "
    "A queued or running job is not a completed video. Source media is preserved."
)


class ProtocolError(Exception):
    """An invalid protocol operation rather than a failed editing operation."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _error(request_id: str | int | None, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(request_id: str | int, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_for_version(tool: dict, version: str) -> dict:
    """Avoid advertising newer optional fields to older clients."""
    fields = {"name", "description", "inputSchema"}
    if version >= "2025-03-26":
        fields.add("annotations")
    if version >= "2025-06-18":
        fields.update(("title", "outputSchema"))
    if version >= "2025-11-25":
        fields.add("icons")
    # Protocol-level task support is not implemented. Persistent render jobs are
    # normal application tools, so do not propagate an execution.taskSupport.
    return {key: value for key, value in tool.items() if key in fields}


class _Session:
    def __init__(self, service: Any, tools: list[dict], stderr: TextIO) -> None:
        self.service = service
        self.tools = tools
        self.tool_names = {tool["name"] for tool in tools}
        self.stderr = stderr
        self.version: str | None = None
        self.ready = False

    def handle(self, request: Any) -> dict | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid JSON-RPC request")

        # We never issue server-to-client requests. Ignore unsolicited responses
        # instead of creating an error-response loop with a confused peer.
        if "method" not in request and ("result" in request or "error" in request):
            return None

        method = request.get("method")
        request_id = request.get("id")
        has_id = "id" in request
        valid_id = isinstance(request_id, (str, int)) and not isinstance(request_id, bool)
        if not isinstance(method, str) or not method or (has_id and not valid_id):
            return _error(request_id if valid_id else None, -32600, "Invalid JSON-RPC request")
        if "result" in request or "error" in request:
            return _error(request_id if valid_id else None, -32600, "Invalid JSON-RPC request")

        params = request.get("params", {})
        if not has_id:
            # Notifications never receive replies, including unknown ones.
            if (
                method == "notifications/initialized"
                and self.version is not None
                and isinstance(params, dict)
            ):
                self.ready = True
            return None

        if not isinstance(params, dict):
            return _error(request_id, -32602, "MCP params must be an object")

        try:
            result = self._dispatch(method, params)
        except ProtocolError as exc:
            return _error(request_id, exc.code, str(exc))
        except Exception:
            # Unexpected transport failures must not leak a traceback or leave a
            # request unanswered. Application failures are handled in _call_tool.
            return _error(request_id, -32603, "Internal MCP server error")
        return _result(request_id, result)

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "server/discover":
            # Enables modern clients to make their documented legacy fallback.
            raise ProtocolError(-32601, "Method not found: server/discover")
        if method == "ping":
            return {}
        if method == "initialize":
            return self._initialize(params)
        if method not in {"tools/list", "tools/call"}:
            raise ProtocolError(-32601, f"Method not found: {method}")
        if self.version is None or not self.ready:
            raise ProtocolError(-32002, "Complete initialize and notifications/initialized first")
        if method == "tools/list":
            if params.get("cursor") is not None:
                raise ProtocolError(-32602, "This tool list is unpaginated; omit cursor")
            return {"tools": [_tool_for_version(tool, self.version) for tool in self.tools]}
        return self._call_tool(params)

    def _initialize(self, params: dict) -> dict:
        if self.version is not None:
            raise ProtocolError(-32600, "This connection is already initialized")
        version = params.get("protocolVersion")
        client = params.get("clientInfo")
        if not isinstance(version, str) or not version:
            raise ProtocolError(-32602, "initialize requires a protocolVersion string")
        if not isinstance(params.get("capabilities"), dict):
            raise ProtocolError(-32602, "initialize requires a capabilities object")
        if (
            not isinstance(client, dict)
            or not isinstance(client.get("name"), str)
            or not client["name"]
            or not isinstance(client.get("version"), str)
            or not client["version"]
        ):
            raise ProtocolError(-32602, "initialize requires clientInfo with name and version")
        self.version = version if version in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return {
            "protocolVersion": self.version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise ProtocolError(-32602, "tools/call requires a tool name")
        if not isinstance(arguments, dict):
            raise ProtocolError(-32602, "Tool arguments must be an object")
        if name not in self.tool_names:
            raise ProtocolError(-32602, f"Unknown tool: {name}")
        try:
            # Protocol stdout stays clean even if a library prints diagnostics.
            with redirect_stdout(self.stderr):
                payload = self.service.call(name, arguments)
            if not isinstance(payload, dict):
                raise TypeError("Tool implementation returned a non-object result")
            serialized = _dumps(payload)
            result = {"content": [{"type": "text", "text": serialized}], "isError": False}
            if name == "asset_preview" and payload.get("path"):
                preview = Path(payload["path"])
                # This path is produced by AssetLibrary.thumbnail, never supplied by the caller.
                cache_root = getattr(getattr(self.service, "config", None), "cache_dir", None)
                if cache_root is not None and preview.resolve().is_relative_to(Path(cache_root).resolve()) and preview.suffix.lower() == ".jpg" and preview.is_file() and preview.stat().st_size <= 2 * 1024 * 1024:
                    result["content"].append({"type": "image", "data": base64.b64encode(preview.read_bytes()).decode("ascii"), "mimeType": "image/jpeg"})
            if self.version >= "2025-06-18":
                result["structuredContent"] = payload
            return result
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            return {"content": [{"type": "text", "text": message}], "isError": True}


def _discard_line(stream: TextIO | BinaryIO) -> None:
    """Discard an oversized line without accumulating its remaining bytes."""
    while True:
        part = stream.readline(65536)
        if not part or part.endswith(b"\n" if isinstance(part, bytes) else "\n"):
            return


def serve(
    service: Any = None,
    *,
    input_stream: TextIO | BinaryIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
    tools: list[dict] | None = None,
    max_input_bytes: int = MAX_INPUT_BYTES,
) -> None:
    """Serve newline-delimited MCP requests until stdin reaches EOF.

    Optional streams and a tool registry make the exact wire behavior testable
    without loading media or starting the full application. Real stdin uses its
    binary stream so the input bound applies to bytes rather than characters.
    """
    if max_input_bytes < 1:
        raise ValueError("max_input_bytes must be positive")
    stdin = input_stream if input_stream is not None else getattr(sys.stdin, "buffer", sys.stdin)
    stdout = output_stream if output_stream is not None else sys.stdout
    stderr = error_stream if error_stream is not None else sys.stderr

    with redirect_stdout(stderr):
        if service is None:
            from .service import Service

            service = Service()
        if tools is None:
            from .tools import TOOLS

            tools = TOOLS
    session = _Session(service, tools, stderr)

    def write(response: dict | None) -> None:
        if response is not None:
            stdout.write(_dumps(response) + "\n")
            stdout.flush()

    while True:
        line = stdin.readline(max_input_bytes + 1)
        if not line:
            return
        newline = b"\n" if isinstance(line, bytes) else "\n"
        try:
            byte_count = len(line) if isinstance(line, bytes) else len(line.encode("utf-8"))
        except UnicodeError:
            write(_error(None, -32700, "Input must be valid UTF-8"))
            continue
        if byte_count > max_input_bytes:
            if not line.endswith(newline):
                _discard_line(stdin)
            write(_error(None, -32700, f"MCP message exceeds {max_input_bytes} bytes"))
            continue
        try:
            decoded = line.decode("utf-8") if isinstance(line, bytes) else line
            request = json.loads(decoded, parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            write(_error(None, -32700, "Parse error: expected one UTF-8 JSON message per line"))
            continue
        write(session.handle(request))


if __name__ == "__main__":
    serve()
