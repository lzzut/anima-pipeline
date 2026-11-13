"""Character evidence eligibility, independent of any particular character or work."""

import datetime as dt
import re
from urllib.parse import parse_qs, unquote, urlsplit

POLICY = "character_sources_v4_latest"
_NONCANON = re.compile(
    (
        "(?:^|[-_. /])(?:crossovers?|fanon|fanfiction|fan-fiction|fanmade|fan-made|roleplay|role-play|headcanons?|"
        "original-characters?|oc)(?:$|[-_. /])"
    ),
    re.I,
)


def exclusion_reason(source):
    parsed = urlsplit(str(source.get("url") or ""))
    host = (parsed.hostname or "").lower()
    section = unquote(parsed.path).split("/wiki/", 1)[0]
    if _NONCANON.search(host + " " + section):
        return (
            "fan-created or crossover continuity is not evidence for the requested original design"
        )
    return ""


def rank(source):
    parsed = urlsplit(str(source.get("url") or ""))
    query = parse_qs(parsed.query)
    archive = any((key in query for key in ("oldid", "diff")))
    revision = query.get("oldid", ["0"])[0]
    return (bool(exclusion_reason(source)), archive, -int(revision) if revision.isdigit() else 0)


def page_key(source):
    parsed = urlsplit(str(source.get("url") or ""))
    query = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()
    path = unquote(parsed.path).rstrip("/")
    if host in {"baike.baidu.com", "wapbaike.baidu.com"}:
        article = re.search("/item/(?:[^/]+/)?(\\d+)$", path)
        if article:
            return ("baike.baidu.com", article.group(1))
    if host.endswith((".fandom.com", ".wikipedia.org", ".wiki.gg")):
        title = query.get("title", [None])[0]
        return (host, "/wiki/" + title if title else path)
    return (host, path, parsed.query)


def distinct_pages(rows):
    selected = {}
    for row in sorted(rows, key=lambda row: (rank(row), preference_rank(row))):
        selected.setdefault(page_key(row), row)
    return list(selected.values())


def recency(source):
    candidates = []
    for field in ("modified_at", "updated_at", "published_date"):
        value = str(source.get(field) or "").strip()
        match = re.match("(\\d{4})-(\\d{2})-(\\d{2})(?:$|[T ])", value)
        if match:
            try:
                date = dt.date(*map(int, match.groups()))
            except ValueError:
                continue
            if date <= dt.datetime.now(dt.timezone.utc).date():
                candidates.append({"date": date.isoformat(), "basis": field, "quote": ""})
    text = str(source.get("text") or source.get("content") or "")
    match = re.search(
        "(?:last (?:edited|updated|modified)|最后编辑|最後編輯|最后更新|最後更新|更新时间|更新時間)[^\\n\\r]{0,55}?(\\d{4})[-年/](\\d{1,2})[-月/](\\d{1,2})日?",
        text,
        re.I,
    )
    if match:
        try:
            date = dt.date(*map(int, match.groups()))
        except ValueError:
            date = None
        if date is not None and date <= dt.datetime.now(dt.timezone.utc).date():
            candidates.append(
                {"date": date.isoformat(), "basis": "body_revision_date", "quote": match.group()}
            )
    return max(
        candidates,
        key=lambda item: item["date"],
        default={"date": None, "basis": "undated", "quote": ""},
    )


def preference_rank(source):
    chronology = recency(source)
    date = dt.date.fromisoformat(chronology["date"]).toordinal() if chronology["date"] else 0
    authority = {
        "official_or_publisher_page": 0,
        "publisher_community_page": 1,
        "community_reference_page": 2,
    }.get(source.get("source_level"), 3)
    return (
        bool(exclusion_reason(source)),
        -date,
        rank(source)[1],
        authority,
        source.get("read_via") == "search_index_body",
        appearance_rank(source)[2],
        -len(str(source.get("text") or source.get("content") or "")),
        str(source.get("url") or ""),
    )


def precedence(sources):
    return [
        {
            "source_id": source["id"],
            **recency(source),
            "historical_revision": rank(source)[1],
            "source_level": source.get("source_level"),
            "selection_basis": (
                "newest_dated_source"
                if recency(source)["date"]
                else "current_page_quality_tiebreak"
            ),
        }
        for source in sorted(sources, key=preference_rank)
    ]


def selection_instructions():
    return (
        "SOURCE DISAGREEMENT POLICY: the user chooses the newest applicable reference instead of requiring all "
        "references to agree. source_precedence lists eligible sources from preferred to fallback. For each "
        "disputed detail choose the first applicable source in that order, keep its quoted value, and omit the "
        "competing value from active facts. Other nonconflicting distinguishing details from other sources remain "
        "available. Do not average colors, blend versions, or generalize away supported features. A lower-priority"
        " source saying something else is not a blocking conflict once this policy selects a supported value. With"
        " no dated sources, the current-page quality order is the deterministic fallback; do not demand new dates "
        "or repeated research, and do not call an undated page proven newest. Publication/revision dates rank "
        "references, not character eligibility. The material cutoff applies ONLY to which characters may be "
        "selected; character eligibility is checked separately by the character gate. Newer descriptions and "
        "appearance details of an eligible character are allowed after that cutoff. Keep the requested "
        "character/version; reject explicitly excluded designs, other characters and unsupported claims. A general"
        " canonical appearance statement about this character applies unless the source specifically limits it to "
        "an excluded version; a stable trait need not repeat the requested game's release year to be usable. An "
        "explicitly version-specific statement takes applicability precedence over generic prose. When "
        "appearance_variant explicitly selects a source-backed minor alternative, that variant's chosen values "
        "override the default main-card source preference; never restore the other variant or mix them. Review and"
        " repair must honor the same recorded source_precedence and selected variant; do not reopen a resolved "
        "disagreement merely because the alternative source is also quoted. Missing or internally unsupported "
        "evidence still cannot be invented. "
    )


def appearance_rank(source):
    content = str(source.get("content") or source.get("text") or "")
    groups = (
        "\\bhair\\b|头发|发色|发型|长发|短发",
        "\\beyes?\\b|眼睛|瞳色|紫瞳|红瞳|蓝瞳",
        "\\b(?:outfit|wears|clothing|dress)\\b|服装|身穿|衣着",
    )
    coverage = sum((bool(re.search(pattern, content, re.I)) for pattern in groups))
    parsed = urlsplit(str(source.get("url") or ""))
    gallery = bool(
        re.search("/(?:Gallery|File:)|[?&]file=", unquote(parsed.path + "?" + parsed.query), re.I)
    )
    return (bool(exclusion_reason(source)), gallery, -coverage, rank(source)[1])


def research_queries(name, series, name_en, missing=()):
    english_name = re.sub("[():]+", " ", str(name_en).replace("_", " "))
    english_name = " ".join(english_name.split())
    english_terms = "appearance hairstyle eye color hair accessories outfit wiki"
    chinese_terms = "官方 外貌 发色 瞳色 发型 服装 性格 百科"
    if missing:
        terms = {
            "hair": "hair hairstyle",
            "eyes": "eyes eye color",
            "face": "face marks",
            "accessory": "hair ornament accessories",
            "body": "appearance body",
            "default_outfit": "original outfit clothing",
        }
        english_terms = " ".join((terms.get(item, "appearance") for item in missing)) + " wiki"
    return (
        f"{english_name[:65]} {english_terms}"[:128],
        f"{name[:30]} {series[:30]} {chinese_terms}"[:128],
    )


def eligible_card(card):
    return not any((exclusion_reason(source) for source in card.get("sources", [])))


def identity_gaps(card):
    missing = {"hair", "eyes"} - {fact["attribute"] for fact in card.get("facts", [])}
    missing.update(
        (
            gap["attribute"]
            for gap in card.get("research_gaps", [])
            if isinstance(gap, dict)
            and gap.get("importance") == "critical"
            and gap.get("reason")
            and (gap.get("attribute") in {"hair", "eyes", "face", "accessory", "body"})
        )
    )
    return sorted(missing)
