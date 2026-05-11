#!/usr/bin/python
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any

DOCUMENTATION = r"""
---
module: agentic_xml_validate
short_description: Validate rendered XML configuration with an LLM.
version_added: "1.0.0"
description:
  - Renders a local Jinja XML template, validates the rendered XML locally, and asks an
    OpenAI-compatible LLM endpoint for configuration review and suggested fixes.
  - The intended collection FQCN is C(pwc.config_validation_agent.agentic_xml_validate).
  - Run this module on the controller, for example with C(delegate_to: localhost), when
    C(src), playbook, role, inventory, and variable paths live on the Ansible controller.
options:
  src:
    description:
      - Path to the XML Jinja template to render before validation.
      - Relative paths are resolved from C(base_dir), or the module working directory.
    type: path
    default: xml_template.xml.j2
  base_dir:
    description:
      - Base directory used to resolve relative paths.
    type: path
  template_vars:
    description:
      - Variables used to render the Jinja template.
      - Pass the relevant play, role, inventory, group, or host variables here.
    type: dict
    default: {}
  api_key:
    description:
      - LLM API key. If omitted, C(api_key_env) and then C(OPENAI_API_KEY) are checked.
    type: str
    no_log: true
  api_key_env:
    description:
      - Environment variable name to read when C(api_key) is omitted.
    type: str
    default: LLM_API_KEY
  provider_url:
    description:
      - Full OpenAI-compatible chat-completions URL for the LLM provider.
      - May point to enterprise ChatGPT, Azure OpenAI, or a self-hosted compatible endpoint.
      - When only a base URL is provided, the module appends C(/v1/chat/completions).
    type: str
    default: https://api.openai.com/v1/chat/completions
  model:
    description:
      - Model name sent in the request body.
      - Set C(include_model) to C(false) when the provider URL already binds a deployment.
    type: str
    default: gpt-4o-mini
  include_model:
    description:
      - Whether to include C(model) in the request body.
    type: bool
    default: true
  prompt:
    description:
      - LLM instruction used for XML configuration validation.
    type: str
  temperature:
    description:
      - Sampling temperature sent to the LLM provider.
    type: float
    default: 0.0
  timeout:
    description:
      - HTTP request timeout in seconds.
    type: int
    default: 60
  validate_certs:
    description:
      - Whether to validate TLS certificates for the provider URL.
    type: bool
    default: true
  auth_header:
    description:
      - Header used to pass C(api_key).
      - Use C(api-key) for providers that expect Azure-style authentication.
    type: str
    default: Authorization
  auth_scheme:
    description:
      - Prefix used in the authentication header.
      - Set to an empty string when the provider expects the raw API key.
    type: str
    default: Bearer
  extra_headers:
    description:
      - Additional HTTP headers sent to the LLM provider.
    type: dict
    default: {}
  request_options:
    description:
      - Additional request body fields merged into the chat-completions payload.
    type: dict
    default: {}
  playbook_path:
    description:
      - Optional playbook path to include as validation context.
    type: path
  role_path:
    description:
      - Optional role directory to include as validation context.
    type: path
  inventory_path:
    description:
      - Optional inventory file or directory to include as validation context.
    type: path
  group_vars_path:
    description:
      - Optional group_vars file or directory to include as validation context.
    type: path
  host_vars_path:
    description:
      - Optional host_vars file or directory to include as validation context.
    type: path
  context_files:
    description:
      - Additional files to include as validation context.
    type: list
    elements: path
    default: []
  context_dirs:
    description:
      - Additional directories to scan for validation context files.
    type: list
    elements: path
    default: []
  extra_context:
    description:
      - Extra structured context to send to the LLM.
    type: dict
    default: {}
  max_context_bytes:
    description:
      - Maximum total bytes of file context sent to the LLM.
    type: int
    default: 20000
  fail_on_invalid:
    description:
      - Whether invalid XML/configuration should fail the Ansible task.
    type: bool
    default: true
  return_rendered:
    description:
      - Whether to return the rendered XML in module output.
      - Leave disabled when rendered configuration may contain secrets.
    type: bool
    default: false
author:
  - xml-validation-agent maintainers
"""

EXAMPLES = r"""
- name: Validate rendered XML with enterprise LLM review
  pwc.config_validation_agent.agentic_xml_validate:
    src: "{{ playbook_dir }}/templates/xml_template.xml.j2"
    template_vars: "{{ vars }}"
    api_key: "{{ lookup('ansible.builtin.env', 'LLM_API_KEY') }}"
    provider_url: "https://llm.example.com/v1/chat/completions"
    model: "enterprise-chat-model"
    playbook_path: "{{ playbook_dir }}/site.yml"
    inventory_path: "{{ inventory_file | default(omit) }}"
    group_vars_path: "{{ playbook_dir }}/../inventory/ci/group_vars"
    role_path: "{{ role_path | default(omit) }}"
  delegate_to: localhost
  run_once: true

- name: Validate through an Azure OpenAI deployment URL
  pwc.config_validation_agent.agentic_xml_validate:
    src: "{{ playbook_dir }}/templates/xml_template.xml.j2"
    template_vars: "{{ vars }}"
    api_key: "{{ lookup('ansible.builtin.env', 'AZURE_OPENAI_API_KEY') }}"
    provider_url: "{{ azure_openai_chat_completions_url }}"
    auth_header: api-key
    auth_scheme: ""
    include_model: false
  delegate_to: localhost
"""

RETURN = r"""
valid:
  description: Indicates whether the rendered XML configuration passed validation.
  type: bool
  returned: always
  sample: true
message:
  description: Validation status text.
  type: str
  returned: always
  sample: XML configuration is valid.
feedback:
  description: LLM feedback for the rendered XML configuration.
  type: str
  returned: always
suggested_fix:
  description: Suggested correction when validation fails.
  type: str
  returned: always
issues:
  description: List of local and LLM-reported issues.
  type: list
  elements: dict
  returned: always
context_files_used:
  description: Paths included as execution context.
  type: list
  elements: str
  returned: always
rendered_xml:
  description: Rendered XML content, returned only when C(return_rendered) is C(true).
  type: str
  returned: when requested
"""

DEFAULT_PROVIDER_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PROMPT = """\
You are an expert Ansible and XML configuration reviewer.
Validate the rendered XML configuration against XML correctness, likely Ansible/Jinja
rendering mistakes, and consistency with the provided playbook, role, inventory,
group_vars, host_vars, and extra execution context.

Return only a JSON object with this schema:
{
  "valid": true,
  "feedback": "short validation summary",
  "suggested_fix": "specific corrected XML, variable, or playbook guidance if invalid",
  "issues": [
    {
      "severity": "error|warning|info",
      "location": "file/path, XML element, variable, or play/task when known",
      "message": "what is wrong",
      "suggested_fix": "how to correct it"
    }
  ]
}

Set "valid" to true only when the configuration is well formed and you find no
configuration, rendering, variable, inventory, role, or playbook inconsistencies.
"""

CONTEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".ini",
    ".j2",
    ".json",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


class AgenticXmlValidateError(Exception):
    """Base error raised by validation helpers."""


class TemplateRenderError(AgenticXmlValidateError):
    """Raised when the XML Jinja template cannot be rendered."""


class LlmRequestError(AgenticXmlValidateError):
    """Raised when the LLM provider request fails."""


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True)


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "valid", "pass", "passed"}:
            return True
        if lowered in {"false", "no", "invalid", "fail", "failed"}:
            return False
    return None


def resolve_path(path_value: str | None, base_dir: str | None = None) -> Path | None:
    """Resolve a user path, preserving None for optional paths."""
    if not path_value:
        return None

    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    if not path.is_absolute() and base_dir:
        path = Path(base_dir) / path
    return path.resolve(strict=False)


def read_limited_text(path: Path, remaining_bytes: int) -> tuple[str, bool]:
    """Read text content, truncating to the remaining context budget."""
    if remaining_bytes <= 0:
        return "", True

    raw = path.read_bytes()
    truncated = len(raw) > remaining_bytes
    raw = raw[:remaining_bytes]
    return raw.decode("utf-8", errors="replace"), truncated


def _context_file_candidates(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []

    candidates = [
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in CONTEXT_SUFFIXES
    ]
    return sorted(candidates)


def collect_execution_context(
    *,
    base_dir: str | None = None,
    playbook_path: str | None = None,
    role_path: str | None = None,
    inventory_path: str | None = None,
    group_vars_path: str | None = None,
    host_vars_path: str | None = None,
    context_files: list[str] | None = None,
    context_dirs: list[str] | None = None,
    max_context_bytes: int = 20000,
) -> dict[str, Any]:
    """Collect playbook, role, inventory, and vars files for LLM context."""
    requested_paths: list[tuple[str, str]] = []

    for label, value in (
        ("playbook", playbook_path),
        ("role", role_path),
        ("inventory", inventory_path),
        ("group_vars", group_vars_path),
        ("host_vars", host_vars_path),
    ):
        if value:
            requested_paths.append((label, value))

    for file_path in context_files or []:
        requested_paths.append(("context_file", file_path))

    for dir_path in context_dirs or []:
        requested_paths.append(("context_dir", dir_path))

    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    bytes_used = 0
    budget = max(max_context_bytes, 0)

    for label, raw_path in requested_paths:
        resolved = resolve_path(raw_path, base_dir)
        if not resolved or not resolved.exists():
            missing.append(str(raw_path))
            continue

        for file_path in _context_file_candidates(resolved):
            remaining = budget - bytes_used
            content, truncated = read_limited_text(file_path, remaining)
            if not content and truncated:
                entries.append(
                    {
                        "label": label,
                        "path": str(file_path),
                        "content": "",
                        "truncated": True,
                    }
                )
                return {
                    "files": entries,
                    "missing": missing,
                    "bytes_used": bytes_used,
                    "truncated": True,
                }

            entries.append(
                {
                    "label": label,
                    "path": str(file_path),
                    "content": content,
                    "truncated": truncated,
                }
            )
            bytes_used += len(content.encode("utf-8", errors="replace"))

            if truncated or bytes_used >= budget:
                return {
                    "files": entries,
                    "missing": missing,
                    "bytes_used": bytes_used,
                    "truncated": True,
                }

    return {
        "files": entries,
        "missing": missing,
        "bytes_used": bytes_used,
        "truncated": False,
    }


def _render_with_ansible_templar(template_path: Path, template_vars: dict[str, Any]) -> str:
    """Render with Ansible's templating engine when ansible-core is available."""
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar

    template_text = template_path.read_text(encoding="utf-8")
    templar = Templar(loader=DataLoader(), variables=template_vars or {})
    rendered = templar.template(template_text, preserve_trailing_newlines=True)
    return rendered if isinstance(rendered, str) else _as_text(rendered)


def _render_with_plain_jinja(template_path: Path, template_vars: dict[str, Any]) -> str:
    """Render with Jinja2 when Ansible's templating engine is unavailable."""
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:
        raise TemplateRenderError(
            "ansible-core or Jinja2 is required to render XML templates on the controller."
        ) from exc

    environment = Environment(
        autoescape=False,
        keep_trailing_newline=True,
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
    )
    template = environment.get_template(template_path.name)
    return template.render(template_vars or {})


def render_jinja_template(template_path: Path, template_vars: dict[str, Any]) -> str:
    """Render a local Jinja template, preferring Ansible-compatible syntax."""
    try:
        return _render_with_ansible_templar(template_path, template_vars)
    except ImportError:
        pass
    except Exception as exc:
        message = f"Failed to render Ansible Jinja template {template_path}: {exc}"
        raise TemplateRenderError(message) from exc

    try:
        return _render_with_plain_jinja(template_path, template_vars)
    except Exception as exc:
        message = f"Failed to render Jinja template {template_path}: {exc}"
        raise TemplateRenderError(message) from exc


def validate_xml_payload(xml_content: str) -> tuple[bool, str | None]:
    """Parse XML content and return a success flag plus optional parse error."""
    try:
        element_tree.fromstring(xml_content)
    except element_tree.ParseError as parse_error:
        return False, str(parse_error)

    return True, None


def resolve_api_key(
    explicit_api_key: str | None,
    api_key_env: str | None,
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> str:
    """Resolve the LLM API key from a module parameter or supported env vars."""
    if explicit_api_key:
        return explicit_api_key

    env = environ or os.environ
    candidate_names = [api_key_env] if api_key_env else []
    if "OPENAI_API_KEY" not in candidate_names:
        candidate_names.append("OPENAI_API_KEY")

    for env_name in candidate_names:
        if env_name and env.get(env_name):
            return str(env[env_name])

    names = ", ".join(name for name in candidate_names if name)
    raise LlmRequestError(f"LLM API key is required. Set api_key or one of: {names}.")


def normalize_provider_url(provider_url: str | None) -> str:
    """Normalize provider URL when only a base endpoint is provided."""
    raw = (provider_url or DEFAULT_PROVIDER_URL).strip()
    if not raw:
        return DEFAULT_PROVIDER_URL

    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw

    path = parsed.path or ""
    normalized_path = path.rstrip("/")
    if normalized_path.endswith("/chat/completions"):
        return raw
    if normalized_path in {"", "/v1"}:
        suffix = "/v1/chat/completions" if normalized_path == "" else "/chat/completions"
        return urllib.parse.urlunparse(parsed._replace(path=f"{normalized_path}{suffix}"))

    return raw


def build_validation_prompt(
    *,
    prompt: str,
    src: str,
    rendered_xml: str,
    local_xml_error: str | None,
    execution_context: dict[str, Any],
    extra_context: dict[str, Any],
) -> str:
    """Build the user message sent to the LLM provider."""
    payload = {
        "instructions": prompt,
        "template_source": src,
        "local_xml_parse_error": local_xml_error,
        "rendered_xml": rendered_xml,
        "execution_context": execution_context,
        "extra_context": extra_context or {},
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def query_llm_provider(
    *,
    provider_url: str,
    api_key: str,
    model: str | None,
    include_model: bool,
    user_prompt: str,
    timeout: int,
    validate_certs: bool,
    temperature: float,
    auth_header: str,
    auth_scheme: str | None,
    extra_headers: dict[str, Any] | None = None,
    request_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat-completions endpoint."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    auth_value = f"{auth_scheme} {api_key}".strip() if auth_scheme else api_key
    if auth_header:
        headers[auth_header] = auth_value

    for key, value in (extra_headers or {}).items():
        if value is not None:
            headers[str(key)] = str(value)

    body: dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": "Return only machine-readable JSON for XML validation.",
            },
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    if include_model and model:
        body["model"] = model
    body.update(request_options or {})

    request = urllib.request.Request(
        provider_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    ssl_context = None if validate_certs else ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise LlmRequestError(
            f"LLM provider returned HTTP {exc.code}: {body_text[:1000]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise LlmRequestError(f"LLM provider request failed: {exc}") from exc

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LlmRequestError("LLM provider returned a non-JSON HTTP response.") from exc


def _content_blocks_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(_as_text(item.get("text") or item.get("content")))
            else:
                parts.append(_as_text(item))
        return "\n".join(part for part in parts if part)
    return _as_text(content)


def extract_llm_content(response_payload: dict[str, Any]) -> str:
    """Extract assistant text from common LLM response shapes."""
    choices = response_payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict) and "content" in message:
                return _content_blocks_to_text(message["content"])
            if "text" in first_choice:
                return _as_text(first_choice["text"])

    if "output_text" in response_payload:
        return _as_text(response_payload["output_text"])

    output = response_payload.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict):
                parts.append(_content_blocks_to_text(item.get("content")))
        if parts:
            return "\n".join(part for part in parts if part)

    return _as_text(response_payload)


def extract_json_object(text: str) -> str:
    """Extract the first likely JSON object from plain or fenced model output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response.")
    return stripped[start : end + 1]


def parse_llm_decision(llm_text: str) -> dict[str, Any]:
    """Parse and normalize the LLM validation decision."""
    try:
        parsed = json.loads(extract_json_object(llm_text))
    except (ValueError, json.JSONDecodeError):
        return {
            "valid": False,
            "feedback": llm_text.strip(),
            "suggested_fix": "The LLM response was not valid JSON. Re-run with a stricter prompt.",
            "issues": [
                {
                    "severity": "error",
                    "location": "llm_response",
                    "message": "Unable to parse LLM validation response as JSON.",
                    "suggested_fix": "Ensure the provider returns only the requested JSON object.",
                }
            ],
        }

    valid = _coerce_bool(parsed.get("valid"))
    if valid is None:
        valid = False

    issues = parsed.get("issues") or []
    if isinstance(issues, str):
        issues = [{"severity": "info", "location": "llm_response", "message": issues}]
    elif not isinstance(issues, list):
        issues = [
            {
                "severity": "info",
                "location": "llm_response",
                "message": _as_text(issues),
            }
        ]

    return {
        "valid": valid,
        "feedback": _as_text(parsed.get("feedback") or parsed.get("message")).strip(),
        "suggested_fix": _as_text(
            parsed.get("suggested_fix")
            or parsed.get("suggestion")
            or parsed.get("fix")
            or ""
        ).strip(),
        "issues": issues,
    }


def _invalid_render_result(src: str, error: Exception) -> dict[str, Any]:
    return {
        "changed": False,
        "valid": False,
        "message": "XML template rendering failed.",
        "feedback": str(error),
        "suggested_fix": (
            "Fix the template path, Jinja syntax, or missing template_vars before "
            "running LLM validation."
        ),
        "issues": [
            {
                "severity": "error",
                "location": src,
                "message": str(error),
                "suggested_fix": (
                    "Provide a valid template and all variables required by the Jinja file."
                ),
            }
        ],
        "context_files_used": [],
    }


def run_validation(params: dict[str, Any]) -> dict[str, Any]:
    """Render XML, collect context, query the LLM, and return module-style output."""
    base_dir = params.get("base_dir") or os.getcwd()
    max_context_bytes = params.get("max_context_bytes")
    if max_context_bytes is None:
        max_context_bytes = 20000

    src_path = resolve_path(params.get("src") or "xml_template.xml.j2", base_dir)
    src = str(src_path) if src_path else str(params.get("src"))
    if not src_path or not src_path.exists():
        return _invalid_render_result(src, FileNotFoundError(f"Template not found: {src}"))

    try:
        rendered_xml = render_jinja_template(src_path, params.get("template_vars") or {})
    except TemplateRenderError as exc:
        return _invalid_render_result(src, exc)

    local_valid, parse_error = validate_xml_payload(rendered_xml)
    execution_context = collect_execution_context(
        base_dir=base_dir,
        playbook_path=params.get("playbook_path"),
        role_path=params.get("role_path"),
        inventory_path=params.get("inventory_path"),
        group_vars_path=params.get("group_vars_path"),
        host_vars_path=params.get("host_vars_path"),
        context_files=params.get("context_files") or [],
        context_dirs=params.get("context_dirs") or [],
        max_context_bytes=max_context_bytes,
    )
    prompt = build_validation_prompt(
        prompt=params.get("prompt") or DEFAULT_PROMPT,
        src=src,
        rendered_xml=rendered_xml,
        local_xml_error=parse_error,
        execution_context=execution_context,
        extra_context=params.get("extra_context") or {},
    )

    api_key = resolve_api_key(params.get("api_key"), params.get("api_key_env"))
    llm_payload = query_llm_provider(
        provider_url=normalize_provider_url(params.get("provider_url") or DEFAULT_PROVIDER_URL),
        api_key=api_key,
        model=params.get("model") or DEFAULT_MODEL,
        include_model=params.get("include_model", True),
        user_prompt=prompt,
        timeout=params.get("timeout") or 60,
        validate_certs=params.get("validate_certs", True),
        temperature=params.get("temperature", 0.0),
        auth_header=params.get("auth_header") or "Authorization",
        auth_scheme=params.get("auth_scheme", "Bearer"),
        extra_headers=params.get("extra_headers") or {},
        request_options=params.get("request_options") or {},
    )
    llm_decision = parse_llm_decision(extract_llm_content(llm_payload))

    issues = list(llm_decision["issues"])
    if parse_error:
        issues.insert(
            0,
            {
                "severity": "error",
                "location": src,
                "message": f"Rendered XML is not well formed: {parse_error}",
                "suggested_fix": "Correct the rendered XML structure or source Jinja template.",
            },
        )

    valid = local_valid and bool(llm_decision["valid"])
    suggested_fix = llm_decision["suggested_fix"]
    if parse_error and not suggested_fix:
        suggested_fix = "Correct the XML parse error before applying the configuration."

    result: dict[str, Any] = {
        "changed": False,
        "valid": valid,
        "message": "XML configuration is valid." if valid else "XML configuration is invalid.",
        "feedback": llm_decision["feedback"],
        "suggested_fix": suggested_fix,
        "issues": issues,
        "context_files_used": [entry["path"] for entry in execution_context["files"]],
        "context_truncated": execution_context["truncated"],
        "missing_context_paths": execution_context["missing"],
        "local_xml_valid": local_valid,
        "local_xml_error": parse_error,
    }
    if params.get("return_rendered"):
        result["rendered_xml"] = rendered_xml
    return result


def run_module() -> None:
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(
        argument_spec={
            "src": {"type": "path", "required": False, "default": "xml_template.xml.j2"},
            "base_dir": {"type": "path", "required": False},
            "template_vars": {"type": "dict", "required": False, "default": {}},
            "api_key": {"type": "str", "required": False, "no_log": True},
            "api_key_env": {"type": "str", "required": False, "default": "LLM_API_KEY"},
            "provider_url": {"type": "str", "required": False, "default": DEFAULT_PROVIDER_URL},
            "model": {"type": "str", "required": False, "default": DEFAULT_MODEL},
            "include_model": {"type": "bool", "required": False, "default": True},
            "prompt": {"type": "str", "required": False, "default": DEFAULT_PROMPT},
            "temperature": {"type": "float", "required": False, "default": 0.0},
            "timeout": {"type": "int", "required": False, "default": 60},
            "validate_certs": {"type": "bool", "required": False, "default": True},
            "auth_header": {"type": "str", "required": False, "default": "Authorization"},
            "auth_scheme": {"type": "str", "required": False, "default": "Bearer"},
            "extra_headers": {"type": "dict", "required": False, "default": {}},
            "request_options": {"type": "dict", "required": False, "default": {}},
            "playbook_path": {"type": "path", "required": False},
            "role_path": {"type": "path", "required": False},
            "inventory_path": {"type": "path", "required": False},
            "group_vars_path": {"type": "path", "required": False},
            "host_vars_path": {"type": "path", "required": False},
            "context_files": {"type": "list", "elements": "path", "required": False, "default": []},
            "context_dirs": {"type": "list", "elements": "path", "required": False, "default": []},
            "extra_context": {"type": "dict", "required": False, "default": {}},
            "max_context_bytes": {"type": "int", "required": False, "default": 20000},
            "fail_on_invalid": {"type": "bool", "required": False, "default": True},
            "return_rendered": {"type": "bool", "required": False, "default": False},
        },
        supports_check_mode=True,
    )

    try:
        result = run_validation(module.params)
    except AgenticXmlValidateError as exc:
        module.fail_json(changed=False, valid=False, msg=str(exc))
    except Exception as exc:
        module.fail_json(changed=False, valid=False, msg=f"Unexpected validation error: {exc}")

    if not result["valid"] and module.params.get("fail_on_invalid", True):
        module.fail_json(msg=result["message"], **result)

    module.exit_json(**result)


def main() -> None:
    run_module()


if __name__ == "__main__":
    main()
