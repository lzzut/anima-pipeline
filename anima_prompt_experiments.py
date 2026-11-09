"""Isolated prompt ablations; profiles describe hypotheses, never measured gains."""

from __future__ import annotations
import re

PROFILES = {
    "baseline": {"factor": "baseline", "extra_calls": 0},
    "concise": {
        "factor": "writing detail",
        "extra_calls": 0,
        "directive": (
            "Use the shortest complete description that retains every visible identity fact, garment structure and "
            "contact relation. Remove repeated modifiers; never truncate sentences."
        ),
    },
    "detailed": {
        "factor": "writing detail",
        "extra_calls": 0,
        "directive": (
            "Add precise visible garment construction, material, spatial relations and motivated light where they help"
            " this scene. No filler, invented identity details or arbitrary length quota."
        ),
    },
    "sentence_separator": {"factor": "prose block separator", "extra_calls": 0},
    "comma_separator": {"factor": "prose block punctuation", "extra_calls": 0},
    "identity_first": {"factor": "header tag order", "extra_calls": 0},
    "quality_minimal": {"factor": "quality prefix", "extra_calls": 0},
    "quality_extra": {"factor": "quality prefix", "extra_calls": 0},
    "identity_weight_105": {"factor": "identity weight", "extra_calls": 0},
    "identity_weight_110": {"factor": "identity weight", "extra_calls": 0},
    "per_framing": {"factor": "dedicated framing rewrite", "extra_calls": 2},
    "second_reviewer": {"factor": "independent review model", "extra_calls": 2},
}


def profile(name):
    if name not in PROFILES:
        raise ValueError("unknown prompt experiment: " + str(name))
    return dict(PROFILES[name], name=name, measured_image_gain=False)


def header(prefix, character, series, name):
    if name == "identity_first":
        return f"1girl, solo, {character}, {series}, {prefix}"
    if name == "quality_minimal":
        prefix = ", ".join(
            (
                tag.strip()
                for tag in prefix.split(",")
                if tag.strip().lower() not in {"masterpiece", "best quality"}
                and (not re.fullmatch("score_\\d+", tag.strip(), re.I))
            )
        )
    if name == "quality_extra":
        existing = {tag.strip().lower() for tag in prefix.split(",")}
        extras = [
            tag for tag in ("masterpiece", "best quality", "high detail") if tag not in existing
        ]
        prefix = ", ".join([prefix] + extras)
    return ", ".join((part for part in (prefix, "1girl", "solo", character, series) if part))


def identity_text(values, name):
    weight = {"identity_weight_105": "1.05", "identity_weight_110": "1.10"}.get(name)
    if not weight:
        return ", ".join(values)
    weighted = []
    for value in values:
        escaped = re.sub("([\\\\():])", "\\\\\\1", value)
        weighted.append(f"({escaped}:{weight})")
    return ", ".join(weighted)


def join_blocks(blocks, name):
    cleaned = [block.strip() for block in blocks if block and block.strip()]
    if name == "comma_separator":
        return ", ".join((block[:-1] if block.endswith(".") else block for block in cleaned))
    return " ".join(cleaned) if name == "sentence_separator" else "\n".join(cleaned)


def trial_plan():
    return {
        "schema": "anima_prompt_trial_plan_v1",
        "profiles": [profile(name) for name in PROFILES],
        "render_candidates_per_channel": 3,
        "automatic_generation": False,
        "comparison_rules": [
            "Compare one profile with baseline using identical character/version, evidence, theme and render settings.",
            "Compiler profiles reuse the identical approved draft; writing profiles change the writing request and must be labelled accordingly.",
            "Per-framing comparisons use the same explicitly chosen frame in both arms; never impose random framing quotas.",
            "Use matched seeds and retain all three candidates; do not infer improvement from the aesthetic winner alone.",
            "Record factual retention, theme compliance, scene contradictions, overall preference, request count and latency.",
            "Do not enable a profile by default without observed improvement across more than one character/theme and no factual regression.",
            "Stop a profile when repeated comparisons show no useful gain or higher failure/call cost without benefit.",
        ],
    }
