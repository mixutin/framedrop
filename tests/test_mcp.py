"""Wire-level tests for the actual MCP stdio loop (no media dependencies)."""

import io
import json
import unittest

from montage_studio.mcp import MAX_INPUT_BYTES, SUPPORTED_VERSIONS, serve


TOOLS = [
    {
        "name": name,
        "description": "Test tool",
        "title": "Test Tool",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
        "outputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
        "icons": [{"src": "data:image/png;base64,AA=="}],
        "execution": {"taskSupport": "optional"},
    }
    for name in ("echo", "fail", "noisy", "bad_result", "render_start", "job_status")
]


class FakeService:
    def __init__(self):
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "fail":
            raise ValueError("Unknown asset; select an ID from assets_list")
        if name == "noisy":
            print("A library diagnostic")
        if name == "bad_result":
            return {"value": float("nan")}
        if name == "render_start":
            return {"id": "job-1", "status": "queued", "progress": 0}
        if name == "job_status":
            return {"id": "job-1", "status": "completed", "progress": 1}
        return {"received": arguments}


def request(method, request_id=1, params=None):
    value = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        value["params"] = params
    return value


def initialize(version="2025-11-25", request_id=1):
    return request(
        "initialize",
        request_id,
        {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    )


READY = {"jsonrpc": "2.0", "method": "notifications/initialized"}


class StdioTests(unittest.TestCase):
    def run_wire(self, messages, **kwargs):
        if isinstance(messages, bytes):
            source = io.BytesIO(messages)
        elif isinstance(messages, str):
            source = io.StringIO(messages)
        else:
            source = io.StringIO("".join(json.dumps(item) + "\n" for item in messages))
        output, errors = io.StringIO(), io.StringIO()
        service = FakeService()
        serve(
            service,
            input_stream=source,
            output_stream=output,
            error_stream=errors,
            tools=TOOLS,
            **kwargs,
        )
        raw = output.getvalue()
        responses = [json.loads(line) for line in raw.splitlines()]
        return responses, service, errors.getvalue(), raw

    def test_full_transcript_and_structured_content(self):
        responses, service, errors, raw = self.run_wire(
            [
                initialize(),
                READY,
                request("ping", "ping-id"),
                request("tools/list", 2),
                request("tools/call", 3, {"name": "echo", "arguments": {"text": "Hei\nä"}}),
            ]
        )
        self.assertEqual([r["id"] for r in responses], [1, "ping-id", 2, 3])
        info = responses[0]["result"]
        self.assertEqual(info["protocolVersion"], "2025-11-25")
        self.assertEqual(info["capabilities"], {"tools": {}})
        self.assertIn("asynchronous", info["instructions"])
        self.assertEqual(responses[1]["result"], {})
        advertised = responses[2]["result"]["tools"]
        self.assertEqual(advertised[0]["name"], "echo")
        self.assertNotIn("execution", advertised[0])
        result = responses[3]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"received": {"text": "Hei\nä"}})
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertEqual(service.calls, [("echo", {"text": "Hei\nä"})])
        self.assertEqual(errors, "")
        self.assertEqual(len(raw.splitlines()), 4)

    def test_negotiates_all_supported_versions_without_newer_fields(self):
        for version in SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                responses, _, _, _ = self.run_wire(
                    [initialize(version), READY, request("tools/list", 2), request("tools/call", 3, {"name": "echo"})]
                )
                self.assertEqual(responses[0]["result"]["protocolVersion"], version)
                tool = responses[1]["result"]["tools"][0]
                self.assertEqual("annotations" in tool, version >= "2025-03-26")
                self.assertEqual("outputSchema" in tool, version >= "2025-06-18")
                self.assertEqual("icons" in tool, version >= "2025-11-25")
                self.assertEqual("structuredContent" in responses[2]["result"], version >= "2025-06-18")

    def test_unknown_version_proposes_latest_supported(self):
        responses, _, _, _ = self.run_wire([initialize("2099-01-01")])
        self.assertEqual(responses[0]["result"]["protocolVersion"], SUPPORTED_VERSIONS[0])

    def test_modern_probe_returns_method_not_found_then_legacy_works(self):
        responses, _, _, _ = self.run_wire(
            [request("server/discover", "probe", {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}), initialize(), READY, request("tools/list", 2)]
        )
        self.assertEqual(responses[0]["error"]["code"], -32601)
        self.assertEqual(responses[1]["result"]["protocolVersion"], "2025-11-25")
        self.assertIn("tools", responses[2]["result"])

    def test_requires_both_initialization_steps_and_allows_early_ping(self):
        responses, service, _, _ = self.run_wire(
            [READY, request("ping", 0), request("tools/list", 1), initialize(request_id=2), request("tools/call", 3, {"name": "echo"}), READY, request("tools/list", 4)]
        )
        self.assertEqual(responses[0]["result"], {})
        self.assertEqual(responses[1]["error"]["code"], -32002)
        self.assertEqual(responses[3]["error"]["code"], -32002)
        self.assertIn("tools", responses[4]["result"])
        self.assertEqual(service.calls, [])

    def test_notifications_never_reply_or_execute_calls(self):
        notifications = [
            {"jsonrpc": "2.0", "method": "initialize", "params": initialize()["params"]},
            {"jsonrpc": "2.0", "method": "unknown"},
            {"jsonrpc": "2.0", "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}},
            {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "echo"}},
            {"jsonrpc": "2.0", "method": "unknown", "params": []},
        ]
        responses, service, _, _ = self.run_wire([*notifications, initialize(), READY, *notifications[1:]])
        self.assertEqual(len(responses), 1)
        self.assertIn("result", responses[0])
        self.assertEqual(service.calls, [])

    def test_tool_error_is_actionable_result_then_session_continues(self):
        responses, _, _, _ = self.run_wire(
            [initialize(), READY, request("tools/call", 2, {"name": "fail"}), request("tools/call", 3, {"name": "echo"})]
        )
        self.assertTrue(responses[1]["result"]["isError"])
        self.assertIn("assets_list", responses[1]["result"]["content"][0]["text"])
        self.assertNotIn("error", responses[1])
        self.assertFalse(responses[2]["result"]["isError"])

    def test_unknown_tools_and_malformed_call_params_are_protocol_errors(self):
        invalid = [
            {"name": "does-not-exist"},
            {"name": "echo", "arguments": []},
            {"name": "echo", "arguments": None},
            {"name": 3},
            {},
        ]
        messages = [initialize(), READY]
        messages += [request("tools/call", index + 2, args) for index, args in enumerate(invalid)]
        messages += [request("resources/list", 8), request("tools/list", 9, {"cursor": "unknown"})]
        responses, service, _, _ = self.run_wire(messages)
        self.assertEqual([r["error"]["code"] for r in responses[1:6]], [-32602] * 5)
        self.assertEqual(responses[6]["error"]["code"], -32601)
        self.assertEqual(responses[7]["error"]["code"], -32602)
        self.assertEqual(service.calls, [])

    def test_invalid_initialize_does_not_poison_valid_retry(self):
        invalid = [{}, {"protocolVersion": "2025-11-25"}, {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test"}}]
        responses, _, _, _ = self.run_wire(
            [*[request("initialize", i, p) for i, p in enumerate(invalid)], initialize(request_id=4), READY, initialize(request_id=5)]
        )
        self.assertEqual([r["error"]["code"] for r in responses[:3]], [-32602] * 3)
        self.assertIn("result", responses[3])
        self.assertEqual(responses[4]["error"]["code"], -32600)

    def test_parse_errors_and_invalid_ids_are_bounded_and_recoverable(self):
        wire = "not-json\n[]\nnull\n"
        for bad_id in (None, True, 1.5):
            wire += json.dumps(request("ping", bad_id)) + "\n"
        wire += '{"jsonrpc":"2.0","id":4,"method":"ping","params":{"x":NaN}}\n'
        wire += json.dumps(request("ping", 5)) + "\n"
        responses, _, _, _ = self.run_wire(wire)
        self.assertEqual([r["error"]["code"] for r in responses[:-1]], [-32700, -32600, -32600, -32600, -32600, -32600, -32700])
        self.assertEqual(responses[-1], {"jsonrpc": "2.0", "id": 5, "result": {}})

    def test_oversized_line_is_drained_and_next_request_survives(self):
        wire = "x" * 1200 + "\n" + json.dumps(request("ping", 9)) + "\n"
        responses, _, _, _ = self.run_wire(wire, max_input_bytes=512)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertIn("512", responses[0]["error"]["message"])
        self.assertEqual(responses[1]["id"], 9)
        self.assertEqual(responses[1]["result"], {})

    def test_multibyte_input_is_limited_by_bytes(self):
        wire = json.dumps({"value": "ä" * 400}, ensure_ascii=False) + "\n" + json.dumps(request("ping", 2)) + "\n"
        for text in (wire, wire.encode("utf-8")):
            responses, _, _, _ = self.run_wire(text, max_input_bytes=512)
            self.assertEqual(responses[0]["error"]["code"], -32700)
            self.assertEqual(responses[1]["result"], {})

    def test_invalid_utf8_then_valid_request(self):
        wire = b"\xff\n" + (json.dumps(request("ping", 2)) + "\n").encode("utf-8")
        responses, _, _, _ = self.run_wire(wire)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"], {})

    def test_accidental_library_prints_go_to_stderr(self):
        responses, _, errors, raw = self.run_wire([initialize(), READY, request("tools/call", 2, {"name": "noisy"})])
        self.assertIn("A library diagnostic", errors)
        self.assertNotIn("A library diagnostic", raw)
        self.assertFalse(responses[-1]["result"]["isError"])

    def test_invalid_tool_output_becomes_execution_error(self):
        responses, _, _, _ = self.run_wire([initialize(), READY, request("tools/call", 2, {"name": "bad_result"})])
        self.assertTrue(responses[-1]["result"]["isError"])
        self.assertNotIn("structuredContent", responses[-1]["result"])

    def test_render_start_returns_job_and_status_is_separate_call(self):
        responses, service, _, _ = self.run_wire(
            [initialize(), READY, request("tools/call", 2, {"name": "render_start", "arguments": {"project_id": "p"}}), request("tools/call", 3, {"name": "job_status", "arguments": {"job_id": "job-1"}})]
        )
        self.assertEqual(responses[1]["result"]["structuredContent"]["status"], "queued")
        self.assertEqual(responses[2]["result"]["structuredContent"]["status"], "completed")
        self.assertEqual(len(service.calls), 2)

    def test_empty_eof_and_unterminated_final_line(self):
        self.assertEqual(self.run_wire("")[0], [])
        self.assertEqual(self.run_wire(json.dumps(request("ping", "last")))[0][0]["id"], "last")

    def test_input_bound_is_positive(self):
        self.assertGreater(MAX_INPUT_BYTES, 0)
        with self.assertRaises(ValueError):
            self.run_wire("", max_input_bytes=0)


if __name__ == "__main__":
    unittest.main()
