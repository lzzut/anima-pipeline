"""Deterministic checks for evidence, visible identity and candidate dependencies."""

from __future__ import annotations
import copy
import json
import re
import unicodedata
import anima_fact_semantics as fact_semantics

SCENE_VIEWS = {"front", "three_quarter", "side", "rear"}
LOOKING_BACK = re.compile(
    (
        "(?i)\\b(?:looking back|looks back|glanc\\w* back|over (?:her|his|one)(?: (?:left|right))? shoulder|turn\\w* "
        "(?:her|his) head back|head (?:is )?turn\\w* back)\\b"
    )
)
POSTURES = {"standing", "seated", "kneeling", "lying", "other"}
VISIBLE_PARTS = {
    "hair",
    "eyes",
    "face",
    "accessory",
    "body",
    "outfit",
    "head",
    "torso",
    "arms",
    "legs",
    "hands",
    "feet",
}
RENDER_FIELDS = ("outfit", "expression", "pose", "scene", "lighting", "composition", "negative")
PATCH_FIELDS = RENDER_FIELDS + ("identity_fact_ids", "scene_state", "pose_variants")


class ReviewAttributionError(ValueError):
    pass


def normalized(value):
    if isinstance(value, str):
        value = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(re.findall("\\w+", value))
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    return value


def effective_candidates(draft, channel):
    primary = {key: copy.deepcopy(value) for key, value in draft.items() if key != "pose_variants"}
    result = [primary]
    if channel == "stable" and isinstance(draft.get("pose_variants"), list):
        for variant in draft["pose_variants"]:
            if isinstance(variant, dict):
                result.append(dict(copy.deepcopy(primary), **copy.deepcopy(variant)))
    return result


def scene_issues(candidate, facts, excluded_identity_ids=()):
    state = candidate.get("scene_state")
    if not isinstance(state, dict):
        return ["scene_state: required object"]
    issues = []
    if state.get("view") not in SCENE_VIEWS:
        issues.append("scene_state: invalid view")
    if state.get("posture") not in POSTURES:
        issues.append("scene_state: invalid posture")
    if not isinstance(state.get("support"), str) or not state["support"].strip():
        issues.append("scene_state: support description required")
    visible = state.get("visible_parts")
    valid_visibility = isinstance(visible, list) and all(
        (isinstance(part, str) and part in VISIBLE_PARTS for part in visible)
    )
    if not valid_visibility:
        issues.append("scene_state: invalid visible_parts")
        visible = []
    occlusions = state.get("occlusions", {})
    known = {fact["id"]: fact for fact in facts}
    if not isinstance(occlusions, dict) or any(
        (
            fid not in known or not isinstance(reason, str) or (not reason.strip())
            for fid, reason in occlusions.items()
        )
    ):
        issues.append("scene_state: occlusions need known fact IDs and reasons")
        occlusions = {}
    contacts = state.get("contacts")
    if not isinstance(contacts, list) or any(
        (
            not isinstance(contact, dict)
            or any(
                (
                    not isinstance(contact.get(key), str) or not contact[key].strip()
                    for key in ("part", "object")
                )
            )
            for contact in contacts
        )
    ):
        issues.append("scene_state: contacts must identify body part and contact object")
    ids = candidate.get("identity_fact_ids", [])
    if valid_visibility and isinstance(ids, list) and all((isinstance(fid, str) for fid in ids)):
        implicit_hidden = {"eyes", "face"} if state.get("view") == "rear" else set()
        required = {
            fact["id"]
            for fact in facts
            if fact["attribute"] not in {"body", "default_outfit"}
            and fact["id"] not in excluded_identity_ids
            and fact.get("identity_critical", True)
            and (fact["id"] not in occlusions)
            and (fact.get("visible_part", fact["attribute"]) not in implicit_hidden)
        }
        if required - set(ids):
            issues.append(
                "identity_fact_ids: missing visible critical facts "
                + ", ".join(sorted(required - set(ids)))
            )
        hidden = [
            fid
            for fid in ids
            if fid in known
            and known[fid]["attribute"] not in {"body", "default_outfit"}
            and (
                fid in occlusions
                or known[fid].get("visible_part", known[fid]["attribute"]) not in visible
            )
        ]
        if hidden:
            issues.append("identity_fact_ids: selected hidden facts " + ", ".join(hidden))
    scene = str(candidate.get("scene", "")).lower()
    pose = str(candidate.get("pose", "")).lower()
    if state.get("posture") == "standing" and re.search(
        "\\b(?:her seated body|supports her seated|she (?:is seated|sits))\\b", scene
    ):
        issues.append("scene: seated support contradicts standing state")
    if state.get("posture") == "seated" and re.search("\\bshe (?:stands|is standing)\\b", pose):
        issues.append("pose: standing contradicts seated state")
    if state.get("posture") == "standing" and re.search("\\bshe (?:sits|is seated)\\b", pose):
        issues.append("pose: seated contradicts standing state")
    composition = str(candidate.get("composition", "")).lower()
    if state.get("view") in {"front", "three_quarter"} and re.search(
        "\\b(?:rear view hides her face|back facing (?:the )?viewer)\\b", pose + " " + composition
    ):
        issues.append("scene_state: rear-facing prose contradicts the declared view")
    looking_back = bool(LOOKING_BACK.search(pose + " " + composition))
    if (
        state.get("view") == "rear"
        and looking_back
        and ("from behind" not in pose + " " + composition)
    ):
        issues.append(
            "composition: a looking-back rear view needs the tag from behind at the start of composition"
        )
    if (
        state.get("view") == "rear"
        and ("eyes" in visible or "face" in visible)
        and (not looking_back)
    ):
        issues.append(
            (
                "scene_state: rear view cannot show the front of the face unless pose says looking back over her shoulder;"
                " for a looking-back pose keep view rear and write that phrase in pose, otherwise remove face and eyes "
                "from visible_parts"
            )
        )
    return issues


def dependency_issues(draft):
    issues = []
    base = draft.get("scene_state")
    for index, variant in enumerate(
        draft.get("pose_variants", []) if isinstance(draft.get("pose_variants"), list) else []
    ):
        if not isinstance(variant, dict):
            continue
        unknown = set(variant) - set(PATCH_FIELDS)
        if unknown or "pose_variants" in variant:
            issues.append(f"pose_variants[{index}]: unsupported candidate fields")
        if "scene_state" in variant and variant["scene_state"] != base:
            missing = set(RENDER_FIELDS + ("identity_fact_ids",)) - set(variant)
            if missing:
                issues.append(
                    f"pose_variants[{index}]: state change requires complete dependent fields: "
                    + ", ".join(sorted(missing))
                )
    return issues


def semantic_risks(drafts):
    reasons = set()
    for channel, draft in drafts.items():
        if not isinstance(draft, dict):
            continue
        for candidate in effective_candidates(draft, channel):
            state = candidate.get("scene_state") or {}
            if state != draft.get("scene_state"):
                reasons.add("candidate changes scene state")
            if isinstance(state, dict) and state.get("occlusions"):
                reasons.add("identity occlusion requires semantic check")
            if isinstance(state, dict) and state.get("contacts"):
                reasons.add("body/object contact")
            prose = " ".join(
                (str(candidate.get(field, "")) for field in RENDER_FIELDS if field != "negative")
            )
            if re.search("\\b(?:hair|eyes?|irises|clasp|birthmark|tattoo)\\b", prose, re.I):
                reasons.add("creative prose mentions identity traits")
            if re.search(
                "\\b(?:rear view|back (?:is turned|to the viewer|facing)|seated|sits|kneels|lying|holding|grips|leans|reaches)\\b",
                prose,
                re.I,
            ):
                reasons.add("prose describes viewpoint/support/contact changes")
    return sorted(reasons)


def local_issues(draft, messages, channel):
    issues = []
    for message in messages:
        field = message.split(":", 1)[0].split("[", 1)[0]
        if field not in PATCH_FIELDS:
            return None
        issues.append(
            {
                "channel": channel,
                "field": field,
                "quote": "",
                "reason": message,
                "fact_ids": [],
                "origin": "local",
                "requires_change": "selected original-costume component also appears in prose"
                in message,
            }
        )
        target = re.match("pose_variants\\[(\\d+)\\](?::\\s*|\\.)([a-z_]+):", message)
        if target and target.group(2) in PATCH_FIELDS:
            issues[-1].update(
                candidate_index=int(target.group(1)) + 1, candidate_field=target.group(2)
            )
    return issues


def quote_matches(value, quote):
    if isinstance(value, str):
        return quote in value
    if quote in json.dumps(value, ensure_ascii=False):
        return True
    if isinstance(value, dict):
        return any((quote_matches(item, quote) for item in value.values()))
    if isinstance(value, list):
        return any((quote_matches(item, quote) for item in value))
    return False


def review_target(issue, draft, channel, omission):
    field, quote = (issue["field"], issue.get("quote"))
    explicit_index = issue.get("candidate_index")
    candidates = effective_candidates(draft, channel)
    if explicit_index is not None:
        if type(explicit_index) is not int or not 0 <= explicit_index < len(candidates):
            raise ReviewAttributionError("semantic review referenced invalid candidate index")
        if field == "pose_variants":
            if explicit_index != 0:
                raise ReviewAttributionError(
                    "pose_variants container requires primary candidate index"
                )
        else:
            target = candidates[explicit_index].get(field)
            if not omission and (not quote_matches(target, quote)):
                raise ReviewAttributionError("semantic review lacks an attributable quote")
            storage_field = (
                "pose_variants"
                if explicit_index and field in draft["pose_variants"][explicit_index - 1]
                else field
            )
            return dict(
                issue, field=storage_field, candidate_field=field, candidate_index=explicit_index
            )
    if omission or quote_matches(draft.get(field), quote):
        return dict(issue)
    matches = (
        [
            index
            for index, variant in enumerate(draft.get("pose_variants", []), 1)
            if field != "pose_variants"
            and field in variant
            and quote_matches(variant[field], quote)
        ]
        if channel == "stable"
        else []
    )
    if len(matches) != 1:
        raise ReviewAttributionError("semantic review lacks an attributable quote")
    return dict(issue, field="pose_variants", candidate_field=field, candidate_index=matches[0])


def validate_review(review, drafts, card, require_fact_checks=False):
    if not isinstance(review, dict) or not isinstance(review.get("issues"), list):
        raise ValueError("semantic review returned invalid contract")
    known = {fact["id"]: fact for fact in card["facts"]}
    checked = {}
    if require_fact_checks or review.get("fact_checks"):
        checks = review.get("fact_checks")
        if not isinstance(checks, list):
            raise ValueError("new fact card requires explicit per-fact support checks")
        for item in checks:
            if not isinstance(item, dict) or not isinstance(item.get("fact_id"), str):
                raise ValueError("invalid fact support check")
            fid = item["fact_id"]
            if (
                fid not in known
                or fid in checked
                or item.get("status") not in {"supported", "unsupported", "unknown"}
                or (not item.get("reason"))
            ):
                raise ValueError("invalid or duplicate fact support verdict")
            checked[fid] = fact_semantics.validate_check(item, known[fid])
        if require_fact_checks and set(checked) != set(known):
            raise ValueError("fact support review omitted facts")
    accepted = []
    for issue in review["issues"]:
        if not isinstance(issue, dict):
            raise ValueError("invalid review issue")
        if issue.get("scope") == "fact_card":
            if (
                not issue.get("reason")
                or not issue.get("fact_ids")
                or any((fid not in known for fid in issue["fact_ids"]))
            ):
                raise ValueError("invalid fact-card issue")
            for fid in issue["fact_ids"]:
                checked[fid] = {"fact_id": fid, "status": "unsupported", "reason": issue["reason"]}
            continue
        channel, field = (issue.get("channel"), issue.get("field"))
        if not issue.get("reason"):
            raise ValueError("semantic review issue requires a reason")
        if channel not in drafts or field not in PATCH_FIELDS:
            raise ReviewAttributionError("semantic review referenced invalid field/channel")
        ids = issue.get("fact_ids", [])
        if not isinstance(ids, list) or any(
            (not isinstance(fid, str) or fid not in known for fid in ids)
        ):
            raise ValueError("semantic review referenced unknown fact")
        omission = field == "identity_fact_ids" and ids and (not issue.get("quote"))
        if not omission and (not isinstance(issue.get("quote"), str) or not issue["quote"]):
            raise ReviewAttributionError("semantic review lacks an attributable quote")
        targeted = review_target(issue, drafts[channel], channel, omission)
        if omission:
            ids = [fid for fid in ids if known[fid]["attribute"] != "body"]
            if not ids:
                continue
            targeted["fact_ids"] = ids
        accepted.append(dict(targeted, origin="semantic"))
    return (accepted, checked)


def attribution_failures(review, drafts, card, require_fact_checks=False):
    validate_review(dict(review, issues=[]), drafts, card, require_fact_checks)
    failures = []
    for issue_index, issue in enumerate(review["issues"]):
        try:
            validate_review(dict(review, issues=[issue]), drafts, card, require_fact_checks)
        except ReviewAttributionError as error:
            quote = issue.get("quote")
            channels = [issue["channel"]] if issue.get("channel") in drafts else list(drafts)
            locations = [
                {"channel": channel, "candidate_index": index}
                for channel in channels
                for index, candidate in enumerate(effective_candidates(drafts[channel], channel))
                if isinstance(quote, str)
                and quote
                and quote_matches(candidate.get(issue.get("field")), quote)
            ]
            failures.append(
                {
                    "issue_index": issue_index,
                    "error": str(error),
                    "exact_quote_candidate_indices": [
                        item["candidate_index"] for item in locations
                    ],
                    "exact_quote_locations": locations,
                }
            )
    return failures


def validate_attribution_correction(
    previous, corrected, failures, drafts, card, require_fact_checks=False
):
    accepted, checked = validate_review(corrected, drafts, card, require_fact_checks)
    if corrected.get("fact_checks", []) != previous.get("fact_checks", []):
        raise ValueError("attribution correction cannot change fact verdicts")
    if (
        "resolved_issue_ids" in previous
        and corrected.get("resolved_issue_ids") != previous["resolved_issue_ids"]
    ):
        raise ValueError("attribution correction cannot change repair verdicts")
    invalid = {failure["issue_index"] for failure in failures}
    remaining = list(range(len(corrected["issues"])))
    for index, issue in enumerate(previous["issues"]):
        if index not in invalid:
            match = next(
                (position for position in remaining if corrected["issues"][position] == issue), None
            )
            if match is None:
                raise ValueError("attribution correction dropped or changed an attributable issue")
            remaining.remove(match)
    changes = corrected.get("attribution_corrections")
    if not isinstance(changes, list) or len(changes) != len(invalid):
        raise ValueError("attribution correction needs one decision per invalid issue")
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("invalid attribution correction decision")
        index = change.get("issue_index")
        if (
            type(index) is not int
            or index not in invalid
            or index in seen
            or (not isinstance(change.get("reason"), str))
            or (not change["reason"].strip())
        ):
            raise ValueError("invalid attribution correction issue or explanation")
        seen.add(index)
        target = change.get("corrected_issue_index")
        if change.get("action") == "corrected":
            if type(target) is not int or target not in remaining:
                raise ValueError("attribution correction references an invalid replacement")
            remaining.remove(target)
        elif change.get("action") != "withdrawn" or target is not None:
            raise ValueError("invalid attribution correction action")
    if remaining:
        raise ValueError("attribution correction added unrelated issues")
    return (accepted, checked)
