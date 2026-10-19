"""IDS W1.4 writer boundary (pre-activation, fail-closed).

No workflow currently calls this module. A separate reviewed admission and
immutable pinned workflow are required before effectful execution.
"""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Mapping
from typing import Any

from tools.generated_artifact_contract import ArtifactRejected

REPOSITORY = "kinoko34077/IDS-Composit"
RECIPE = "ids-known-merge-v0.2"
BRANCH_PREFIX = "artifact/writeback-ids/"
OUTPUTS = frozenset({
    "data/known/generated/known-index-v0.2.json",
    "data/known/reports/known-index-v0.2.json",
})
MAX_FILE_BYTES = 24 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
# Deliberately not activated: the current admission verifier rejects IDS write.
WRITER_ACTIVATED = False


def validate_target(repository: str, recipe: str, branch: str, expected_head: str) -> None:
    if (repository, recipe) != (REPOSITORY, RECIPE):
        raise ArtifactRejected("IDS writer repository or recipe mismatch")
    if not isinstance(branch, str) or not re.fullmatch(
        r"artifact/writeback-ids/[A-Za-z0-9][A-Za-z0-9._-]*", branch
    ):
        raise ArtifactRejected("IDS writer target must be an admitted scratch branch")
    if not isinstance(expected_head, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ArtifactRejected("IDS writer expected HEAD must be an exact SHA")


def validate_outputs(outputs: Mapping[str, bytes]) -> None:
    if not isinstance(outputs, Mapping) or set(outputs) != OUTPUTS:
        raise ArtifactRejected("IDS writer output path set differs from fixed two-file recipe")
    total = 0
    for path in sorted(OUTPUTS):
        payload = outputs[path]
        if not isinstance(payload, bytes) or len(payload) > MAX_FILE_BYTES:
            raise ArtifactRejected("IDS writer file is not bounded bytes")
        total += len(payload)
    if total > MAX_TOTAL_BYTES:
        raise ArtifactRejected("IDS writer combined output exceeds size ceiling")


class NarrowIdsWriteApi:
    """Minimal Git object write surface; never permits default-branch mutation."""

    def __init__(self, transport: Any, branch: str, expected_head: str):
        validate_target(getattr(transport, "repository", ""), RECIPE, branch, expected_head)
        self.repository = REPOSITORY
        self._transport = transport
        self._branch = branch
        self._patch_ref = "/git/refs/heads/" + urllib.parse.quote(branch, safe="/")

    def get(self, path: str) -> Any:
        allowed = (
            path in ("", "/rulesets")
            or path.startswith("/actions/runs/")
            or path.startswith("/actions/workflows/")
            or path.startswith("/contents/.github/workflows/verified-artifacts-rollout.yml?ref=")
            or path.startswith("/branches/")
            or path.startswith("/pulls?")
            or path.startswith("/git/commits/")
            or path.startswith("/git/trees/")
            or path.startswith("/git/blobs/")
            or path.startswith("/compare/")
        )
        if not allowed:
            raise ArtifactRejected("IDS writer unadmitted read endpoint")
        return self._transport.get(path)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        if not WRITER_ACTIVATED:
            raise ArtifactRejected("IDS privileged writer not activated")
        if path not in ("/git/blobs", "/git/trees", "/git/commits"):
            raise ArtifactRejected("IDS writer unadmitted Git mutation")
        return self._transport.post(path, dict(payload))

    def patch(self, path: str, payload: Mapping[str, Any]) -> Any:
        if not WRITER_ACTIVATED:
            raise ArtifactRejected("IDS privileged writer not activated")
        if path != self._patch_ref or set(payload) != {"sha", "force"} or payload.get("force") is not False:
            raise ArtifactRejected("IDS writer allows only non-force scratch branch updates")
        return self._transport.patch(path, dict(payload))
