"""Bounded, evidence-backed appearance alternatives with task-local selection."""

import copy
import datetime as dt
import json
import secrets

POLICY = "minor_appearance_variants_v1"
MAX_CARDS = 3
MAX_PATCHES = 4
ALLOWED_ATTRIBUTES = {"hair", "eyes", "accessory", "default_outfit"}


def extraction_instructions():
    return (
        "For small source-backed appearance disagreements, keep the preferred source as the main facts and return "
        "appearance_alternatives:[{label,difference_type,patches:[{fact_id,value_en,source_id,quote}]}]. Return at"
        " most TWO alternatives; each has at most FOUR replacement patches for existing fact IDs. difference_type "
        "is color or ornament_detail. Each alternative is a coherent complete appearance after applying its "
        "patches, not a mix of contradictory claims. Colors and small ornament details may vary when quoted "
        "evidence supports both choices for this same character. When two applicable sources support different "
        "small color or ornament details, retain the alternative instead of discarding that supported choice. Do "
        "not create variants from imagination, from another character, age, species, body proportions, major "
        "silhouette, or an explicitly excluded outfit/version. Do not change fact attributes, critical flags or "
        "visible parts. Keep all shared identifying details. An alternative is a separate choice, not an active "
        "conflict or a critical missing field in the main card. If no applicable evidence supports a minor "
        "alternative, omit appearance_alternatives. "
    )


def review_instructions():
    return (
        "When fact_card.appearance_variant is present, review ONLY that selected complete variant. Its base_facts "
        "are comparison context, not additional active facts. Compare each patched fact with its base: only the "
        "declared small color or ornament difference is permitted; reject changes of character, age, species, "
        "body, major silhouette, excluded costume/version or loss of other identifying details. An independently "
        "quoted alternative color is allowed even if the preferred-source main card chooses another color. Do not "
        "restore the main card's choice, fuse alternatives, or switch variants during repair or scene writing. All"
        " active facts still require verbatim attributable evidence and full semantic checks. "
    )


def make_pool(card, alternatives):
    from anima_pipeline.prompting import anima_prompt_pipeline as chain

    errors = []
    if not isinstance(alternatives, list):
        return ([card], ["appearance_alternatives must be an array"])
    if len(alternatives) > MAX_CARDS - 1:
        errors.append("alternative count exceeds limit; excess alternatives ignored")
    options = [copy.deepcopy(card)]
    signatures = {chain.sha(card["facts"])}
    for alternative in alternatives[: MAX_CARDS - 1]:
        try:
            if (
                not isinstance(alternative, dict)
                or set(alternative) != {"label", "difference_type", "patches"}
                or (not isinstance(alternative["label"], str))
                or (not alternative["label"].strip())
                or (len(alternative["label"]) > 200)
                or (alternative["difference_type"] not in {"color", "ornament_detail"})
            ):
                raise ValueError("invalid minor appearance alternative")
            patches = alternative["patches"]
            if not isinstance(patches, list) or not 1 <= len(patches) <= MAX_PATCHES:
                raise ValueError("minor appearance patch limit exceeded")
            facts = copy.deepcopy(card["facts"])
            known = {fact["id"]: fact for fact in facts}
            seen, before = (set(), [])
            for patch in patches:
                if (
                    not isinstance(patch, dict)
                    or set(patch) != {"fact_id", "value_en", "source_id", "quote"}
                    or any(
                        (
                            not isinstance(value, str) or not value.strip()
                            for value in patch.values()
                        )
                    )
                ):
                    raise ValueError("invalid appearance patch contract")
                fact_id = patch["fact_id"]
                if (
                    fact_id in seen
                    or fact_id not in known
                    or known[fact_id]["attribute"] not in ALLOWED_ATTRIBUTES
                ):
                    raise ValueError(
                        "appearance patch changes an unknown, duplicate or protected attribute"
                    )
                seen.add(fact_id)
                before.append(copy.deepcopy(known[fact_id]))
                known[fact_id].update(
                    {field: patch[field] for field in ("value_en", "source_id", "quote")}
                )
            candidate = chain.validate_card(
                {"facts": facts, "conflicts": [], "body_type": card["body_type"]},
                card["sources"],
                card["character_key"],
                card["appearance_version"],
                card["material_cutoff"],
            )
            if candidate["rejected_facts"] or len(candidate["facts"]) != len(card["facts"]):
                raise ValueError("appearance alternative lacks valid quoted evidence")
            signature = chain.sha(candidate["facts"])
            if signature in signatures:
                raise ValueError("appearance alternative is duplicate or unchanged")
            signatures.add(signature)
            candidate["created_utc"] = card["created_utc"]
            for field in ("appearance_detail_research", "research_gaps", "excluded_evidence"):
                if field in card:
                    candidate[field] = copy.deepcopy(card[field])
            candidate["appearance_variant"] = {
                "label": alternative["label"],
                "difference_type": alternative["difference_type"],
                "base_facts": before,
            }
            options.append(candidate)
        except (ValueError, chain.NeedsReview) as error:
            errors.append(str(error))
    if len(options) > 1:
        pool_id = chain.sha([card["character_key"], [option["facts"] for option in options]])
        for option in options:
            metadata = option.setdefault(
                "appearance_variant",
                {"label": "preferred source", "difference_type": "primary", "base_facts": []},
            )
            metadata.update(
                policy=POLICY, pool_id=pool_id, variant_id=chain.sha(option["facts"])[:16]
            )
    return (options, errors)


def choose(options):
    return copy.deepcopy(secrets.choice(options))
