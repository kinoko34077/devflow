"""Fail-closed validation for public KAEP Issue and comment locators."""
from __future__ import annotations

import re
from typing import Any


ISSUE_URL = re.compile(
    r"https://github\.com/(kinoko34077/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)\Z"
)
# Compatibility name used by presentation validators; ISSUE_URL is the
# canonical capture-capable pattern for KAEP Issue locators.
ISSUE_LINK = ISSUE_URL
API_ISSUE_URL = re.compile(
    r"https://api\.github\.com/repos/(kinoko34077/[A-Za-z0-9_.-]+)"
    r"/issues/([1-9][0-9]*)\Z"
)
COMMENT_LINK = re.compile(
    r"https://github\.com/kinoko34077/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*"
    r"#issuecomment-[1-9][0-9]*\Z"
)

def owner_issue_url(repository: str, issue: int) -> str:
    """Format a canonical owner Issue URL after caller-side validation."""
    return f"https://github.com/{repository}/issues/{issue}"


def owner_comment_url(repository: str, issue: int, comment: int) -> str:
    """Format a canonical owner Issue-comment URL after caller-side validation."""
    return f"{owner_issue_url(repository, issue)}#issuecomment-{comment}"


def safe_issue_link(value: Any) -> str | None:
    """Return a valid owner Issue URL, otherwise ``None``."""
    return value if type(value) is str and ISSUE_LINK.fullmatch(value) else None


def safe_comment_link(value: Any) -> str | None:
    """Return a valid owner Issue-comment URL, otherwise ``None``."""
    return value if type(value) is str and COMMENT_LINK.fullmatch(value) else None
