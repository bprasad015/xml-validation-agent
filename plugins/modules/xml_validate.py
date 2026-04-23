#!/usr/bin/python
from __future__ import annotations

import xml.etree.ElementTree as element_tree

DOCUMENTATION = r"""
---
module: xml_validate
short_description: Validate that an XML payload is well formed.
version_added: "1.0.0"
description:
  - Parses XML content and returns a failure when the payload is malformed.
options:
  xml_content:
    description:
      - XML string content to validate.
    required: true
    type: str
author:
  - xml-validation-agent maintainers
"""

EXAMPLES = r"""
- name: Validate XML content
  xml_validate:
    xml_content: "<root><child /></root>"
"""

RETURN = r"""
valid:
  description: Indicates if XML payload is valid.
  type: bool
  returned: always
  sample: true
message:
  description: Validation status text.
  type: str
  returned: always
  sample: XML payload is well formed.
"""


def validate_xml_payload(xml_content: str) -> tuple[bool, str | None]:
    """Parse XML content and return a success flag plus optional parse error."""
    try:
        element_tree.fromstring(xml_content)
    except element_tree.ParseError as parse_error:
        return False, str(parse_error)

    return True, None


def run_module() -> None:
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(
        argument_spec={
            "xml_content": {"type": "str", "required": True},
        },
        supports_check_mode=True,
    )

    is_valid, parse_error = validate_xml_payload(module.params["xml_content"])
    if not is_valid:
        module.fail_json(
            changed=False,
            valid=False,
            msg=f"XML validation failed: {parse_error}",
            parse_error=parse_error,
        )

    module.exit_json(
        changed=False,
        valid=True,
        message="XML payload is well formed.",
    )


def main() -> None:
    run_module()


if __name__ == "__main__":
    main()
