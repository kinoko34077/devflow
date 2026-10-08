"""Trusted writeback core for verified generated-artifact bytes (S3, no CLI).

This module must be executed ONLY in a reviewed/pinned writer environment
with a job-scoped token. Never import or execute source-repository code here.
The caller must authenticate the producer run/source/workflow and admission
independently; the untrusted manifest is never authorization.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping
from typing import Any

try:
    from .generated_artifact_contract import (
        ArtifactRejected, manifest_digest, validate_and_plan,
    )
except ImportError:
    from generated_artifact_contract import ArtifactRejected, manifest_digest, validate_and_plan


class WritebackRejected(ArtifactRejected):
    """Refuse a write without widening the accepted scope."""


class GitHubWriteApi:
    """Minimal authenticated Git Data REST transport; no credential output."""

    def __init__(self, repository: str, token: str, *, opener=None, api_base="https://api.github.com"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise WritebackRejected("invalid repository identity")
        if not token:
            raise WritebackRejected("a job-scoped GitHub token is required")
        self.repository = repository
        self.token = token
        self.opener = opener or urllib.request.urlopen
        self.api_base = api_base.rstrip("/")

    def _request(self, method: str, path: str, payload: Any = None) -> Any:
        if method not in ("GET", "POST", "PATCH") or not path.startswith("/"):
            raise WritebackRejected("unsupported GitHub API operation")
        data = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        request = urllib.request.Request(
            self.api_base + "/repos/" + self.repository + path,
            method=method, data=data,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise WritebackRejected(f"GitHub API {method} refused with HTTP {exc.code}") from None
        except (OSError, ValueError) as exc:
            raise WritebackRejected(f"GitHub API {method} failed ({type(exc).__name__})") from None

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: Any) -> Any:
        return self._request("POST", path, payload)

    def patch(self, path: str, payload: Any) -> Any:
        return self._request("PATCH", path, payload)


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise WritebackRejected(f"{name} is not an exact 40-character SHA")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise WritebackRejected(f"{name} must be an object")
    return value


def _request_path(branch: str) -> str:
    return urllib.parse.quote(branch, safe="/")


def _read_target(api: GitHubWriteApi, policy: Mapping[str, Any], admission: Mapping[str, Any]) -> dict:
    """Read trustworthy metadata rather than trusting manifests or the caller."""
    repo = api.get("")
    if not isinstance(repo, dict) or repo.get("full_name") != api.repository:
        raise WritebackRejected("repository identity mismatch")
    default = repo.get("default_branch")
    if not default or default != policy.get("default_branch"):
        raise WritebackRejected("repository default branch differs from pinned policy")
    if api.repository != policy.get("repository") or admission.get("repository") != api.repository:
        raise WritebackRejected("repository policy/admission mismatch")
    branch = admission["branch"]
    if branch == default:
        raise WritebackRejected("default branch is forbidden")
    live = api.get("/branches/" + _request_path(branch))
    if not isinstance(live, dict) or live.get("protected") is not False:
        raise WritebackRejected("branch protection is enabled or cannot be verified")
    head = _sha(_mapping(live.get("commit"), "branch.commit").get("sha"), "live head")
    # A trusted writer must see one existing PR owned by this exact repository.
    pulls = api.get(
        "/pulls?state=open&head=" +
        urllib.parse.quote(api.repository.split("/")[0] + ":" + branch, safe="")
    )
    if not isinstance(pulls, list) or len(pulls) != 1:
        raise WritebackRejected("target must be exactly one open same-repo PR branch")
    pr = pulls[0]
    if (
        pr.get("state") != "open"
        or _mapping(pr.get("head"), "PR.head").get("ref") != branch
        or _mapping(pr["head"].get("repo"), "PR.head.repo").get("full_name") != api.repository
        or _mapping(pr.get("base"), "PR.base").get("repo", {}).get("full_name") != api.repository
    ):
        raise WritebackRejected("target PR identity does not match")
    # If GitHub fails to provide ruleset visibility, refuse, not guess.
    rulesets = api.get("/rulesets")
    if not isinstance(rulesets, list):
        raise WritebackRejected("ruleset state unavailable")
    # Any configured ruleset needs a separately accepted impact evaluation.
    if rulesets:
        raise WritebackRejected("repository rulesets require explicit audit for writer admission")
    commit = api.get("/git/commits/" + head)
    parents = commit.get("parents") if isinstance(commit, dict) else None
    tree = _mapping(commit.get("tree") if isinstance(commit, dict) else None, "commit.tree")
    tree_sha = _sha(tree.get("sha"), "tree_sha")
    return {"head": head, "tree_sha": tree_sha, "pr_number": pr.get("number"), "parents": parents}


def _read_files(api: GitHubWriteApi, root_tree_sha: str, paths: list[str]) -> dict[str, bytes | None]:
    """Walk Git trees by path component; reject symlink, submodule and tree targets."""
    tree_cache: dict[str, dict] = {}

    def children(tree_sha: str) -> dict:
        if tree_sha not in tree_cache:
            response = api.get("/git/trees/" + tree_sha)
            if not isinstance(response, dict) or not isinstance(response.get("tree"), list):
                raise WritebackRejected("Git tree listing unavailable")
            entries = response["tree"]
            if len({e.get("path") for e in entries}) != len(entries):
                raise WritebackRejected("ambiguous Git tree entries")
            tree_cache[tree_sha] = {e["path"]: e for e in entries}
        return tree_cache[tree_sha]

    observed: dict[str, bytes | None] = {}
    for path in paths:
        parts = path.split("/")
        sha = root_tree_sha
        entry = None
        for index, part in enumerate(parts):
            entry = children(sha).get(part)
            if entry is None:
                observed[path] = None
                break
            if index < len(parts) - 1:
                if entry.get("mode") != "040000" or entry.get("type") != "tree":
                    raise WritebackRejected("generated path parent is not a directory")
                sha = _sha(entry.get("sha"), "directory SHA")
            else:
                # In S3 all existing generated outputs must be regular non-executable blobs.
                if entry.get("mode") != "100644" or entry.get("type") != "blob":
                    raise WritebackRejected("existing target is symlink, submodule, directory or executable")
                blob = api.get("/git/blobs/" + _sha(entry.get("sha"), "blob SHA"))
                if not isinstance(blob, dict) or blob.get("encoding") != "base64":
                    raise WritebackRejected("Git blob response encoding unavailable")
                try:
                    value = base64.b64decode(blob.get("content", ""), validate=False)
                except (ValueError, TypeError) as exc:
                    raise WritebackRejected("invalid Git blob bytes") from exc
                if len(value) > 100 * 1024 * 1024:
                    raise WritebackRejected("existing file exceeds safe read ceiling")
                observed[path] = value
    return observed


def _extract_again(archive_bytes: bytes, manifest: Mapping[str, Any], max_file_bytes: int) -> dict[str, bytes]:
    """Read only pre-validated, immutable ZIP bytes; reverify hashes."""
    expected = {entry["path"]: entry for entry in manifest["files"]}
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
        result = {}
        for path in sorted(expected):
            with archive.open(path) as member:
                payload = member.read(max_file_bytes + 1)
            if len(payload) != expected[path]["size"]:
                raise WritebackRejected("verified ZIP content size changed")
            if hashlib.sha256(payload).hexdigest() != expected[path]["sha256"]:
                raise WritebackRejected("verified ZIP member digest changed")
            result[path] = payload
    return result


def _replay_is_exact(
    api: GitHubWriteApi, admission: Mapping[str, Any], manifest: Mapping[str, Any],
    current_head: str, observed_files: Mapping[str, bytes | None],
    verified: Mapping[str, bytes],
) -> bool:
    """Only an exact single-parent receipt and exact generated diff can be a no-op replay."""
    commit = api.get("/git/commits/" + current_head)
    if not isinstance(commit, dict):
        return False
    parents = commit.get("parents")
    if not isinstance(parents, list) or len(parents) != 1:
        return False
    if parents[0].get("sha") != admission["expected_head"]:
        return False
    marker = f"Generated-Writeback-V1: sha256:{manifest_digest(manifest)}"
    if marker not in str(commit.get("message") or ""):
        return False
    if f"Producer-Run: {admission['producer_run_id']}/{admission['producer_run_attempt']}" not in str(commit.get("message") or ""):
        return False
    for path, data in verified.items():
        if observed_files.get(path) != data:
            return False
    comparison = api.get("/compare/" + admission["expected_head"] + "..." + current_head)
    if not isinstance(comparison, dict) or comparison.get("status") != "ahead" or comparison.get("ahead_by") != 1:
        return False
    changed_files = comparison.get("files")
    return (
        isinstance(changed_files, list)
        and bool(changed_files)
        and all(x.get("filename") in verified and x.get("status") in ("added", "modified")
                for x in changed_files)
    )


def verified_writeback(
    api: GitHubWriteApi,
    policy: Mapping[str, Any],
    admission: Mapping[str, Any],
    manifest: Mapping[str, Any],
    archive_bytes: bytes,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Plan or commit a verified artifact; does not dispatch CI.

    The caller must first independently authenticate the producer-run identity
    and use a pinned trusted helper. dry_run=False is ONLY for a reviewed writer
    job with a job-level contents:write grant and explicit Human approval.
    """
    target = _read_target(api, policy, admission)
    paths = policy["recipe"]["paths"]
    observed = _read_files(api, target["tree_sha"], paths)
    # Exact admission/policy/ZIP validation for all outcomes, including replay.
    archive_plan = validate_and_plan(
        policy, admission, manifest, archive_bytes,
        observed_head=admission["expected_head"],
        existing_files=observed,
    )
    verified = _extract_again(archive_bytes, manifest, policy["limits"]["max_file_bytes"])

    if target["head"] != admission["expected_head"]:
        if _replay_is_exact(api, admission, manifest, target["head"], observed, verified):
            return {**archive_plan, "status": "NO_OP_REPLAY", "writes_performed": False,
                    "target_head": target["head"], "ci_verified": False}
        raise WritebackRejected("target branch moved; no commit or retry without new admission")
    # Fresh no-op is safe, but still requires exact authenticated provenance.
    if archive_plan["status"] == "NO_OP":
        return {**archive_plan, "target_head": target["head"], "ci_verified": False}
    if dry_run:
        return {**archive_plan, "status": "DRY_RUN", "target_head": target["head"], "ci_verified": False}

    # Last observed head fence: create immutable Git objects against only that parent.
    blobs = {}
    for change in archive_plan["changes"]:
        path = change["path"]
        blob = api.post("/git/blobs", {
            "content": base64.b64encode(verified[path]).decode("ascii"),
            "encoding": "base64",
        })
        blobs[path] = _sha(_mapping(blob, "created blob").get("sha"), "created blob SHA")
    tree = api.post("/git/trees", {
        "base_tree": target["tree_sha"],
        "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blobs[path]}
                 for path in sorted(blobs)],
    })
    new_tree = _sha(_mapping(tree, "new tree").get("sha"), "new tree SHA")
    new_commit = api.post("/git/commits", {
        "message": (
            "chore: apply verified generated artifacts\n\n"
            f"Generated-Writeback-V1: sha256:{manifest_digest(manifest)}\n"
            f"Producer-Run: {admission['producer_run_id']}/{admission['producer_run_attempt']}\n"
            f"Recipe: {admission['recipe_id']}@{admission['recipe_version']}\n"
            f"Source-SHA: {admission['source_sha']}"
        ),
        "tree": new_tree,
        "parents": [target["head"]],
    })
    commit_sha = _sha(_mapping(new_commit, "new commit").get("sha"), "new commit SHA")

    # REST PATCH force:false is a non-force fast-forward-only fence: if head
    # advanced from the expected parent, this divergent sibling commit cannot land.
    again = api.get("/branches/" + _request_path(admission["branch"]))
    if not isinstance(again, dict) or again.get("protected") is not False:
        raise WritebackRejected("target protection changed before push")
    if _mapping(again.get("commit"), "head recheck").get("sha") != target["head"]:
        raise WritebackRejected("target branch moved before push")
    api.patch("/git/refs/heads/" + _request_path(admission["branch"]), {
        "sha": commit_sha, "force": False
    })
    readback = api.get("/branches/" + _request_path(admission["branch"]))
    if not isinstance(readback, dict) or _mapping(readback.get("commit"), "post-write head").get("sha") != commit_sha:
        raise WritebackRejected("post-write head drift; external recovery required")
    return {**archive_plan, "status": "COMMITTED", "writes_performed": True,
            "new_head": commit_sha, "previous_head": target["head"],
            "ci_verified": False}
