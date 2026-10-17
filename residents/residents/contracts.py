"""JSON-schema validation against contracts/*.schema.json (the team's shared interface)."""

from __future__ import annotations

import json
from functools import lru_cache

import jsonschema
from referencing import Registry, Resource

from .config import CONTRACTS


@lru_cache(maxsize=1)
def _registry() -> Registry:
    reg = Registry()
    for p in CONTRACTS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        reg = reg.with_resource(s["$id"], Resource.from_contents(s))
    return reg


@lru_cache(maxsize=None)
def validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema, registry=_registry())


def errors(name: str, obj: object) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:200]}" for e in validator(name).iter_errors(obj)]


def validate_report(r: dict) -> list[str]:
    return errors("report", r)


def def_errors(name: str, definition: str, obj: object) -> list[str]:
    """Validate against one $defs entry, e.g. def_errors("state", "plan_metrics", metrics)."""
    v = jsonschema.Draft202012Validator({"$ref": f"ember/{name}.schema.json#/$defs/{definition}"}, registry=_registry())
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:200]}" for e in v.iter_errors(obj)]
