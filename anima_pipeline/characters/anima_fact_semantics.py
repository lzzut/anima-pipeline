"""Shared fact extraction/review policy. No character names or term replacement table.

Lexical comparison only selects facts needing an explicit semantic comparison;
it never decides that a paraphrase is wrong. Meaning is still checked by the LLM.
"""

import re
import unicodedata
from anima_pipeline.characters import anima_source_policy as source_policy
from anima_pipeline.characters import anima_character_variants as character_variants

REVIEW_POLICY = "source_meaning_v3_single_state"


def appearance_state_instructions():
    return (
        "SINGLE APPEARANCE STATE: active facts describe one drawable appearance, not a catalogue of appearances "
        "over time. A source may truthfully describe a usual hairstyle and occasionally worn alternatives, but "
        "those mutually exclusive whole-head arrangements must not all become active facts, even with words such "
        "as sometimes or occasionally. Use the requested state when specified; otherwise use the source's "
        "principal/usual state and source_precedence. At extraction omit unselected optional states while "
        "retaining all shared distinguishing details in the chosen state; their source passages remain evidence, "
        "not render requirements. Do not treat this as missing critical evidence. This is not a keyword ban: bangs"
        " with a braid, a braided ponytail, multicolored hair, and a color appearing darker under lighting may be "
        "compatible. Judge whether the quoted spatial and temporal relationships can coexist. Review the joint "
        "active state as well as each fact's truth: mark facts for unselected incompatible states unknown and "
        "explain which supported principal state resolves them. During repair, a fact describing an unselected "
        "optional state may be replaced by a precisely quoted fact about the chosen state of the SAME attribute, "
        "preserving IDs and all source-supported shared identity details. Do not invent a reconciliation, collapse"
        " to generic hair, remove a distinctive attachment, change a chosen minor variant, or treat another "
        "age/species/body/version as optional. "
    )


def extraction_instructions():
    return (
        source_policy.selection_instructions()
        + appearance_state_instructions()
        + (
            "Preserve the meaning of source terminology, including compound nouns and names of plants, garments, "
            "materials, patterns, hairstyles and ornaments. For an English source, keep its specific noun phrase where"
            " possible instead of simplifying it into an imagined shape or material. Do not split a named concept into"
            " the everyday meanings of its words. A named motif is not the actual animal/object; a resemblance is not "
            "identity, and a figurative material/color name is not proof of physical material. Do not add a shape, "
            "texture, construction, material or count that the source does not state. Faithful translation and "
            "ordinary grammatical rephrasing are allowed; preserve semantic relationships, negation and qualifiers. "
            "Keep source-language wording verbatim in quote. value_en must be English only: translate a non-English "
            "term faithfully, using a recognized English equivalent when supported, never copy CJK characters into the"
            " English rendering value. Do not invent an explanatory gloss. If a term cannot be translated reliably, "
            "report that detail as a research gap rather than supplying an invalid or fabricated fact. "
        )
    )


def review_instructions():
    return (
        source_policy.selection_instructions()
        + character_variants.review_instructions()
        + appearance_state_instructions()
        + (
            "Compare the actual value_en with the source meaning, not just with the existence of quote. Check compound"
            " nouns and named concepts as whole terms; do not assume a familiar word's literal meaning inside a "
            "botanical, clothing, material or pattern name. Check object versus motif, name versus shape, color versus"
            " material, resemblance versus identity, and any added physical properties. "
            "fact_card.semantic_comparison_required lists facts whose wording needs explicit comparison. For EVERY "
            "supported fact on that list include "
            "semantic_comparison:{source_concept:string,value_concept:string,meaning_preserved:boolean} in its "
            "fact_check. State briefly what the quoted source means and what the actual value_en claims; do not merely"
            " repeat the source as if it were the value. meaning_preserved is true only if every claim in this atomic "
            "fact is entailed by the source in context. The source may contain other details omitted by this atomic "
            "fact; omission alone is not a changed meaning. Faithful synonyms, translation, inflection, word order and"
            " grammatical compression are allowed. An unsupported change of concept is unsupported even if subject, "
            "color and count match. Genuine uncertainty is unknown, not supported. For an unsupported/unknown fact the"
            " comparison is optional because it is already blocked. Do not fix or reinterpret the supplied value "
            "during review. "
        )
    )


def _words(text):
    return [
        word
        for word in re.findall("[^\\W_]+", unicodedata.normalize("NFKC", text).casefold())
        if word not in {"a", "an", "the"}
    ]


def comparison_required(fact):
    value, quote = (_words(fact.get("value_en", "")), _words(fact.get("quote", "")))
    return not value or not any(
        (quote[index : index + len(value)] == value for index in range(len(quote) - len(value) + 1))
    )


def validate_check(item, fact):
    """Enforce comparison completeness/consistency, not truth of the LLM's claim."""
    comparison = item.get("semantic_comparison")
    if comparison is None:
        if item.get("status") == "supported" and comparison_required(fact):
            raise ValueError("supported rewritten fact lacks semantic comparison: " + fact["id"])
        return item
    if (
        not isinstance(comparison, dict)
        or type(comparison.get("meaning_preserved")) is not bool
        or any(
            (
                not isinstance(comparison.get(key), str) or not comparison[key].strip()
                for key in ("source_concept", "value_concept")
            )
        )
    ):
        raise ValueError("invalid semantic comparison: " + fact["id"])
    if item.get("status") == "supported" and (not comparison["meaning_preserved"]):
        return dict(
            item,
            status="unsupported",
            reason=str(item.get("reason", ""))
            + " [semantic comparison says the source meaning was not preserved]",
        )
    return item
