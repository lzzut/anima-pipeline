"""Semantic prompt de-duplication / conflict resolution.

The LLM, Booru mining and the template all write into the same prompt.
Exact string de-dup is not enough: "full bust" + "large breasts" +
"hourglass figure" all survive. This layer keeps one authoritative value per
semantic slot (age/body, eyes, framing, expression) and drops contradictions.

It intentionally does not do character recognition or identity filtering.
"""

import re

FRAMING_TAGS = {
    "full body",
    "cowboy shot",
    "upper body",
    "close-up",
    "portrait",
    "medium shot",
    "wide shot",
}
EYE_RE = re.compile(
    "(?i)^(light |dark |pale |deep |bright )?(red|blue|green|purple|violet|aqua|teal|yellow|orange|pink|gold|amber|grey|gray|brown) eyes?$"
)
BAD_EXPRESSION = {
    "expressionless",
    "blank stare",
    "dead eyes",
    "doll-like stare",
    "emotionless",
    "lifeless eyes",
    "stiff expression",
}


def _dedupe(items):
    seen, out = (set(), [])
    for x in items:
        s = str(x or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def sanitize_prompt_tags(tags, structured=None, theme=None, framing=None, max_tags=130):
    """Return a semantically de-duplicated tag list.

    Canonical priority:
      body/body_type + eye_colors + expression + framing
      > LLM other fields
      > Booru/template tags
    """
    st = structured or {}
    eye = str(st.get("eye_colors") or "").strip()
    if eye and (not re.search("(?i)\\beyes?\\b", eye)):
        eye = ""
    canonical = []
    if eye:
        canonical.extend((x.strip() for x in eye.split(",") if x.strip()))
    if framing:
        canonical.append(str(framing))
    main_expressions = set()
    if st.get("_expression_policy"):
        from framing_content import split_prompt_tags

        main_expressions = {
            part.strip().lower()
            for part in split_prompt_tags(
                st.get("expression_priority") or st.get("expression") or ""
            )
        }
    out = []
    for tag in tags:
        s = str(tag or "").strip()
        if not s:
            continue
        low = s.lower()
        if EYE_RE.match(s):
            continue
        if framing and low in FRAMING_TAGS:
            continue
        if low in BAD_EXPRESSION and low not in main_expressions:
            continue
        out.append(s)
    front = out[:3]
    rest = out[3:]
    out = _dedupe(front + canonical + rest)
    if max_tags and len(out) > max_tags:
        out = out[:max_tags]
    return ", ".join(out)
