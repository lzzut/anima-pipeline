"""Small deterministic diagnostics for existing clothing cleanup decisions.

This metadata is never prompt content. Carried records describe earlier inputs;
they do not authenticate those inputs or establish official character facts.
"""

from __future__ import annotations
import copy
import hashlib

AUDIT_KEY = "prompt_source_audit"
PRODUCER = "pipeline_character.dressup_cleanup"


def without_cleanup_audit(value):
    """Keep audit-only text out of selfchecks, including saved nested views."""
    if isinstance(value, dict):
        return {
            key: without_cleanup_audit(child) for key, child in value.items() if key != AUDIT_KEY
        }
    if isinstance(value, list):
        return [without_cleanup_audit(child) for child in value]
    return value


def field_record(field, before, after, removed, unresolved):
    if not removed and (not unresolved):
        return None
    digest = lambda text: hashlib.sha256(str(text).encode("utf-8")).hexdigest()
    return {
        "field": field,
        "before_sha256": digest(before),
        "after_sha256": digest(after),
        "removed": list(removed),
        "unresolved": copy.deepcopy(unresolved),
    }


def record_stage(structured, stage, theme, applied, fields):
    """Merge distinct observations without erasing earlier pre-budget removals."""
    audit = structured.get(AUDIT_KEY)
    if not (
        isinstance(audit, dict)
        and audit.get("schema_version") == 1
        and (audit.get("producer") == PRODUCER)
        and isinstance(audit.get("stages"), list)
        and all(
            (
                isinstance(item, dict) and isinstance(item.get("fields"), list)
                for item in audit["stages"]
            )
        )
    ):
        audit = {
            "schema_version": 1,
            "producer": PRODUCER,
            "scope": "diagnostics only; inherited records are historical claims, not authenticated facts",
            "stages": [],
        }
        structured[AUDIT_KEY] = audit
    match = next(
        (
            item
            for item in audit["stages"]
            if item.get("stage") == stage and item.get("theme") == str(theme or "")
        ),
        None,
    )
    if match is None:
        match = {"stage": stage, "theme": str(theme or ""), "applied": bool(applied), "fields": []}
        audit["stages"].append(match)
    for item in fields:
        if item is not None and item not in match["fields"]:
            match["fields"].append(copy.deepcopy(item))
