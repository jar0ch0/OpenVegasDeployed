from __future__ import annotations

from openvegas.agent.local_tools import extract_tool_instruction


def test_extract_tool_instruction_from_fenced_json():
    text = """
Here is a step.
```json
{"type":"tool_call","tool_name":"fs_read","arguments":{"path":"README.md"},"shell_mode":"read_only","timeout_sec":5}
```
"""
    req, cleaned = extract_tool_instruction(text)
    assert isinstance(req, dict)
    assert req["tool_name"] == "fs_read"
    assert req["arguments"]["path"] == "README.md"
    assert "```json" not in cleaned


def test_extract_tool_instruction_invalid_json_falls_back_to_text():
    text = '{"type":"tool_call","tool_name":"fs_read","arguments":'
    req, cleaned = extract_tool_instruction(text)
    assert req is None
    assert cleaned == text


def test_extract_tool_instruction_requires_tool_name_and_arguments():
    text = '{"type":"tool_call","tool_name":"fs_read"}'
    req, cleaned = extract_tool_instruction(text)
    assert req is None
    assert cleaned == text
