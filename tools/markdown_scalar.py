"""Shared normalization for scalar values extracted from Markdown sections."""

from __future__ import annotations


def strip_scalar(value: str) -> str:
    """Trim a section value and remove one outer fenced/code wrapper."""

    value = value.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3:
            value = "\n".join(lines[1:-1]).strip()
    if len(value) >= 2 and value[0] == value[-1] == "`":
        value = value[1:-1].strip()
    return value

