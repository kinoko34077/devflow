"""S3.6 acceptance-only same-receipt replay proof.

Called only after the trusted Pilot helper has authenticated a first-party
runner and its producer artifact. No credentials or untrusted code are loaded.
"""
from __future__ import annotations

import copy
import re
import urllib.parse
from collections.abc import Mapping
from typing import Any


class ReplayProbeRejected(Exception):
    """Failure may occur after a real branch write: manual recovery is required."""

    def __init__(self, reason: str, *, first_committed: bool = False,
                 previous_head: str | None = None, new_head: str | None = None):
        super().__init__(reason)
        self.first_committed = first_committed
        self.previous_head = previous_head
        self.new_head = new_head


class ReadOnlyReplayApi:
    """Second invocation may read GitHub state but cannot mutate Git objects/refs."""

    def __init__(self, api: Any):
        self._api = api
        self.repository = api.repository
        self.blocked_mutations = 0

    def get(self, path: str) -> Any:
        return self._api.get(path)

    def post(self, path: str, payload: Any) -> None:
        self.blocked_mutations += 1
        raise ReplayProbeRejected("second invocation attempted Git mutation")

    def patch(self, path: str, payload: Any) -> None:
        self.blocked_mutations += 1
        raise ReplayProbeRejected("second invocation attempted Git mutation")


def _exact_sha(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{40}", value) is None:
        raise ReplayProbeRejected("invalid exact commit SHA")
    return value


def _head(api: Any, branch: str) -> str:
    response = api.get("/branches/" + urllib.parse.quote(branch, safe="/"))
    if not isinstance(response, dict) or not isinstance(response.get("commit"), dict):
        raise ReplayProbeRejected("branch readback unavailable")
    return _exact_sha(response["commit"].get("sha"))


def probe_exact_replay(api: Any, policy: Mapping[str, Any],
                       admission: Mapping[str, Any], manifest: Mapping[str, Any],
                       archive: bytes, *, verified_writeback: Any) -> dict[str, Any]:
    """Commit once, check replay without mutation, and check exact head again.

    Reuse the original authenticated policy/admission/manifest/archive objects.
    A failure after the first COMMITTED result never triggers automatic retry
    or rollback, even if the live branch has subsequently moved.
    """
    snapshot = copy.deepcopy((policy, admission, manifest))
    first = verified_writeback(api, policy, admission, manifest, archive, dry_run=False)
    if not isinstance(first, dict) or first.get("status") != "COMMITTED" or first.get("writes_performed") is not True:
        raise ReplayProbeRejected("first invocation did not confirm COMMITTED")
    # As soon as COMMITTED is reported, every subsequent failure is classified
    # as post-write, including a malformed SHA in the returned result.
    previous = first.get("previous_head")
    new = first.get("new_head")
    try:
        previous = _exact_sha(previous)
        new = _exact_sha(new)
        if previous != admission.get("expected_head") or previous == new:
            raise ReplayProbeRejected("first commit heads inconsistent with admission")
        if (policy, admission, manifest) != snapshot:
            raise ReplayProbeRejected("trusted replay inputs mutated during commit")
        if _head(api, admission["branch"]) != new:
            raise ReplayProbeRejected("first commit does not own target branch")
        commit = api.get("/git/commits/" + new)
        if (not isinstance(commit, dict) or
                not isinstance(commit.get("parents"), list) or
                len(commit["parents"]) != 1 or
                not isinstance(commit["parents"][0], dict) or
                commit["parents"][0].get("sha") != previous):
            raise ReplayProbeRejected("first commit parent mismatch")
        replay_api = ReadOnlyReplayApi(api)
        second = verified_writeback(replay_api, policy, admission, manifest, archive, dry_run=False)
        if (not isinstance(second, dict) or
                second.get("status") != "NO_OP_REPLAY" or
                second.get("writes_performed") is not False or
                second.get("target_head") != new or
                second.get("ci_verified") is not False or
                replay_api.blocked_mutations != 0):
            raise ReplayProbeRejected("exact receipt replay not proved")
        if (policy, admission, manifest) != snapshot:
            raise ReplayProbeRejected("trusted replay inputs mutated during replay")
        if _head(api, admission["branch"]) != new:
            raise ReplayProbeRejected("branch moved following replay")
    except Exception as exc:
        raise ReplayProbeRejected(
            "replay proof failed after COMMITTED; manual readback/recovery required",
            first_committed=True, previous_head=previous if isinstance(previous, str) else None,
            new_head=new if isinstance(new, str) else None,
        ) from exc
    return {
        "status": "REPLAY_VERIFIED",
        "first_status": "COMMITTED",
        "second_status": "NO_OP_REPLAY",
        "writes_performed": True,
        "second_writes_performed": False,
        "previous_head": previous,
        "new_head": new,
        "ci_verified": False,
    }
