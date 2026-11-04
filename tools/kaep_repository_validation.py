"""Shared repository-name validation for KAEP read paths.

This module deliberately contains only the repository locator pattern. Keeping
it separate prevents public projections from importing the authenticated Inbox
transport just to validate a locator.
"""
from __future__ import annotations

import re


REPOSITORY = re.compile(r"kinoko34077/[A-Za-z0-9_.-]+\Z")
