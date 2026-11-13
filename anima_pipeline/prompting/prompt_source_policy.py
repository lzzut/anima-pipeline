"""Build rendering features from supplied selections without external backfill."""

from anima_pipeline.prompting.framing_content import split_prompt_tags


def merge_selected_features(structured, limit=12):
    selected = []
    seen = set()
    for field in ("core_features", "appearance", "hybrid_features"):
        value = structured.get(field)
        if not isinstance(value, str):
            continue
        for clause in split_prompt_tags(value):
            key = clause.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                selected.append(clause)
    return ", ".join(selected[:limit])
