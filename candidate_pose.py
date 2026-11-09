"""Production-only candidate composition reconciliation."""

import re
from framing_content import _split_top

_HEAD_POSTURE_PATTERNS = {
    "tilt": re.compile(
        (
            "(?i)(?:(?:slight\\s+)?head\\s+(?:slightly\\s+)?tilt(?:ed)?(?:\\s+(?:slightly|(?:slightly\\s+)?(?:left|right|to"
            " one side|to the side)))?|tilted\\s+head)"
        )
    ),
    "level": re.compile(
        "(?i)(?:head\\s+(?:upright|straight|level)|(?:upright|straight|level)\\s+head)"
    ),
}


def _posture(value):
    matches = [
        name
        for name, pattern in _HEAD_POSTURE_PATTERNS.items()
        if pattern.fullmatch(str(value or "").strip())
    ]
    return matches[0] if len(matches) == 1 else None


def reconcile_candidate_composition(composition, pose, *, preserve=False):
    """Remove one explicit, opposite plain head-pose label for later candidates.

    The first stable candidate remains unchanged. Only close-up, portrait and
    upper-body callers use this helper; full-body composition is kept intact.
    Weighted groups, camera labels, opaque clauses and ambiguous prose remain.
    """
    original = str(composition or "")
    if preserve or not original:
        return (original, [])
    pose_parts, pose_balanced = _split_top(str(pose or ""))
    composition_parts, composition_balanced = _split_top(original)
    if not pose_balanced or not composition_balanced:
        return (original, [])
    pose_kinds = {_posture(part) for part in pose_parts} - {None}
    if len(pose_kinds) != 1:
        return (original, [])
    pose_kind = pose_kinds.pop()
    opposite = "level" if pose_kind == "tilt" else "tilt"
    kept, removed = ([], [])
    for part in composition_parts:
        if _posture(part) == opposite:
            removed.append(part)
        else:
            kept.append(part)
    return (", ".join(kept) if removed else original, removed)
