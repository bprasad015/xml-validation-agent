from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "plugins" / "modules" / "xml_validate.py"
    spec = importlib.util.spec_from_file_location("xml_validate", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_validate_xml_payload_accepts_valid_xml():
    xml_validate = _load_module()

    is_valid, parse_error = xml_validate.validate_xml_payload("<root><node>ok</node></root>")

    assert is_valid is True
    assert parse_error is None


def test_validate_xml_payload_rejects_malformed_xml():
    xml_validate = _load_module()

    is_valid, parse_error = xml_validate.validate_xml_payload("<root><node>broken</root>")

    assert is_valid is False
    assert parse_error is not None


def test_validate_xml_payload_accepts_xml_with_declaration():
    xml_validate = _load_module()
    payload = '<?xml version="1.0" encoding="UTF-8"?><root><x>1</x></root>'

    is_valid, parse_error = xml_validate.validate_xml_payload(payload)

    assert is_valid is True
    assert parse_error is None
