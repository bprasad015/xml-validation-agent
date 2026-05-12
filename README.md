# xml-validation-agent

Layered Ansible test baseline for GitHub-hosted `ubuntu-latest` runners.

## Repository Layout

- `playbooks/` integration entry points
- `roles/` reusable roles under development
- `plugins/modules/` custom Ansible modules (collection-aligned path)
- `inventory/ci/` YAML inventory plus colocated `group_vars/` and `host_vars/`
- `meta/` collection runtime metadata
- `tests/` smoke playbooks, fixtures, and unit tests
- `.github/workflows/` CI pipelines
- `galaxy.yml` collection metadata (`pwc.config_validation_agent`)

## What Is Implemented

- A sample role: `roles/xml_validation`
- A sample custom module: `plugins/modules/xml_validate.py`
- Agentic XML validation module: `plugins/modules/agentic_xml_validate.py`
- Layered tests:
  - Static linting (`yamllint`, `ansible-lint`, `ruff`)
  - Python unit tests for module logic (`pytest`)
  - Role/module smoke tests via playbooks
  - Integration playbook with idempotency rerun check

## Agentic XML Validation

`agentic_xml_validate.py` is intended to be used as
`pwc.config_validation_agent.agentic_xml_validate` when this repository is packaged as the
`pwc.config_validation_agent` collection. It renders a local `xml_template.xml.j2`, validates
the rendered XML, sends the rendered configuration plus selected playbook, role,
inventory, and vars context to an OpenAI-compatible LLM endpoint, and returns
`valid`, `feedback`, `issues`, and `suggested_fix`.

Environment fallback behavior:
- `api_key` falls back to `api_key_env` (default `LLM_API_KEY`), then `LLM_API_KEY`, then `OPENAI_API_KEY`.
- `provider_url` falls back to `provider_url_env` (default `LLM_API_URL`), then module default base URL.
- `model` falls back to `model_env` (default `LLM_MODEL`), then `gpt-4o-mini`.
- When a provider base URL is supplied, the module tries both `/v1/chat/completions` and `/chat/completions`.

Run it on the controller when template and Ansible context files are local:

```yaml
- name: Validate rendered XML with LLM feedback
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
```

For Azure-style endpoints, set `auth_header: api-key`, `auth_scheme: ""`, and
`include_model: false` when the deployment is already encoded in `provider_url`.

CI behavior:
- `workflow_dispatch` supports optional inputs:
  - `llm_provider_profile` (`organization_default` | `openai_public` | `custom`)
  - `llm_api_url` (default `https://genai-sharedservice-americas.pwc.com`)
  - `llm_model` (default `azure.gpt-4o-mini`)
- When `secrets.LLM_API_KEY` is set, agentic smoke tests call the real provider.
- In real-provider mode, CI requires only `secrets.LLM_API_KEY`; URL/model come from workflow inputs or defaults.
- When `secrets.LLM_API_KEY` is absent, CI automatically starts the local mock LLM server.

Testing with a regular OpenAI API key:
1. Set `secrets.LLM_API_KEY` to your OpenAI key.
2. Run `ansible-ci` via `workflow_dispatch`.
3. Select `llm_provider_profile: openai_public`.
The workflow will automatically use `https://api.openai.com` and `gpt-4o-mini`.

## Local Quick Start

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml

ansible-lint playbooks roles tests/playbooks
pytest tests/unit -q
ansible-playbook -i inventory/ci/hosts.yml playbooks/integration.yml
ansible-playbook -i inventory/ci/hosts.yml playbooks/integration.yml
```
