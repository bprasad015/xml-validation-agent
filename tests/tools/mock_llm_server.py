from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as element_tree
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockLlmHandler(BaseHTTPRequestHandler):
    server_version = "MockLlm/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_json({"ok": True})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        request_payload = json.loads(raw_body)
        user_message = request_payload["messages"][-1]["content"]
        validation_payload = json.loads(user_message)

        rendered_xml = validation_payload["rendered_xml"]
        issues = []
        try:
            element_tree.fromstring(rendered_xml)
        except element_tree.ParseError as exc:
            issues.append(
                {
                    "severity": "error",
                    "location": "rendered_xml",
                    "message": f"Malformed XML: {exc}",
                    "suggested_fix": "Fix the Jinja template so it renders well-formed XML.",
                }
            )

        if "agentic-xml-smoke" not in rendered_xml:
            issues.append(
                {
                    "severity": "error",
                    "location": "xmlValidationConfig/metadata/name",
                    "message": "Expected smoke-test service name was not rendered.",
                    "suggested_fix": "Pass xml_validation_service_name to template_vars.",
                }
            )

        decision = {
            "valid": not issues,
            "feedback": "Mock LLM validated rendered XML and supplied Ansible context.",
            "suggested_fix": "" if not issues else issues[0]["suggested_fix"],
            "issues": issues,
        }
        response_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(decision),
                    }
                }
            ]
        }
        self._write_json(response_payload)

    def _write_json(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock OpenAI-compatible LLM server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockLlmHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
