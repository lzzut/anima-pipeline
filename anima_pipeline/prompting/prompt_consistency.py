"""Conservative consistency for eye colors inside one structured draft.

The existing ``eye_colors`` value is a rendering source, not a verified fact.
This module neither chooses a character's true color nor queries a source.
Only plain, unambiguous eye-color clauses in five appearance fields can change.
"""

import copy
import re
from anima_pipeline.prompting.framing_content import split_prompt_tags

_FIELDS = ("face_priority", "core_features", "appearance", "hybrid_features", "grounded_appearance")
_COLORS = (
    "red",
    "blue",
    "green",
    "purple",
    "violet",
    "aqua",
    "teal",
    "yellow",
    "orange",
    "pink",
    "magenta",
    "gold",
    "golden",
    "amber",
    "grey",
    "gray",
    "brown",
    "black",
    "white",
    "silver",
    "cyan",
    "turquoise",
    "hazel",
    "indigo",
)
_COLOR_WORD = "(?:" + "|".join(_COLORS) + ")"
_COLOR = re.compile("(?i)\\b" + _COLOR_WORD + "\\b")
_MODIFIER_WORD = "(?:light|dark|pale|deep|bright)"
_CANONICAL = re.compile(
    "(?i)^(?:(?P<shade>" + _MODIFIER_WORD + ")\\s+)?(?P<color>" + _COLOR_WORD + ")\\s+eyes$"
)
_COLOR_SPAN = re.compile("(?i)\\b(?:" + _MODIFIER_WORD + "\\s+)?" + _COLOR_WORD + "\\b")
_EYE_NOUN = re.compile(
    "(?i)\\b(?:eyes?|irises?|pupils?)\\b(?!\\s+(?:makeup|make-up|shadow|liner|contour|decoration|motif)\\b)"
)
_EYES_END = re.compile("(?i)\\s+eyes$")
_OPAQUE = re.compile("[@_()\\[\\]{}\\\\:|]")
_SPECIAL_EYE = re.compile(
    (
        "(?i)\\b(?:heterochrom\\w*|multi[- ]?colou?red|two[- ](?:toned?|colou?red)|dual[- ](?:toned?|colou?red)|bi[-"
        " ]?colou?red|differently[- ]colou?red|gradient|rainbow)\\b"
    )
)
_SIDE_OR_SINGLE = re.compile("(?i)\\b(?:left|right|one|other|each|single)\\b")
_DESCRIPTORS = {
    "sharp",
    "narrow",
    "almond",
    "almond-shaped",
    "half-lidded",
    "half",
    "lidded",
    "hooded",
    "slanted",
    "upturned",
    "downturned",
    "round",
    "large",
    "small",
    "wide",
    "droopy",
    "sleepy",
    "tired",
    "catlike",
    "cat-like",
    "foxlike",
    "fox-like",
    "glowing",
    "sparkling",
    "detailed",
    "pupilless",
    "slit-pupil",
}


def _normal(value):
    return re.sub("\\s+", " ", value.strip()).lower()


def _special_reason(clause):
    """Explicit special-eye evidence blocks a global single-color rewrite."""
    if re.search("(?i)\\bheterochrom\\w*\\b", clause):
        return "explicit_heterochromia"
    if not _EYE_NOUN.search(clause):
        return None
    if _SPECIAL_EYE.search(clause):
        return "explicit_multicolor_or_gradient"
    if _SIDE_OR_SINGLE.search(clause):
        return "sided_or_single_eye"
    if len({match.group(0).lower() for match in _COLOR.finditer(clause)}) > 1:
        return "multiple_colors_in_one_eye_clause"
    if re.search(
        "(?i)\\b"
        + _COLOR_WORD
        + "\\s+eye\\b(?!\\s+(?:makeup|make-up|shadow|liner|contour|decoration|motif)\\b)",
        clause,
    ):
        return "singular_eye_ambiguous"
    return None


def _candidate(clause):
    """Return a color span only for a short plain eye-description grammar."""
    if _OPAQUE.search(clause):
        return (None, "opaque_group_identity_or_artist")
    end = _EYES_END.search(clause)
    if not end:
        return (None, "unsupported_eye_clause")
    prefix = clause[: end.start()].strip()
    matches = list(_COLOR_SPAN.finditer(prefix))
    if len(matches) != 1:
        return (None, "unsupported_color_grammar")
    match = matches[0]
    remaining = (prefix[: match.start()] + " " + prefix[match.end() :]).strip()
    words = _normal(remaining).split() if remaining else []
    if any((word not in _DESCRIPTORS for word in words)):
        return (None, "opaque_composite_eye_clause")
    return (match, None)


def reconcile_eye_colors(structured):
    """Return ``(deepcopy rendering view, audit)`` without changing the source.

    A unique simple ``<color> eyes`` field is required. An explicit sided,
    single-eye, heterochromia or multicolor statement anywhere in the relevant
    fields prevents a single-color rewrite for the whole draft. Weighted groups
    and composite prose stay intact and are audited. No other fields change.
    """
    view = copy.deepcopy(structured)
    audit = {
        "scope": "draft_internal_eye_color_consistency",
        "fact_verified": False,
        "status": "unchanged",
        "canonical": "",
        "changes": [],
        "unresolved": [],
    }
    if not isinstance(structured, dict):
        audit["status"] = "unsupported_structured_type"
        return (view, audit)
    eye = structured.get("eye_colors")
    if not isinstance(eye, str) or not eye.strip():
        audit["status"] = "missing_or_nonstring_eye_colors"
        return (view, audit)
    audit["canonical"] = eye
    canonical = _CANONICAL.fullmatch(_normal(eye))
    if canonical is None:
        audit["status"] = "ambiguous_or_unsupported_eye_colors"
        return (view, audit)
    for field in _FIELDS:
        value = structured.get(field)
        if not isinstance(value, str):
            continue
        for clause in split_prompt_tags(value):
            reason = _special_reason(clause)
            if reason:
                audit["unresolved"].append({"field": field, "value": clause, "reason": reason})
    if audit["unresolved"]:
        audit["status"] = "preserved_special_eye_evidence"
        return (view, audit)
    selected_color = canonical["color"].lower()
    selected_shade = (canonical["shade"] or "").lower()
    for field in _FIELDS:
        value = structured.get(field)
        if not isinstance(value, str):
            if value is not None:
                audit["unresolved"].append(
                    {
                        "field": field,
                        "reason": "nonstring_field_preserved",
                        "value_type": type(value).__name__,
                    }
                )
            continue
        parts, field_changed = ([], False)
        for clause in split_prompt_tags(value):
            if not (_EYE_NOUN.search(clause) and _COLOR.search(clause)):
                parts.append(clause)
                continue
            match, reason = _candidate(clause)
            if reason:
                parts.append(clause)
                audit["unresolved"].append({"field": field, "value": clause, "reason": reason})
                continue
            color = _COLOR.search(match.group(0)).group(0).lower()
            if color == selected_color:
                parts.append(clause)
                shade = _normal(match.group(0)).split()
                if selected_shade and len(shade) > 1 and (shade[0] != selected_shade):
                    audit["unresolved"].append(
                        {
                            "field": field,
                            "value": clause,
                            "reason": "same_color_shade_difference_preserved",
                        }
                    )
                continue
            after = re.sub("\\s+", " ", clause[: match.start()] + clause[match.end() :]).strip()
            if after.lower() == "eyes":
                after = ""
            if after:
                parts.append(after)
            field_changed = True
            audit["changes"].append(
                {
                    "field": field,
                    "before": clause,
                    "after": after,
                    "removed_color_phrase": match.group(0),
                    "reason": "removed_internal_color_conflict",
                }
            )
        if field_changed:
            view[field] = ", ".join(parts)
    if audit["changes"]:
        audit["status"] = "reconciled_internal_conflicts"
    elif audit["unresolved"]:
        audit["status"] = "preserved_ambiguous_eye_clauses"
    return (view, audit)
