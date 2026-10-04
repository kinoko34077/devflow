from __future__ import annotations

import json
from typing import Any


class MarkerJSONError(ValueError):
    pass


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
    *,
    label: str,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MarkerJSONError(f"{label} contains duplicate JSON key: {key}")
        result[key] = value
    return result


def marker_bounds(
    body: str,
    begin_marker: str,
    end_marker: str,
    *,
    label: str,
) -> tuple[int, int] | None:
    text = str(body or "")
    begin_count = text.count(begin_marker)
    end_count = text.count(end_marker)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise MarkerJSONError(f"{label} must contain exactly one marker pair")
    begin = text.find(begin_marker)
    end = text.find(end_marker)
    if end < begin + len(begin_marker):
        raise MarkerJSONError(f"{label} markers are malformed")
    return begin, end


def parse_json_object_block(
    body: str,
    begin_marker: str,
    end_marker: str,
    *,
    label: str,
) -> dict[str, Any] | None:
    bounds = marker_bounds(body, begin_marker, end_marker, label=label)
    if bounds is None:
        return None
    begin, end = bounds
    raw = str(body or "")[begin + len(begin_marker) : end].strip()
    if not raw:
        raise MarkerJSONError(f"{label} JSON is empty")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=lambda pairs: _reject_duplicate_json_keys(
                pairs,
                label=label,
            ),
        )
    except json.JSONDecodeError as exc:
        raise MarkerJSONError(f"{label} JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise MarkerJSONError(f"{label} must be an object")
    return payload
