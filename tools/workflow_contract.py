from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".devflow" / "WORKFLOW.yaml"
_KEY_RE = re.compile(r"^([A-Za-z0-9_]+):(?:\s*(.*))?$")


class WorkflowContractError(ValueError):
    """Malformed or unsupported machine workflow contract."""


def _yaml_scalar(value: str) -> str:
    text = value.strip()
    if not text:
        raise WorkflowContractError("workflow contract contains an empty scalar")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    if not text or "\n" in text or "\r" in text:
        raise WorkflowContractError("workflow contract scalar is malformed")
    return text


def _parse_scalar_contract(text: str) -> tuple[dict[tuple[str, ...], str], dict[tuple[str, ...], list[str]]]:
    scalars: dict[tuple[str, ...], str] = {}
    lists: dict[tuple[str, ...], list[str]] = {}
    stack: list[tuple[int, str]] = []
    seen_keys: set[tuple[str, ...]] = set()

    for line_number, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise WorkflowContractError(f"workflow contract uses tab indentation at line {line_number}")

        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if stripped.startswith("- "):
            if not stack:
                raise WorkflowContractError(f"orphan workflow list item at line {line_number}")
            path = tuple(key for _, key in stack)
            lists.setdefault(path, []).append(_yaml_scalar(stripped[2:]))
            continue

        match = _KEY_RE.fullmatch(stripped)
        if not match:
            raise WorkflowContractError(f"unsupported workflow YAML shape at line {line_number}")

        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = match.group(1)
        path = tuple([*(item[1] for item in stack), key])
        if path in seen_keys:
            raise WorkflowContractError(f"duplicate workflow contract key: {'.'.join(path)}")
        seen_keys.add(path)

        inline = (match.group(2) or "").strip()
        if inline:
            scalars[path] = _yaml_scalar(inline)
        stack.append((indent, key))

    return scalars, lists


def _required_list(lists: Mapping[tuple[str, ...], list[str]], path: tuple[str, ...]) -> frozenset[str]:
    values = lists.get(path)
    if not values:
        raise WorkflowContractError(f"missing workflow contract list: {'.'.join(path)}")
    if len(values) != len(set(values)):
        raise WorkflowContractError(f"duplicate workflow contract list value: {'.'.join(path)}")
    return frozenset(values)


def _required_scalar(scalars: Mapping[tuple[str, ...], str], path: tuple[str, ...]) -> str:
    value = scalars.get(path)
    if value is None:
        raise WorkflowContractError(f"missing workflow contract scalar: {'.'.join(path)}")
    return value


def _section_scalar(value: str, field: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] == "`":
        text = text[1:-1].strip()
    if "\n" in text or "\r" in text:
        raise WorkflowContractError(f"invalid {field}: expected one scalar value")
    return text


@dataclass(frozen=True)
class WorkflowContract:
    work_states: frozenset[str]
    repository_states: frozenset[str]
    priorities: frozenset[str]
    risks: frozenset[str]
    types: frozenset[str]
    audit_depths: frozenset[str]
    audit_freshness_values: frozenset[str]
    excluded_repositories: frozenset[str]
    control_wait_state: str
    control_wait_project_status: str

    def validate_repository_control_sections(self, sections: Mapping[str, str]) -> None:
        checks = {
            "Repository State": self.repository_states,
            "Priority": self.priorities,
            "Risk": self.risks,
            "Type": self.types,
            "Audit Depth": self.audit_depths,
        }
        for field, allowed in checks.items():
            if field not in sections:
                continue
            value = _section_scalar(str(sections[field]), field)
            if value and value not in allowed:
                raise WorkflowContractError(f"invalid {field}: {value!r}")

        if "Work Status" in sections:
            value = _section_scalar(str(sections["Work Status"]), "Work Status")
            allowed = self.work_states | {self.control_wait_state}
            if value and value not in allowed:
                raise WorkflowContractError(f"invalid Work Status: {value!r}")


def load_workflow_contract(path: Path | str = DEFAULT_WORKFLOW_PATH) -> WorkflowContract:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowContractError(f"cannot read workflow contract: {source}") from exc

    scalars, lists = _parse_scalar_contract(text)
    return WorkflowContract(
        work_states=_required_list(lists, ("workflow", "work_states")),
        repository_states=_required_list(lists, ("workflow", "repository_states")),
        priorities=_required_list(lists, ("workflow", "priorities")),
        risks=_required_list(lists, ("workflow", "risks")),
        types=_required_list(lists, ("workflow", "types")),
        audit_depths=_required_list(lists, ("repository_control", "audit_provenance", "audit_depths")),
        audit_freshness_values=_required_list(
            lists,
            ("repository_control", "audit_provenance", "derived_freshness", "values"),
        ),
        excluded_repositories=_required_list(lists, ("repository_control", "excluded_repositories")),
        control_wait_state=_required_scalar(
            scalars,
            ("repository_control", "control_only_wait_source_state", "value"),
        ),
        control_wait_project_status=_required_scalar(
            scalars,
            ("repository_control", "control_only_wait_source_state", "project_status_projection"),
        ),
    )


WORKFLOW_CONTRACT = load_workflow_contract()
