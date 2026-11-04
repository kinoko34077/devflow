from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def generation_material(payload: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    value.pop("generation_id", None)
    return value


def recompute_generation_id(payload: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(payload)
    value["generation_id"] = canonical_digest(generation_material(value))
    return value

