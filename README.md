# xml-validation-agent

Layered Ansible test baseline for GitHub-hosted `ubuntu-latest` runners.

## Repository Layout

- `playbooks/` integration entry points
- `roles/` reusable roles under development
- `plugins/modules/` custom Ansible modules (collection-aligned path)
- `inventories/`, `group_vars/`, `host_vars/` CI inventory and variables
- `tests/` smoke playbooks, fixtures, and unit tests
- `.github/workflows/` CI pipelines

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
`pwc.ansible.agentic_xml_validate` when this repository is packaged as the
`pwc.ansible` collection. It renders a local `xml_template.xml.j2`, validates
the rendered XML, sends the rendered configuration plus selected playbook, role,
inventory, and vars context to an OpenAI-compatible LLM endpoint, and returns
`valid`, `feedback`, `issues`, and `suggested_fix`.

Run it on the controller when template and Ansible context files are local:

```yaml
- name: Validate rendered XML with LLM feedback
  pwc.ansible.agentic_xml_validate:
    src: "{{ playbook_dir }}/templates/xml_template.xml.j2"
    template_vars: "{{ vars }}"
    api_key: "{{ lookup('ansible.builtin.env', 'LLM_API_KEY') }}"
    provider_url: "https://llm.example.com/v1/chat/completions"
    model: "enterprise-chat-model"
    playbook_path: "{{ playbook_dir }}/site.yml"
    inventory_path: "{{ inventory_file | default(omit) }}"
    group_vars_path: "{{ playbook_dir }}/../group_vars"
    role_path: "{{ role_path | default(omit) }}"
  delegate_to: localhost
  run_once: true
```

For Azure-style endpoints, set `auth_header: api-key`, `auth_scheme: ""`, and
`include_model: false` when the deployment is already encoded in `provider_url`.

## Local Quick Start

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml

ansible-lint playbooks roles tests/playbooks
pytest tests/unit -q
ansible-playbook -i inventories/ci/hosts.ini playbooks/integration.yml
ansible-playbook -i inventories/ci/hosts.ini playbooks/integration.yml
```
