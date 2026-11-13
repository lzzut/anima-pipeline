"""Evidence-grounded character features from Booru tag frequency.

Do not invent body/age profiles. Only keep appearance tags that are actually
observed for this character; if there is no evidence, leave the field empty.
"""

import re

FEATURE_ALLOW = re.compile(
    (
        "(?i)(hair|eye|horn|ear|tail|ahoge|braid|ponytail|twintail|ribbon|ornament|earring|mole|flower|bell|mask|g"
        "lasses|fang|pupil|eyelash|eyebrow|bangs|tattoo|scar|headwear|hat|hairclip|hairpin|choker|collar|frecles|f"
        "reckles|skin)"
    )
)
FEATURE_BLOCK = re.compile(
    "(?i)(breast|bust|cleavage|navel|hip|thigh|waist|curvy|voluptuous|mature|adult|child|loli|teen|body|figure|proportion|ass|legs?$)"
)
EYE_RE = re.compile(
    "(?i)^(light |dark |pale |deep |bright )?(red|blue|green|purple|violet|aqua|teal|yellow|orange|pink|gold|amber|grey|gray|brown) eyes?$"
)


def ground_character_features(st, name_en, sample=40):
    """Overwrite appearance/eye fields with observed Booru tags only."""
    try:
        from anima_pipeline.research.booru_client import appearance_tags

        tags = appearance_tags(name_en, sample=sample) or []
    except Exception as e:
        print(f"[资料库] 查询失败（{type(e).__name__}），不添加未经验证的外观词")
        st["grounded_appearance"] = ""
        st["grounded_source"] = f"error:{type(e).__name__}"
        return st
    kept, eye = ([], "")
    for tag in tags:
        t = str(tag).replace("_", " ").strip()
        if not t or FEATURE_BLOCK.search(t):
            continue
        if EYE_RE.match(t):
            if not eye:
                eye = t
            continue
        if FEATURE_ALLOW.search(t):
            tl = t.lower()
            if tl not in [x.lower() for x in kept]:
                kept.append(t)
        if len(kept) >= 8:
            break
    st["grounded_appearance"] = ", ".join(kept)
    st["grounded_source"] = f"safebooru sample={sample}"
    if eye:
        st["eye_colors"] = eye
    extra = []
    for field in ("core_features", "appearance"):
        for part in str(st.get(field) or "").split(","):
            t = part.strip()
            if not t or FEATURE_BLOCK.search(t):
                continue
            tl = t.lower()
            if tl not in [x.lower() for x in kept + extra]:
                extra.append(t)
            if len(kept) + len(extra) >= 12:
                break
        if len(kept) + len(extra) >= 12:
            break
    st["hybrid_features"] = ", ".join((kept + extra)[:12])
    print(
        f"[资料库] {name_en}: grounded={st['grounded_appearance'] or '无'} hybrid={st['hybrid_features'] or '无'} eyes={eye or '无'}"
    )
    return st
