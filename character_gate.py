# -*- coding: utf-8 -*-
"""
character_gate.py — 工作流 × 人物 能力门控（三级判定）

【要解决的问题】
随机到某条工作流后，如果那个模型根本不认识这个角色，出图就是"通用脸"，
还原度直接崩掉。所以选角必须落在该模型的"人物选择范围"内。

【判定顺序】
  ① 查该模型训练数据范围：**先联网查**角色出道年份/作品（时间限制、作品限制），
     查不到或联网不可用时，退到**本地信息文件兜底**
  ② 仍无法确认 → **舍弃此人物**，换人

【数据来源】
  · 联网：web_search.search()（本机可用的 Bing RSS + 360）
  · 本地兜底：data/danbooru_tags.csv（tag,category,post_count）
      category 4 = 角色标签，3 = 作品/版权标签
  · 本地兜底：config.SERIES_DEBUT_YEAR（作品出道年份表）
"""
import csv
import json
import os
import re

import config as _cfg
from config import (
    WORKFLOW_MODEL_INFO, CHARACTER_MIN_POSTS, SERIES_MIN_POSTS,
    series_debut_year, CHARACTER_GATE_WEB, GATE_WEB_MAX_RESULTS,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAG_CSV = os.path.join(BASE_DIR, "data", "danbooru_tags.csv")
CACHE_FILE = os.path.join(BASE_DIR, "character_gate_cache.json")

CAT_CHARACTER = "4"
CAT_COPYRIGHT = "3"


# ---------------------------------------------------------------------------
# 2026-10-21：日期精确到月/日（模型截止日 + 角色出道日）
#   比较规则：按双方都有的**最细粒度**比；无法证明更晚 → 放行。
#   Anima 官方卡只有 "September 2025"（月）；Animagine 有 2025-01-07（日）；Nova 只有 2024（年）。
# ---------------------------------------------------------------------------
def parse_debut_date(value):
    """'2025-09-15' / '2025-09' / '2025' / '2025年9月15日' / int -> (y, m, d)；非法 None"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        y = int(value)
        return (y, None, None) if 1970 <= y <= 2070 else None
    s = str(value).strip()
    m = re.match(r"^(\d{4})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?$", s)
    if not m:
        m = re.match(r"^(\d{4})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?$", s)
    if not m:
        return None
    try:
        y = int(m.group(1))
        mo = int(m.group(2)) if m.group(2) else None
        d = int(m.group(3)) if m.group(3) else None
    except Exception:
        return None
    if not (1970 <= y <= 2070):
        return None
    if mo is not None and not (1 <= mo <= 12):
        mo = None
    if d is not None and not (1 <= d <= 31):
        d = None
    return (y, mo, d)


def debut_after(deb, cutoff):
    """deb 是否晚于 cutoff（按双方最细的共同精度；无法证明更晚 → False）"""
    if not deb or not cutoff:
        return False
    if deb[0] != cutoff[0]:
        return deb[0] > cutoff[0]
    if deb[1] is None or cutoff[1] is None:
        return False
    if deb[1] != cutoff[1]:
        return deb[1] > cutoff[1]
    if deb[2] is None or cutoff[2] is None:
        return False
    return deb[2] > cutoff[2]


def _cutoff_parts(info):
    return parse_debut_date((info or {}).get("cutoff_date") or (info or {}).get("cutoff_year"))

# 只采信这些百科/WIKI 域名的摘要（实测本机搜索的官网/论坛摘要年份极不可靠）
WIKI_DOMAINS = (
    "baike.baidu.com", "zh.wikipedia.org", "wikipedia.org", "moegirl.org",
    "fandom.com", "huijiwiki.com", "wiki.gg",
    "game8.co", "gamewith.jp", "kamigame.jp", "hpoi.net", "bangumi.tv",
)

YEAR_RE = re.compile(r"(19[7-9]\d|20[0-4]\d)")
# 2026-10-21：日期到月/日（摘要里常见 2021-09-01 / 2021年9月1日 / 2021-09）
DATE_RE = re.compile(
    r"(19[7-9]\d|20[0-4]\d)\s*[年\-/.]\s*(\d{1,2})(?:\s*[月\-/.]\s*(\d{1,2}))?")
# 年份语境词：放宽（实测摘要里更常见"公测/开服/开播/发售"这类说法）
DEBUT_HINTS = (
    "初登场", "首次登场", "初次登场", "登场", "上线", "发布", "发行", "推出",
    "公开", "开服", "公测", "发售", "上市", "开播", "首播", "放送", "面世",
    "出道", "开测", "内测", "首发",
    "debut", "released", "launched", "introduced", "first appeared",
    "release date", "premiered", "aired",
)

_tag_index = None
_cache = None


# ===========================================================================
# 缓存
# ===========================================================================
def _load_cache():
    global _cache
    if _cache is None:
        _cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:
                _cache = {}
    return _cache


def _save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ===========================================================================
# 本地信息文件（兜底）
# ===========================================================================
def _load_tag_index():
    """danbooru 标签总表 → {tag: (category, post_count)}"""
    global _tag_index
    if _tag_index is not None:
        return _tag_index
    _tag_index = {}
    if os.path.exists(TAG_CSV):
        with open(TAG_CSV, "r", encoding="utf-8", errors="ignore") as f:
            for row in csv.reader(f):
                if len(row) >= 3:
                    try:
                        _tag_index[row[0].strip().lower()] = (row[1].strip(), int(row[2] or 0))
                    except ValueError:
                        continue
    return _tag_index


_alias_index = None


def _load_alias_index():
    """danbooru 标签表第 4 列（别名）→ {别名: 规范标签}（2026-10-11 新增，复用同一份 CSV）"""
    global _alias_index
    if _alias_index is not None:
        return _alias_index
    _alias_index = {}
    if os.path.exists(TAG_CSV):
        with open(TAG_CSV, "r", encoding="utf-8", errors="ignore") as f:
            for row in csv.reader(f):
                if len(row) >= 4 and row[3].strip():
                    canon = row[0].strip().lower()
                    for a in row[3].split(","):
                        a = a.strip().lower()
                        if a and a != canon:
                            _alias_index.setdefault(a, canon)
    return _alias_index


def canonical_tag(name):
    """
    把 LLM 给的角色/作品名**规范成 danbooru 官方标签**（2026-10-11 新增）。

    数据来源：`danbooru_tags.csv` 第 4 列（别名），例如
        'sorasaki_hina' → 'hina_(blue_archive)'
        'hatsune miku'  → 'hatsune_miku'（空格规范化后命中）

    为什么重要：角色标签写错/写偏 = 底模不认识该标签 = **脸不像**。
    命中则返回规范标签；未知返回 None（调用方保持原值，绝不猜）。
    """
    if not name:
        return None
    raw = str(name).strip().lower()
    cands = [raw, raw.replace(" ", "_"), raw.replace(" ", ""),
             raw.replace("_", " "),
             raw.replace("(", "").replace(")", "")]
    idx = _load_tag_index()
    for c in cands:
        if c and c in idx:
            return c
    ai = _load_alias_index()
    for c in cands:
        if c and c in ai:
            return ai[c]
    return None


def _tag_row(tag):

    cat, posts = _load_tag_index().get((tag or "").strip().lower(), ("", 0))
    return {"tag": (tag or "").strip().lower(), "category": cat,
            "posts": posts, "known": bool(cat)}


def danbooru_profile(name_en):
    """角色标签档案：是否 danbooru 角色标签 + 投稿数"""
    row = _tag_row(name_en)
    return {"tag": row["tag"], "category": row["category"],
            "is_character": row["category"] == CAT_CHARACTER,
            "posts": row["posts"], "known": row["known"]}


def series_profile(series_en):
    """作品标签档案：是否 danbooru 版权标签 + 投稿数 + 出道年份（本地表）"""
    row = _tag_row(series_en)
    return {"tag": row["tag"], "category": row["category"],
            "is_copyright": row["category"] == CAT_COPYRIGHT,
            "posts": row["posts"], "known": row["known"],
            "debut_year": series_debut_year(series_en)}


# ===========================================================================
# 联网查角色（时间限制 / 作品限制）
# ===========================================================================
def _extract_year(text):
    """从一段文字里抽"出道/发布"语境下的最早年份"""
    if not text:
        return None
    low = text.lower()
    if not any(h in low for h in DEBUT_HINTS):
        return None
    years = [int(y) for y in YEAR_RE.findall(text)]
    years = [y for y in years if 1970 <= y <= 2026]
    return min(years) if years else None


def _extract_date(text):
    """从一段文字里抽最早的 'YYYY-MM[-DD]'（无日期返回 None）"""
    if not text:
        return None
    dates = []
    for m in DATE_RE.finditer(text):
        try:
            y = int(m.group(1))
            mo = int(m.group(2))
            d = int(m.group(3)) if m.group(3) else None
        except Exception:
            continue
        if not (1970 <= y <= 2060 and 1 <= mo <= 12):
            continue
        if d is not None and not (1 <= d <= 31):
            d = None
        dates.append((y, mo, d))
    if not dates:
        return None
    y, mo, d = min(dates, key=lambda t: (t[0], t[1], t[2] or 0))
    return f"{y:04d}-{mo:02d}" + (f"-{d:02d}" if d else "")


def _web_years(queries, key, must_mention=None):
    """
    跑一组联网查询，从摘要里抽"发布语境下的最早年份"，结果缓存。

    重要（实测教训）：本机搜索摘要不可信 ——
      · 查"原神 发行日期"返回官网 2026 版本日期（会把老游戏误判成新作）
      · 查"蔚蓝档案"匹配到《蔚蓝》(Celeste, 2018)，是另一个游戏
    所以只采信**百科/WIKI 类域名**的摘要，且摘要里必须出现作品名。
    """
    cache = _load_cache()
    # 2026-10-13 修：**只复用"查到年份"的缓存**。原来把"查不到/联网失败"也永久缓存，
    # 导致角色（如芙宁娜）第一次没查到就被永久打回、联网再也不重试（实测 0 秒打回）。
    if key in cache and (cache[key] or {}).get("year"):
        return cache[key]
    out = {"year": None, "date": None, "evidence": [], "ok": False, "sources": []}
    if not CHARACTER_GATE_WEB:
        cache[key] = out
        _save_cache()
        return out

    years, dates, evidence, sources = [], [], [], []
    ok = False
    try:
        from web_search import search as ws
        for q in queries:
            res = ws(q, max_results=GATE_WEB_MAX_RESULTS)
            for r in (res.get("results") or []):
                ok = True
                url = (r.get("url") or "").lower()
                blob = f"{r.get('title', '')} {r.get('snippet', '')}"
                if not any(d in url for d in WIKI_DOMAINS):
                    continue                      # 非百科/WIKI 域名 → 不采信
                if must_mention and must_mention.lower() not in blob.lower():
                    continue                      # 摘要里没提到该作品 → 不采信
                y = _extract_year(blob)
                if y:
                    years.append(y)
                    d = _extract_date(blob)
                    if d:
                        dates.append(d)
                    evidence.append(f"{d or y} | {r.get('title', '')[:40]} | {blob[:70]}")
                    sources.append(url[:60])
    except Exception as e:
        evidence.append(f"联网失败：{type(e).__name__}")

    _date = None
    if dates:
        _date = min(dates, key=lambda s: tuple(int(x) for x in s.split("-")))
    out = {"year": (min(years) if years else None), "date": _date,
           "evidence": evidence[:3], "ok": ok, "sources": sources[:3]}
    cache[key] = out
    _save_cache()
    return out


def web_series_year(series_en, series_cn=None):
    """
    联网查【作品】发行/开播年份（作品级时间限制）。
    优先用中文名提问（本机引擎对中文更灵），并要求命中百科/WIKI 域名。
    """
    plain = (series_cn or re.sub(r"[_()]", " ", series_en or "")).strip()
    if not plain:
        return {"year": None, "evidence": [], "ok": False, "sources": []}
    return _web_years(
        [f"{plain} 发行日期 上线时间 百科", f"{plain} 游戏 发行 年份 wiki"],
        key=f"webseries|{plain.lower()}",
        must_mention=plain,
    )


def web_character_info(name_en, series_en=None, name_cn=None, series_cn=None):
    """
    联网查角色：出道年份 + 证据（先角色级，抓不到就用作品级年份兜）。
    返回 {"year", "evidence", "ok", "scope", "sources"}
    """
    # 角色级日期优先用 safebooru 首帖（可靠、免搜索摘要）
    try:
        from booru_client import character_first_post_date
        _first = character_first_post_date(name_en)
        if _first:
            return {"year": int(_first[:4]), "date": _first,
                    "evidence": [f"safebooru 首帖 {_first}"],
                    "ok": True, "sources": ["safebooru"], "scope": "character"}
    except Exception:
        pass

    plain = (name_cn or re.sub(r"[_()]", " ", name_en or "")).strip()
    series = (series_cn or re.sub(r"[_()]", " ", series_en or "")).strip()
    info = _web_years(
        [f"{plain} {series} 角色 初登场 年份 百科".strip(),
         f"{plain} 首次登场 发布时间 百科".strip()],
        key=f"web|{(name_en or '').lower()}|{(series_en or '').lower()}",
        must_mention=plain,
    )
    if info.get("year"):
        return dict(info, scope="character")
    ser = web_series_year(series_en, series_cn)
    if ser.get("year"):
        return {"year": ser["year"], "evidence": ser["evidence"], "ok": ser.get("ok"),
                "sources": ser.get("sources"), "scope": "series"}
    return dict(info, scope="none")


# ===========================================================================
# 判定
# ===========================================================================
def accepts(workflow, name_en, series_en=None, name_cn=None, series_cn=None,
            check_web=True, verbose=False, theme=None, llm_debut=None):
    """
    该工作流能不能画好这个角色。返回 (bool, 原因字符串)

    联网查（时间限制/作品限制，只采信百科域名）→ 本地信息文件兜底；
    仍无法确认则舍弃。
    """
    info = WORKFLOW_MODEL_INFO.get(workflow)
    if not info:
        return False, f"未知工作流 {workflow}"

    # ---- 2026-10-19 用户：芙宁娜眼睛画不好 → ban ----
    try:
        import config as _c3
        if str(name_en) in tuple(getattr(_c3, "CHAR_BAN_LIST", ()) or ()):
            return False, f"手工禁用：{name_en}（用户指定）"
    except Exception:
        pass

    # ---- ⓪ 儿童/萝莉体型 × 暴露主题（**方案 B**，2026-10-14 用户改）----
    #   不再"禁角色"：**仅当主题属泳装/暴露类**时才对小体型角色做判定与拒绝
    #   非暴露主题（冬日/和服/校园日常…）→ 直接放行，省掉 VLM 调用
    try:
        import config as _c2
        if theme and _c2.is_revealing_theme(theme):
            import body_judge as _bj
            _v = _bj.judge(name_en, verbose=bool(verbose))
            if _v and _v.get("childlike") is True:
                return False, (f"体型×主题拒绝：{name_en} 为儿童/萝莉体型"
                               f"（VLM {_v.get('votes')}：{_v.get('reason')}）"
                               f"且主题「{theme}」属暴露类 → 舍弃此人物")
            import booru_client as _bc
            _tags = tuple(getattr(_c2, "BANNED_BODY_TAGS", ()) or ())
            _thr = float(getattr(_c2, "BANNED_BODY_RATIO", 0.03))
            _total = _bc.character_total(name_en) if _tags else 0
            if _total and _total > 0:
                for _b in _tags:
                    _vol = _bc.theme_volume(name_en, _b)
                    if _vol and _vol > 0 and (_vol / float(_total)) >= _thr:
                        return False, (f"体型×主题拒绝：{name_en} × {_b} 共现 "
                                       f"{_vol}/{_total} = {_vol/float(_total):.1%} ≥ {_thr:.0%}"
                                       f" 且主题「{theme}」属暴露类 → 舍弃")
    except Exception:
        pass

    prof = danbooru_profile(name_en)
    ser = series_profile(series_en)

    # ---- ⓪ 角色级日期（本地缓存，方案 A）：先于联网/作品判定 ----
    #   2026-10-21：支持到月/日，按双方都有的最细精度比较。
    _cy = None
    _cd = None
    _cy_ok = False
    try:
        _cy = _cfg.char_debut_year(name_en)
        _cd = _cfg.char_debut_date(name_en)
    except Exception:
        _cy, _cd = None, None
    _deb = parse_debut_date(_cd) or parse_debut_date(_cy)
    _deb_llm = parse_debut_date(llm_debut)
    # 2026-10-21：缓存只有年、LLM 拿到月/日时，用**更细**的 LLM 日期比较；
    #   否则旧缓存的 "2025" 会挡住 "2025-10" 的精确判断。
    _prec = lambda _p: (3 if _p and _p[2] else (2 if _p and _p[1] else (1 if _p else 0)))
    if _deb_llm and _prec(_deb_llm) > _prec(_deb):
        _deb = _deb_llm
    _cut = _cutoff_parts(info)
    if _deb:
        if debut_after(_deb, _cut):
            return False, (f"角色级出道 {_cd or _cy}（本地缓存）晚于 {info['label']} "
                           f"知识截止 {info['cutoff']}")
        _cy_ok = True          # 角色级日期有效 → 后续不再因"只有作品级"被打回
    elif _cy and _cy > info["cutoff_year"]:
        return False, (f"角色级出道年 {_cy}（本地缓存）晚于 {info['label']} "
                       f"知识截止 {info['cutoff']}")

    # ---- ②-1 联网查（时间限制 / 作品限制；只认百科/WIKI 域名）----
    _web_series = None
    if check_web and CHARACTER_GATE_WEB:
        web = web_character_info(name_en, series_en, name_cn, series_cn)
        _wv = web.get("date") or web.get("year")
        if _wv:
            ev = web["evidence"][0] if web.get("evidence") else ""
            # 2026-10-13 用户规则（第1点）：**只认角色级日期/年份**
            #   作品级会把同作品的老角色判成新角色（《原神》2020 → 芙宁娜 2023 也变"老"）
            if web.get("scope") == "character":
                if debut_after(parse_debut_date(_wv), _cut):
                    return False, (f"联网百科查得角色级 {_wv}，晚于 "
                                   f"{info['label']} 的知识截止 {info['cutoff']}｜证据：{ev}")
                if not prof["is_character"]:
                    return False, (f"联网百科查得 {_wv}，但 danbooru 无角色标签 "
                                   f"（{name_en}），疑似拼写错误或非角色标签")
                return True, (f"联网百科确认（角色级）：{_wv} ≤ {info['label']} 截止 "
                              f"{info['cutoff']}，danbooru 角色投稿 {prof['posts']}｜证据：{ev}")
            _web_series = (web.get("year"), ev)

    # ---- ②-2 本地信息文件兜底 ----
    if not prof["known"]:
        return False, f"联网查不到且 danbooru 无此标签：{name_en}（舍弃此人物）"
    if not prof["is_character"]:
        return False, f"{name_en} 不是 danbooru 角色标签（category={prof['category']}）"

    # 作品限制：作品要是 danbooru 版权标签且够热
    if series_en:
        if not ser["known"]:
            return False, (f"作品标签 {series_en} 不在 danbooru 表内（作品限制不通过）"
                           f"｜角色投稿 {prof['posts']}")
        if not ser["is_copyright"]:
            return False, (f"{series_en} 不是 danbooru 版权标签"
                           f"（category={ser['category']}）")
        if ser["posts"] < SERIES_MIN_POSTS:
            return False, (f"作品 {series_en} 投稿 {ser['posts']} < {SERIES_MIN_POSTS}，"
                           f"该模型大概率没学过这个作品的画风")

    # 2026-10-20 用户：老角色要高人气，新角色有人气即可
    try:
        import config as _cp
        _yr_p = 0
        try:
            _yr_p = int(_cp.char_debut_year(name_en) or 0)
        except Exception:
            _yr_p = 0
        # 2026-10-21：缓存还没有年份时，用 LLM 的 debut_date/year 判"老/新"人气阈值
        if not _yr_p and llm_debut:
            _p_llm = parse_debut_date(llm_debut)
            _yr_p = _p_llm[0] if _p_llm else 0
        _is_old = bool(_yr_p and _yr_p <= getattr(_cp, "CHAR_POP_OLD_YEAR", 2020))
        _min_posts = (getattr(_cp, "CHAR_POP_OLD_MIN", 5000) if _is_old
                      else getattr(_cp, "CHAR_POP_NEW_MIN", 800))
        _pop_label = "老角色" if _is_old else "新角色"
    except Exception:
        _min_posts, _pop_label = CHARACTER_MIN_POSTS, "默认"
    if prof["posts"] < _min_posts:
        return False, (f"danbooru 角色投稿 {prof['posts']} < {_pop_label}阈值 {_min_posts}，"
                       f"模型大概率不认识 → 会出通用脸")

    year = ser["debut_year"]
    if year and year > info["cutoff_year"]:
        return False, (f"作品 {year} 年出道（本地年份表），晚于 {info['label']} "
                       f"知识截止 {info['cutoff']}")

    # ---- ②-1b LLM 角色级日期兜底（2026-10-21）----
    #   本地缓存/联网都拿不到角色级日期时，用选角 LLM 联网确认过的 debut_date/year。
    #   放在人气/作品检查之后：LLM 只补"日期来源"，不放宽热度/作品门槛。
    _llm_deb = parse_debut_date(llm_debut)
    if _llm_deb:
        if debut_after(_llm_deb, _cut):
            return False, (f"LLM 角色级出道 {llm_debut} 晚于 {info['label']} "
                           f"知识截止 {info['cutoff']}")
        return True, (f"LLM 角色级出道 {llm_debut} ≤ {info['label']} 截止 "
                      f"{info['cutoff']}，danbooru 角色投稿 {prof['posts']}")

    # 2026-10-13 用户规则（第1点）：**只认角色级年份**
    #   本地表是作品级年份，无法区分同作品的新老角色
    #   （雷电将军 2021 与芙宁娜 2023 同属《原神》2020）→ 一律舍弃换人
    #   （原行为：按 danbooru 热度放行）
    if _cy_ok:
        return True, (f"角色级出道 {_cd or _cy}（本地缓存）≤ {info['label']} 截止 "
                      f"{info['cutoff']}；角色投稿 {prof['posts']}，作品投稿 {ser['posts']}")
    _y = f"作品 {year} 年出道（本地表）" if year else "本地年份表未收录"
    _ws = f"；联网只查到作品级 {_web_series[0]} 年" if _web_series and _web_series[0] else ""
    return False, (f"{name_en} 只拿到作品级信息（{_y}{_ws}），拿不到角色级日期"
                   f" → 按规则舍弃此人物，请换一个不同的人物")


def eligible_workflows(name_en, series_en=None, pool=None,
                       name_cn=None, series_cn=None, theme=None,
                       llm_debut=None, exclude=(), wf_filter=None, check_web=True):
    """返回该角色能通过的 [(workflow, why), ...]（按 WORKFLOW_POOL 顺序）"""
    from config import WORKFLOW_POOL
    pool = [w for w in (pool or WORKFLOW_POOL) if w not in exclude]
    ok, reasons = [], []
    for wf in pool:
        if wf_filter and not wf_filter(wf):
            reasons.append(f"{wf}: 被 wf_filter 排除（黑名单/其它线路约束）")
            continue
        good, why = accepts(wf, name_en, series_en, name_cn=name_cn,
                            series_cn=series_cn,
                            check_web=check_web, theme=theme, llm_debut=llm_debut)
        if good:
            ok.append((wf, why))
        else:
            reasons.append(f"{wf}: {why}")
    return ok, reasons


def choose_workflow_for(name_en, series_en=None, pool=None,
                        exclude=(), name_cn=None, series_cn=None, theme=None,
                        llm_debut=None, verbose=True, wf_filter=None,
                        check_web=True):
    """
    给这个角色挑一条能画好的工作流。返回 (workflow, 原因) 或 (None, 拒绝原因列表)

    2026-10-21 用户：**以模型为导向**，只在能画这个人物的模型里随机：
      · 通过集合按基础模型 label 分组（Anima / Animagine / Nova，最多 3 个）
      · 2/3 个模型 → random.choice；只有 1 个 → 不随机
      · 选中 Anima-2.9B 后，再在通过的那条/两条（api / anima_flow）里随机
    不再把 api/anima_flow 当成两个独立模型；它们是同一套 Anima 权重。
    """
    import random
    from config import WORKFLOW_MODEL_INFO
    ok, reasons = eligible_workflows(
        name_en, series_en, pool=pool,
        name_cn=name_cn, series_cn=series_cn, theme=theme,
        llm_debut=llm_debut, exclude=exclude, wf_filter=wf_filter,
        check_web=check_web)
    if not ok:
        return None, reasons
    groups = {}
    for wf, why in ok:
        label = (WORKFLOW_MODEL_INFO.get(wf) or {}).get("label", wf)
        groups.setdefault(label, []).append((wf, why))
    label = random.choice(list(groups.keys()))
    wf, why = random.choice(groups[label])
    if verbose:
        print(f"  [模型导向] {name_en} 通过 {len(groups)} 个基础模型："
              f"{' / '.join(groups.keys())} → 选中 {label} → 线路 {wf}")
    return wf, why
