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
        root = None
        try:
            root = element_tree.fromstring(rendered_xml)
        except element_tree.ParseError as exc:
            issues.append(
                {
                    "severity": "error",
                    "location": "rendered_xml",
                    "message": f"Malformed XML: {exc}",
                    "suggested_fix": "Fix the Jinja template so it renders well-formed XML.",
                }
            )

        if root is not None:
            issues.extend(self._validate_service_configuration(root, validation_payload))

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

    def _validate_service_configuration(
        self,
        root: element_tree.Element,
        validation_payload: dict[str, Any],
    ) -> list[dict[str, str]]:
        issues = []

        if root.tag != "serviceConfiguration":
            issues.append(
                self._issue(
                    "serviceConfiguration",
                    f"Expected root element serviceConfiguration but found {root.tag}.",
                    "Render the service_config.xml.j2 template or update the AI contract.",
                )
            )
            return issues

        if root.get("environment") != "ci":
            issues.append(
                self._issue(
                    "serviceConfiguration/@environment",
                    "Expected CI environment attribute was not rendered.",
                    "Pass xml_validation_environment: ci to template_vars.",
                )
            )

        expected_service = (
            validation_payload.get("extra_context", {}).get("expected_service")
            or "agentic-xml-smoke"
        )
        service_name = root.findtext("./metadata/serviceName")
        if service_name != expected_service:
            issues.append(
                self._issue(
                    "serviceConfiguration/metadata/serviceName",
                    f"Expected service {expected_service} but rendered {service_name}.",
                    "Align extra_context.expected_service with xml_validation_service_name.",
                )
            )

        endpoint = root.find("./endpoint")
        if endpoint is None:
            issues.append(
                self._issue(
                    "serviceConfiguration/endpoint",
                    "Endpoint block is missing.",
                    "Render host, port, protocol, and certificateProfile under endpoint.",
                )
            )
        else:
            if endpoint.get("protocol") != "https":
                issues.append(
                    self._issue(
                        "serviceConfiguration/endpoint/@protocol",
                        "Endpoint protocol should be https for the smoke contract.",
                        "Set xml_validation_protocol: https.",
                    )
                )
            if endpoint.findtext("host") != "example.internal":
                issues.append(
                    self._issue(
                        "serviceConfiguration/endpoint/host",
                        "Expected endpoint host example.internal was not rendered.",
                        "Pass xml_validation_host: example.internal.",
                    )
                )
            if endpoint.findtext("port") != "8443":
                issues.append(
                    self._issue(
                        "serviceConfiguration/endpoint/port",
                        "Expected endpoint port 8443 was not rendered.",
                        "Pass xml_validation_port: 8443.",
                    )
                )

        backend_members = root.findall("./backendPool/member")
        if not any(
            member.get("name") == "primary-api"
            and member.findtext("host") == "api-1.example.internal"
            for member in backend_members
        ):
            issues.append(
                self._issue(
                    "serviceConfiguration/backendPool/member",
                    "Primary backend member was not rendered.",
                    "Include primary-api in xml_validation_backend_pool.",
                )
            )

        routes = root.findall("./routing/rule")
        if not any(
            route.get("name") == "order-writes"
            and route.find("match") is not None
            and route.find("match").get("path") == "/v1/orders"
            and route.find("forward") is not None
            and route.find("forward").get("backend") == "primary-api"
            for route in routes
        ):
            issues.append(
                self._issue(
                    "serviceConfiguration/routing/rule",
                    "Order write route does not forward to primary-api.",
                    "Include the order-writes route with path /v1/orders.",
                )
            )

        context_paths = [
            context_file.get("path", "")
            for context_file in validation_payload.get("execution_context", {}).get("files", [])
        ]
        if not any("group_vars" in path for path in context_paths):
            issues.append(
                self._issue(
                    "execution_context/group_vars",
                    "Group vars context was not supplied to the LLM request.",
                    "Pass group_vars_path to agentic_xml_validate.",
                )
            )

        return issues

    def _issue(self, location: str, message: str, suggested_fix: str) -> dict[str, str]:
        return {
            "severity": "error",
            "location": location,
            "message": message,
            "suggested_fix": suggested_fix,
        }

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
