"""Source-neutral first-PR engine, deliberately NOT activated.

A future independently admitted writer must provide an authenticated narrow
transport and reviewed recipe. There is no CLI, token loading, registry entry,
scheduler or production activation. The public entry is READ ONLY.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from tools.generated_artifact_contract import manifest_digest, validate_payload_and_plan
from tools.generated_artifact_writer import (
    WritebackRejected, _build_verified_commit, _extract_again, _mapping,
    _read_files, _sha,
)


@dataclass(frozen=True)
class BootstrapRecipe:
    repository: str
    repository_id: int
    private: bool
    recipe_id: str
    paths: tuple[str, ...]
    limits: dict[str, int]


def _read_base(api: Any, recipe: BootstrapRecipe, base: str) -> str:
    if (type(recipe.repository_id) is not int or recipe.repository_id <= 0
            or type(recipe.private) is not bool
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", recipe.repository)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", recipe.recipe_id)
            or getattr(api, "repository", None) != recipe.repository):
        raise WritebackRejected("invalid trusted recipe identity")
    repo = _mapping(api.get(""), "repository")
    if (repo.get("id") != recipe.repository_id or repo.get("full_name") != recipe.repository
            or repo.get("private") is not recipe.private
            or repo.get("visibility") != ("private" if recipe.private else "public")
            or repo.get("default_branch") != "main"):
        raise WritebackRejected("destination identity or visibility mismatch")
    main = _mapping(api.get("/branches/main"), "main")
    if (main.get("name") != "main" or main.get("protected") is not True
            or _mapping(main.get("commit"), "main.commit").get("sha") != _sha(base, "source base")):
        raise WritebackRejected("main protection or expected source base not established")
    if api.get("/rulesets") != []:
        raise WritebackRejected("rulesets require separate admission")
    commit = _mapping(api.get("/git/commits/" + base), "base commit")
    return _sha(_mapping(commit.get("tree"), "base.tree").get("sha"), "base tree")


def _receipt(recipe: BootstrapRecipe, base: str, files: list[dict]) -> str:
    return manifest_digest({
        "schema": "generated-pr-bootstrap.v1", "repository_id": recipe.repository_id,
        "repository": recipe.repository, "private": recipe.private, "recipe": recipe.recipe_id,
        "base": base, "files": sorted(files, key=lambda f: f["path"]),
    })


def _message(receipt: str) -> str:
    return "chore: apply verified generated artifacts\n\nGenerated-PR-Bootstrap-V1: sha256:" + receipt


def _observe(api: Any, recipe: BootstrapRecipe, branch: str, base: str,
             receipt: str, verified: dict[str, bytes], changes: list[dict]) -> dict:
    refs = api.get("/git/matching-refs/heads/" + urllib.parse.quote(branch, safe="/"))
    if not isinstance(refs, list) or len(refs) > 1:
        raise WritebackRejected("ambiguous branch observation")
    name = "refs/heads/" + branch
    owner = recipe.repository.split("/")[0]
    prs = api.get("/pulls?state=all&head=" + urllib.parse.quote(owner + ":" + branch, safe=""))
    if not isinstance(prs, list) or len(prs) > 1:
        raise WritebackRejected("ambiguous PR observation")
    if not refs:
        if prs:
            raise WritebackRejected("PR exists without its exact branch")
        return {"status": "CREATE_BRANCH"}
    ref = _mapping(refs[0], "branch ref")
    if ref.get("ref") != name:
        raise WritebackRejected("branch prefix collision")
    head = _sha(_mapping(ref.get("object"), "ref.object").get("sha"), "branch head")
    live = _mapping(api.get("/branches/" + urllib.parse.quote(branch, safe="/")), "branch")
    if (live.get("name") != branch or live.get("protected") is not False
            or _mapping(live.get("commit"), "branch.commit").get("sha") != head):
        raise WritebackRejected("branch observation changed")
    _verify_commit(api, base, head, receipt, verified, changes)
    if not prs:
        return {"status": "CREATE_PR", "head": head}
    pr = _mapping(prs[0], "PR")
    h = _mapping(pr.get("head"), "PR head")
    b = _mapping(pr.get("base"), "PR base")
    if (pr.get("state") != "open" or h.get("ref") != branch or h.get("sha") != head
            or b.get("ref") != "main"
            or any(_mapping(x.get("repo"), "PR repository").get("id") != recipe.repository_id
                   or x["repo"].get("full_name") != recipe.repository for x in (h,b))
            or type(pr.get("number")) is not int or pr["number"] <= 0):
        raise WritebackRejected("existing PR closed, moved or belongs to another target")
    return {"status": "NO_OP_REPLAY", "head": head, "pr_number": pr["number"]}


def _verify_commit(api: Any, base: str, head: str, receipt: str,
                   verified: dict[str, bytes], changes: list[dict]) -> None:
    commit = _mapping(api.get("/git/commits/" + head), "candidate commit")
    if (commit.get("message") != _message(receipt)
            or not isinstance(commit.get("parents"), list) or len(commit["parents"]) != 1
            or _mapping(commit["parents"][0], "parent").get("sha") != base):
        raise WritebackRejected("branch receipt or parent mismatch")
    tree = _sha(_mapping(commit.get("tree"), "candidate tree").get("sha"), "candidate tree SHA")
    if _read_files(api, tree, list(verified)) != verified:
        raise WritebackRejected("candidate bytes do not match")
    compare = _mapping(api.get("/compare/" + base + "..." + head), "comparison")
    diff = compare.get("files")
    if (compare.get("status") != "ahead" or compare.get("ahead_by") != 1
            or not isinstance(diff, list) or len(diff) != len(changes)
            or any(not isinstance(f, dict) or f.get("status") not in ("added","modified") for f in diff)
            or {f.get("filename") for f in diff} != {f["path"] for f in changes}):
        raise WritebackRejected("candidate contains unexpected diff")


def _prepare(api: Any, recipe: BootstrapRecipe, base: str, files: list[dict],
             archive: bytes) -> tuple[dict, dict[str, bytes], str, str]:
    tree = _read_base(api, recipe, base)
    paths = list(recipe.paths)
    # Validate the exact trusted recipe and ZIP before any path-based Git reads.
    validate_payload_and_plan(paths, recipe.limits, files, archive, existing_files={})
    before = _read_files(api, tree, paths)
    payload = validate_payload_and_plan(paths, recipe.limits, files, archive, existing_files=before)
    verified = _extract_again(archive, {"files": files}, recipe.limits["max_file_bytes"])
    receipt = _receipt(recipe, base, files)
    branch = "artifact/writeback-" + recipe.recipe_id + "/" + receipt
    return payload, verified, branch, tree


def plan_new_pr(api: Any, recipe: BootstrapRecipe, base: str, files: list[dict],
                archive: bytes) -> dict:
    """Authenticated reads only; never accepts a caller claim as write authority."""
    payload, verified, branch, tree = _prepare(api, recipe, base, files, archive)
    receipt = _receipt(recipe, base, files)
    observed = ({"status": "NO_OP"} if payload["status"] == "NO_OP" else
                _observe(api, recipe, branch, base, receipt, verified, payload["changes"]))
    return {**payload, **observed, "branch": branch, "receipt": receipt,
            "writer_authorized": False, "writes_performed": False}


def _execute_admitted_new_pr(api: Any, recipe: BootstrapRecipe, base: str,
                            files: list[dict], archive: bytes) -> dict:
    """Dormant effect core, exercised ONLY with fake transport in tests.

    No production caller may import this until independently accepted scoped
    transport, producer authentication and Human approval exist. The reviewed
    adapter must enforce repository, exact branch, exact bytes and endpoints.
    This helper itself is not authentication or authorization.
    """
    payload, verified, branch, tree = _prepare(api, recipe, base, files, archive)
    receipt = _receipt(recipe, base, files)
    if payload["status"] == "NO_OP":
        return {"status": "NO_OP", "writes_performed": False}
    state = _observe(api, recipe, branch, base, receipt, verified, payload["changes"])
    if state["status"] == "NO_OP_REPLAY":
        return {**state, "writes_performed": False}
    if state["status"] == "CREATE_BRANCH":
        _read_base(api, recipe, base)
        head = _build_verified_commit(api, base_head=base, base_tree=tree,
                                      changes=payload["changes"], verified=verified,
                                      message=_message(receipt))
        _verify_commit(api, base, head, receipt, verified, payload["changes"])
        _read_base(api, recipe, base)
        # Create only a new ref. Never PATCH an existing ref or force an update.
        api.post("/git/refs", {"ref": "refs/heads/" + branch, "sha": head})
        state = _observe(api, recipe, branch, base, receipt, verified, payload["changes"])
    if state["status"] != "CREATE_PR":
        raise WritebackRejected("unexpected branch/PR state after creation")
    # No atomic expected-head field exists on PR creation. Re-read the exact
    # branch and main just before the request; postread detects remaining race.
    latest = _observe(api, recipe, branch, base, receipt, verified, payload["changes"])
    if latest != state:
        raise WritebackRejected("branch or PR changed before creation")
    _read_base(api, recipe, base)
    api.post("/pulls", {"title": "chore: apply verified generated artifacts",
                       "body": "Generated-PR-Bootstrap-V1: sha256:" + receipt,
                       "head": branch, "base": "main"})
    state = _observe(api, recipe, branch, base, receipt, verified, payload["changes"])
    if state["status"] != "NO_OP_REPLAY":
        raise WritebackRejected("post-create PR readback not established")
    return {**state, "status": "PR_CREATED", "writes_performed": True,
            "ci_verified": False}
