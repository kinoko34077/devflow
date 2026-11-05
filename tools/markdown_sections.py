"""Shared scanner for top-level Markdown H2 sections."""

from __future__ import annotations

import re
from collections.abc import Iterator


_HEADING = re.compile(r"^## ([^#].*?)\s*$")
_DEVFLOW_BLOCK_BEGIN = re.compile(r"^<!--\s*DEVFLOW_[A-Z0-9_]+_BEGIN\s*-->\s*$")


def iter_h2_sections(
    body: str,
    *,
    reset_on_devflow_blocks: bool = False,
) -> Iterator[tuple[str, str]]:
    """Yield H2 names and raw bodies while preserving caller-specific policy."""

    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    current: str | None = None
    lines: list[str] = []

    for line in body.split("\n"):
        if reset_on_devflow_blocks and _DEVFLOW_BLOCK_BEGIN.match(line):
            if current is not None:
                yield current, "\n".join(lines)
            current = None
            lines = []
            continue
        match = _HEADING.match(line)
        if match:
            if current is not None:
                yield current, "\n".join(lines)
            current = match.group(1).strip()
            lines = []
            continue
        if current is not None:
            lines.append(line)

    if current is not None:
        yield current, "\n".join(lines)
