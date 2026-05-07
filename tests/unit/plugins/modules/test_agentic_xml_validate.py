from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as element_tree
from pathlib import Path

import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "plugins" / "modules" / "agentic_xml_validate.py"
    spec = importlib.util.spec_from_file_location("agentic_xml_validate", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_validate_xml_payload_accepts_rendered_xml():
    agentic_xml_validate = _load_module()

    is_valid, parse_error = agentic_xml_validate.validate_xml_payload(
        "<config><name>valid</name></config>"
    )

    assert is_valid is True
    assert parse_error is None


def test_validate_xml_payload_rejects_malformed_rendered_xml():
    agentic_xml_validate = _load_module()

    is_valid, parse_error = agentic_xml_validate.validate_xml_payload(
        "<config><name>broken</config>"
    )

    assert is_valid is False
    assert parse_error is not None


def test_parse_llm_decision_handles_fenced_json():
    agentic_xml_validate = _load_module()
    llm_text = """```json
    {
      "valid": false,
      "feedback": "missing hostname",
      "suggested_fix": "set hostname",
      "issues": "hostname is undefined"
    }
    ```"""

    decision = agentic_xml_validate.parse_llm_decision(llm_text)

    assert decision["valid"] is False
    assert decision["feedback"] == "missing hostname"
    assert decision["suggested_fix"] == "set hostname"
    assert decision["issues"] == [
        {
            "severity": "info",
            "location": "llm_response",
            "message": "hostname is undefined",
        }
    ]


def test_parse_llm_decision_marks_unparseable_response_invalid():
    agentic_xml_validate = _load_module()

    decision = agentic_xml_validate.parse_llm_decision("looks fine")

    assert decision["valid"] is False
    assert "not valid JSON" in decision["suggested_fix"]
    assert decision["issues"][0]["location"] == "llm_response"


def test_collect_execution_context_reads_role_inventory_and_group_vars(tmp_path):
    agentic_xml_validate = _load_module()
    role_path = tmp_path / "roles" / "xml_validation"
    inventory_path = tmp_path / "inventories" / "ci" / "hosts.ini"
    group_vars_path = tmp_path / "group_vars"
    role_tasks = role_path / "tasks"
    role_tasks.mkdir(parents=True)
    inventory_path.parent.mkdir(parents=True)
    group_vars_path.mkdir()
    (role_tasks / "main.yml").write_text("---\n- debug:\n    msg: role\n", encoding="utf-8")
    inventory_path.write_text("[ci]\nlocalhost\n", encoding="utf-8")
    (group_vars_path / "all.yml").write_text("---\nxml_value: from_group\n", encoding="utf-8")

    context = agentic_xml_validate.collect_execution_context(
        role_path=str(role_path),
        inventory_path=str(inventory_path),
        group_vars_path=str(group_vars_path),
        max_context_bytes=10000,
    )

    used_paths = {Path(entry["path"]).name for entry in context["files"]}
    assert used_paths == {"main.yml", "hosts.ini", "all.yml"}
    assert context["missing"] == []
    assert context["truncated"] is False


def test_collect_execution_context_tracks_missing_paths(tmp_path):
    agentic_xml_validate = _load_module()

    context = agentic_xml_validate.collect_execution_context(
        base_dir=str(tmp_path),
        playbook_path="missing.yml",
    )

    assert context["files"] == []
    assert context["missing"] == ["missing.yml"]


def test_build_validation_prompt_includes_rendered_xml_and_context():
    agentic_xml_validate = _load_module()

    prompt = agentic_xml_validate.build_validation_prompt(
        prompt="validate this",
        src="xml_template.xml.j2",
        rendered_xml="<root />",
        local_xml_error=None,
        execution_context={"files": [{"path": "group_vars/all.yml", "content": "x: y"}]},
        extra_context={"play": "integration"},
    )

    assert '"rendered_xml": "<root />"' in prompt
    assert "group_vars/all.yml" in prompt
    assert '"play": "integration"' in prompt


def test_resolve_api_key_prefers_explicit_value():
    agentic_xml_validate = _load_module()

    api_key = agentic_xml_validate.resolve_api_key(
        "explicit",
        "LLM_API_KEY",
        {"LLM_API_KEY": "from-env"},
    )

    assert api_key == "explicit"


def test_render_jinja_template_uses_template_vars(tmp_path):
    pytest.importorskip("jinja2")
    agentic_xml_validate = _load_module()
    template_path = tmp_path / "xml_template.xml.j2"
    template_path.write_text("<config><name>{{ name }}</name></config>", encoding="utf-8")

    rendered = agentic_xml_validate.render_jinja_template(template_path, {"name": "agentic"})

    assert rendered == "<config><name>agentic</name></config>"


def test_service_config_template_renders_realistic_xml():
    agentic_xml_validate = _load_module()
    repo_root = Path(__file__).resolve().parents[4]
    template_path = repo_root / "roles" / "xml_validation" / "templates" / "service_config.xml.j2"

    rendered = agentic_xml_validate.render_jinja_template(
        template_path,
        {
            "xml_validation_environment": "ci",
            "xml_validation_service_name": "agentic-xml-smoke",
            "xml_validation_owner": "network-automation",
            "xml_validation_change_ticket": "CHG-2026-0001",
            "xml_validation_protocol": "https",
            "xml_validation_host": "example.internal",
            "xml_validation_port": 8443,
            "xml_validation_tls_enabled": "true",
            "xml_validation_certificate_profile": "internal-mtls",
            "xml_validation_backend_pool": [
                {
                    "name": "primary-api",
                    "host": "api-1.example.internal",
                    "port": 9443,
                    "weight": 100,
                }
            ],
            "xml_validation_routes": [
                {
                    "name": "order-writes",
                    "priority": 20,
                    "method": "POST",
                    "path": "/v1/orders",
                    "backend": "primary-api",
                }
            ],
            "xml_validation_features": ["xml-render", "llm-review", "backend-routing"],
            "xml_validation_allowed_status_codes": [200, 201, 204],
            "xml_validation_max_payload_kb": 512,
            "xml_validation_logging_profile": "structured-json",
            "xml_validation_metrics_enabled": "true",
        },
    )

    root = element_tree.fromstring(rendered)

    assert root.tag == "serviceConfiguration"
    assert root.get("environment") == "ci"
    assert root.findtext("./metadata/serviceName") == "agentic-xml-smoke"
    assert root.findtext("./endpoint/host") == "example.internal"
    assert root.find("./backendPool/member").get("name") == "primary-api"
    assert root.find("./routing/rule/match").get("path") == "/v1/orders"
