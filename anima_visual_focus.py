"""Unify visual priorities after environment design without changing scene intent."""

import copy
import json
import anima_prompt_contracts as contracts

EDITABLE_FIELDS = ("pose", "expression", "composition")


def instructions():
    return (
        "Edit the COMPLETE illustration after its environment design so action, expression and camera work "
        "together with the finished outfit and setting. This is final visual synthesis, not a new scene, a score "
        "or a request for more details. Return JSON {candidates:[{candidate_index:integer,fields:{...}}]}. Return "
        "every supplied candidate once in order, with exactly that candidate's editable_fields, all English. "
        "Preserve each candidate's actual moment, silhouette, posture, torso/head orientation, camera/crop, "
        "essential hand-object contact, garment design and setting. outfit, scene and lighting belong to earlier "
        "stages: they are context here, not editable text. garment_plan, creative_brief and composition_plan, when"
        " supplied, are design intent to keep, not text to copy. The main gesture is mandatory even if previously "
        "phrased softly. Do not solve competing instructions by dropping a raised arm, held object or head turn, "
        "or by replacing an expressive pose with ordinary standing. Use the pose field for an unmistakable action "
        "silhouette and contact: arm elevation/bend, what the hand touches or holds, and where the object is. A "
        "few literal action tags may accompany one relational sentence when useful. Keep viewpoint and crop "
        "anchors in composition rather than copying them into pose. Do not add tag weights or repeat the same "
        "gesture in every field. Keep necessary support in scene_state. Give each editable field one job: pose "
        "describes the action; expression states the face; composition states the camera, crop and subject "
        "placement without a shopping list of garment details or a second scene description. Do not repeat "
        "identity colors or body facts already owned by the compiler. Do not demand that the figure display every "
        "seam, ring and panel to the camera. The expression field must begin with one to three familiar Danbooru "
        "expression tags matching the intended mood, before a short relational phrase; a smiling mood begins with "
        "a smile tag, not only a phrase such as closed-mouth smile. Keep the expression already chosen unless it "
        "contradicts the face or clashes with the action. Choose the expression and the action together as one "
        "moment: the face must suit what her body is doing and the mood of the place. A quiet, low or resting "
        "posture (kneeling, squatting, sitting, lying) takes a calm or gentle face, not a taunting, smug or showy "
        "one; a teasing face belongs to a posture that itself shows attitude. Do not use the tag raised eyebrow, "
        "which renders as a lopsided, distorted face. Do not restate an eye trait the identity facts already "
        "supply. Keep composition focused on the existing camera, crop and subject placement, compatible with "
        "composition_plan.background_in_frame when supplied. Remove incidental sky, weather and scenery wording "
        "from composition because scene already owns it. A request for the head or hand to read against open sky "
        "means a local uncluttered gap; it must not erase planned clouds or the horizon elsewhere. Explicit "
        "weather constraints and fixed reference fields still take precedence. There is no universal word count: "
        "keep enough relational detail for the primary action and omit competing repetition. No artist tags, "
        "quality prefixes, new identity facts, private reasoning or commentary. Identity selection, negatives, "
        "scene_state, candidate count, support/contact relationships, outfit, scene and lighting are immutable. A "
        "genuinely conflicting starting instruction remains for review; do not disguise a pose change as a wording"
        " improvement.\n"
    )


def refine(session, draft, *, theme, channel, brief_text=""):
    from anima_prompt_pipeline import (
        DESIGN_FIELDS,
        NeedsReview,
        action_camera_instructions,
        english_issues,
        theme_brief,
    )

    brief = session._brief(theme) if hasattr(session, "_brief") else theme_brief(session.cfg, theme)
    fixed = set(draft.get("visual_design_reference", {}).get("fields", {}))
    editable = set(EDITABLE_FIELDS) - fixed
    if not editable:
        return draft
    original = contracts.effective_candidates(draft, channel)
    candidates = [
        {
            "candidate_index": index,
            "editable_fields": sorted(editable),
            **{
                field: copy.deepcopy(candidate.get(field))
                for field in contracts.PATCH_FIELDS
                if field != "pose_variants"
            },
        }
        for index, candidate in enumerate(original)
    ]
    context = {"theme": brief, "candidates": candidates}
    if brief_text:
        context["creative_brief"] = brief_text
    plan = session.composition_plans().get(channel)
    if plan:
        context["composition_plan"] = plan
    garment = session.audit.get("art_direction", {}).get(channel, {}).get("outfit_plan")
    if garment:
        context["garment_plan"] = copy.deepcopy(garment)
    response = session.request(
        "final_visual_focus:" + channel,
        instructions()
        + action_camera_instructions()
        + "\n"
        + json.dumps(context, ensure_ascii=False),
    )
    if (
        not isinstance(response, dict)
        or set(response) != {"candidates"}
        or (not isinstance(response["candidates"], list))
    ):
        raise NeedsReview("visual focus must return a candidate array")
    updates = response["candidates"]
    from anima_prompt_pipeline import unwrap_editable_fields

    unwrap_editable_fields(updates)
    if len(updates) != len(original):
        raise NeedsReview("visual focus changed the number of candidates")
    result = copy.deepcopy(draft)
    limit = getattr(session.cfg, "ANIMA_PROMPT_MAX_CHARS", 16000)
    for index, update in enumerate(updates):
        if (
            not isinstance(update, dict)
            or set(update) != {"candidate_index", "fields"}
            or type(update["candidate_index"]) is not int
            or (update["candidate_index"] != index)
            or (not isinstance(update["fields"], dict))
            or (not editable.issubset(update["fields"]))
            or (not set(update["fields"]).issubset(DESIGN_FIELDS))
        ):
            raise NeedsReview("visual focus changed immutable fields or candidate indexing")
        echoed = set(update["fields"]) - editable
        if any((update["fields"][field] != original[index].get(field) for field in echoed)):
            raise NeedsReview("visual focus modified a fixed rendering field")
        for field, value in update["fields"].items():
            if (
                english_issues(value, field)
                or "@" in value
                or len(value) > limit
                or (field != "expression" and (not value.strip()))
            ):
                raise NeedsReview("invalid visual focus field: " + field)
        target = result if index == 0 else result["pose_variants"][index - 1]
        target.update(
            {
                field: copy.deepcopy(value)
                for field, value in update["fields"].items()
                if field in editable
            }
        )
    session.audit.setdefault("visual_focus", {})[channel] = {
        "before": candidates,
        "updates": copy.deepcopy(updates),
        "editable_fields": sorted(editable),
    }
    return result


def intents(audit):
    return {
        channel: [
            {
                "candidate_index": candidate["candidate_index"],
                **{
                    field: candidate[field]
                    for field in ("pose", "composition", "outfit", "scene_state")
                },
            }
            for candidate in record["before"]
        ]
        for channel, record in audit.get("visual_focus", {}).items()
    }


def review_instructions():
    return (
        "pre_focus_intents contains the actual candidate pose, camera, garment and physical state before final "
        "synthesis. For each matching candidate check that its final fields still express the same essential "
        "gesture/contact, body/head orientation, garment identity and crop. Flag an omitted main gesture or actual"
        " redesign, not a harmless wording simplification or a missing minor ornament. For an omission quote the "
        "current pose or composition exactly and name the dropped relation from pre_focus_intents; never quote old"
        " text as if it appeared in the new field. Preserve these primary action relations when repairing other "
        "fields. Judge actual text consistency, not whether the diffusion model will obey it or whether the "
        "picture looks premium. "
    )
