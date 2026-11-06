"""Shared validation for GitHub-style owner/repository identifiers."""

from __future__ import annotations

import re


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def is_repository_name(value: object) -> bool:
    """Return whether *value* is a non-empty owner/repository identifier."""

    return (
        isinstance(value, str)
        and _REPOSITORY.fullmatch(value.strip()) is not None
    )
