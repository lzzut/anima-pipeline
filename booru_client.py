# -*- coding: utf-8 -*-
"""
booru_client.py — Danbooru 数据的本机可用替代通道

【背景】本机实测（2026-10）danbooru.donmai.us 及其官方镜像走不通：
    danbooru.donmai.us      → ConnectTimeout（连 curl 都是 000）
    safebooru.donmai.us     → 403 Cloudflare 盾（curl 也过不去）
    betabooru.donmai.us     → 403 Cloudflare 盾
    konachan.net            → 403 Cloudflare 盾；konachan.com / yande.re /
                              gelbooru.com / rule34.xxx / zerochan → 全部不可达

【可用的三条通道（均已实测 200 OK）】
  1) 本地 Danbooru 标签总表（离线，最稳）
     raw.githubusercontent.com 或 ghproxy.net 拉 tagcomplete 的 danbooru.csv
     （约 1.4 MB，格式：tag,category,post_count,"aliases"
      → 能校验标签拼写、拿真实 Danbooru 投稿数当热度）
  2) safebooru.org —— Gelbooru 系 JSON API（安全版图库）
     → 可查某 tag 的实时图片数（<posts count="...">），可拿图片直链
  3) sakizuki-danboorusearch.hf.space —— Danbooru Tags Searcher
     → 可查标签的中文名、分类、wiki 描述（角色设定/服装细节）

用法：
    from booru_client import lookup, search_tags, safebooru_count, related_tags
    info = lookup("firefly_(honkai:_star_rail)")
"""
import json
import os
import re
import time

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json,*/*"}

TAG_INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "danbooru_tags.csv")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "booru_cache.json")

# 多条下载链，按实测可用顺序；raw.github / ghproxy 都验证过有数据
TAG_INDEX_URLS = [
    "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/"
    "master/tags/danbooru.csv",
    "https://ghproxy.net/https://raw.githubusercontent.com/DominikDoom/"
    "a1111-sd-webui-tagcomplete/master/tags/danbooru.csv",
]

SAFEBOORU_URL = "https://safebooru.org/index.php"
SAKIZUKI_URL = "https://sakizuki-danboorusearch.hf.space/api/related"

REQUEST_TIMEOUT = 25.0
MIN_INTERVAL = 0.5

# Danbooru 标签分类编号
CATEGORY_NAMES = {
    0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta",
}
CATEGORY_IDS = {v: k for k, v in CATEGORY_NAMES.items()}

_index = None
_cache = {}
_last_request = 0.0


def _throttle():
    global _last_request
    wait = MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


# ===========================================================================
# 通道 1：本地标签总表（离线校验拼写 + 真实 Danbooru 投稿数）
# ===========================================================================
def download_tag_index(force=False, verbose=True):
    """下载 Danbooru 标签总表（约 1.4MB），已存在则跳过。返回本地路径。"""
    if os.path.exists(TAG_INDEX_FILE) and not force:
        size = os.path.getsize(TAG_INDEX_FILE)
        if size > 500_000:
            if verbose:
                print(f"[标签总表] 已存在：{TAG_INDEX_FILE}（{size / 1024:.0f} KB）")
            return TAG_INDEX_FILE

    last_error = None
    for url in TAG_INDEX_URLS:
        try:
            if verbose:
                print(f"[标签总表] 下载中：{url[:80]} …")
            _throttle()
            with httpx.stream("GET", url, headers=HEADERS,
                              timeout=120, follow_redirects=True) as resp:
                resp.raise_for_status()
                total = 0
                tmp = TAG_INDEX_FILE + ".part"
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(65536):
                        f.write(chunk)
                        total += len(chunk)
            if total < 500_000:
                raise ValueError(f"文件过小（{total} 字节），疑似失败")
            os.replace(tmp, TAG_INDEX_FILE)
            if verbose:
                print(f"[标签总表] 完成：{total / 1024:.0f} KB → {TAG_INDEX_FILE}")
            return TAG_INDEX_FILE
        except Exception as e:
            last_error = e
            if verbose:
                print(f"[标签总表] 失败：{type(e).__name__}: {str(e)[:90]}")
    raise RuntimeError(f"标签总表下载失败：{last_error}")


def _load_index(verbose=False):
    """懒加载标签总表到内存：{tag: (category, post_count, aliases)}"""
    global _index
    if _index is not None:
        return _index
    if not os.path.exists(TAG_INDEX_FILE) or os.path.getsize(TAG_INDEX_FILE) < 500_000:
        download_tag_index(verbose=verbose)
    index = {}
    with open(TAG_INDEX_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(",", 3)
            if len(parts) < 3:
                continue
            tag = parts[0]
            try:
                category = int(parts[1])
                count = int(parts[2])
            except ValueError:
                continue
            aliases = parts[3].strip('"') if len(parts) > 3 else ""
            index[tag] = (category, count, aliases)
    _index = index
    if verbose:
        print(f"[标签总表] 载入 {len(index)} 个标签")
    return index


def tag_info(tag):
    """离线查一个标签：分类 + Danbooru 投稿数 + 别名。返回值 found=False 表示拼写错误。"""
    tag = (tag or "").strip()
    if not tag:
        return {"tag": tag, "found": False, "error": "标签为空"}
    try:
        index = _load_index()
    except Exception as e:
        return {"tag": tag, "found": None, "error": f"标签总表不可用：{e}"}

    key = tag.lower().replace(" ", "_")
    hit = index.get(key)
    if hit is None:
        # 别名兜底（别名表里存的是 "a,b,c"）
        for t, (cat, cnt, alias) in index.items():
            if key in [a.strip() for a in alias.split(",") if a.strip()]:
                return {"tag": tag, "found": True, "canonical": t,
                        "category": CATEGORY_NAMES.get(cat, str(cat)),
                        "post_count": cnt, "matched_by": "alias"}
        return {"tag": tag, "found": False,
                "hint": "本地总表里没有这个标签，可能拼写有误或太新"}

    cat, cnt, alias = hit
    return {
        "tag": key, "found": True,
        "category": CATEGORY_NAMES.get(cat, str(cat)),
        "post_count": cnt,
        "aliases": [a.strip() for a in alias.split(",") if a.strip()][:8],
    }


def search_tags(keyword, category=None, limit=10):
    """
    在本地总表里模糊搜标签（按投稿数降序）。
    用来反查"这个角色/作品的正确标签怎么写"，category 可填 character / copyright。
    """
    keyword = (keyword or "").strip().lower().replace(" ", "_")
    if not keyword:
        return []
    index = _load_index()
    want = CATEGORY_IDS.get(category) if category else None

    hits = []
    for tag, (cat, cnt, alias) in index.items():
        if want is not None and cat != want:
            continue
        if keyword == tag or keyword in tag or keyword in alias.lower():
            hits.append((cnt, tag, cat, alias))
    hits.sort(reverse=True)
    return [{"tag": t, "category": CATEGORY_NAMES.get(c, str(c)),
             "post_count": n,
             "aliases": [a.strip() for a in al.split(",") if a.strip()][:6]}
            for n, t, c, al in hits[:limit]]


# ===========================================================================
# 通道 2：safebooru.org（Gelbooru 系，实测 200 OK）
# ===========================================================================
def safebooru_count(tag):
    """查 safebooru.org 上该标签的实时图片数（<posts count="N">）。"""
    _throttle()
    r = httpx.get(SAFEBOORU_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                  follow_redirects=True,
                  params={"page": "dapi", "s": "post", "q": "index",
                          "limit": 0, "tags": tag})
    r.raise_for_status()
    m = re.search(r'count="(\d+)"', r.text)
    return int(m.group(1)) if m else 0


def search_posts(tags, limit=5, pid=0):
    """在 safebooru.org 上搜图，返回帖子信息（含图片直链，可用于参考图）。"""
    _throttle()
    r = httpx.get(SAFEBOORU_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                  follow_redirects=True,
                  params={"page": "dapi", "s": "post", "q": "index",
                          "json": 1, "limit": limit, "pid": pid, "tags": tags})
    r.raise_for_status()
    try:
        posts = r.json()
    except Exception:
        return []
    out = []
    for p in posts if isinstance(posts, list) else []:
        out.append({
            "id": p.get("id"),
            "file_url": p.get("file_url"),
            "preview_url": p.get("preview_url"),
            "created_at": p.get("created_at") or "",
            "tags": (p.get("tags") or "")[:400],
        })
    return out


def character_first_post_date(character_tag):
    """角色级首帖日期（safebooru 最老一张单人图），用于门控的出道日期。"""
    key = (character_tag or "").strip().lower()
    if not key:
        return ""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "booru_first_post_cache.json")
    data = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if data.get(key):
        return data[key]
    date = ""
    try:
        q = f"{character_tag} solo"
        total = safebooru_count(q)
        if total > 0:
            pid = max(0, (total - 1) // 100)
            posts = search_posts(q, limit=100, pid=pid)
            dates = [str(p.get("created_at") or "")[:10] for p in posts
                     if str(p.get("created_at") or "")[:10]]
            if dates:
                date = min(dates)
            elif posts:
                # safebooru JSON 没有 created_at → 抓最老一张的帖子页取日期
                oldest = min(posts, key=lambda p: p.get("id") or 0)
                try:
                    from web_search import fetch_page
                    url = ("https://safebooru.org/index.php?page=post&s=view&id=%s"
                           % oldest.get("id"))
                    page = fetch_page(url, max_chars=4000)
                    if page.get("ok"):
                        m = re.search(r"(20\d{2}-\d{2}-\d{2})", page.get("text") or "")
                        if m:
                            date = m.group(1)
                except Exception:
                    pass
    except Exception:
        date = ""
    data[key] = date
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return date


def appearance_tags(character_tag, sample=40, limit=18, verbose=True):
    """
    **挖掘该角色的高频外观标签**（2026-10-11 新增，规划中的 B 方案）。

    做法：拉 safebooru 上该角色的 N 张帖子 → 汇总每张帖子的标签 → 统计频率
          → 只保留"发色/瞳色/眼型/发饰/颈饰/配饰"类 → 出现≥2 次的取前 N 个。

    为什么比搜索引擎准：数据来自**真实二创的标签**，不是网页摘要的转述。
    结果落本地缓存（同角色只抓一次），网络失败返回空表（调用方当没有即可）。
    """
    import collections
    key = (character_tag or "").strip().lower()
    if not key:
        return []
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "booru_appearance_cache.json")
    data = {}
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if key in data:
        return data[key]
    hints = ("hair", "eyes", "eyebrow", "eyelash", "pupil", "heterochromia", "ahoge",
             "hairband", "headband", "hair_ornament", "hair_ribbon", "hat", "bow",
             "ribbon", "choker", "necklace", "earring", "pendant", "gem", "jewel",
             "horn", "halo", "crown", "veil", "gloves", "thigh_strap", "tattoo",
             # 强辨识锚点（2026-10-12 新增：雷电将军的 mole_under_eye 出现 24/40，
             # 是"像不像本人"的关键，之前完全没被挖掘）
             "mole", "scar", "freckles", "fang", "eyepatch", "bandage", "streaked",
             # ★ 发型结构类（2026-10-12 补：braid/blunt_bangs 不含 "hair" 子串 →
             #   被过滤器漏掉 → 雷神的麻花辫从未进入正向 → 出图不像本人）
             "braid", "twintails", "ponytail", "bun", "bangs", "sidelock", "wavy",
             "straight hair", "curly", "drill", "hair over", "gauntlet", "pauldron",
             "armor", "sleeves", "collar", "obi", "sash", "frill", "lace", "corset")
    _bare = key.split("(")[0].strip("_ ") or key
    try:
        # 只采样**单人图**（solo）：多角色同框图会把别人的发色/服饰带进来
        # （实测芙宁娜的采样里混进 blonde_hair/black_hair/brown_hair，且频率不低，
        #   靠频率门槛压不掉 → 必须从源头过滤）
        posts = search_posts(f"{key} solo", limit=sample)
        # 标签降级：safebooru 上不少角色的实际标签不带作品后缀（如 raiden_shogun）
        if len(posts) < max(6, sample // 4) and _bare != key:
            _p2 = search_posts(f"{_bare} solo", limit=sample)
            if len(_p2) > len(posts):
                posts = _p2
                if verbose:
                    print(f"  [外观标签挖掘] 标签降级命中：{key} → {_bare}")
        if len(posts) < max(6, sample // 4):
            _p3 = posts or search_posts(key, limit=sample)
            if len(_p3) > len(posts):
                posts = _p3
    except Exception:
        return []
    cnt = collections.Counter()
    for p in posts:
        for t in (p.get("tags") or "").split():
            cnt[t] += 1
    mined = []
    for t, c in cnt.most_common():
        tl = t.lower()
        if c < max(3, int(sample * 0.15)) or tl == key:
            continue
        if any(h in tl for h in hints):
            mined.append(t)
        if len(mined) >= limit:
            break
    if verbose:
        print(f"  [外观标签挖掘] {key}: 采样 {len(posts)} 张 → 得到 {len(mined)} 个高频外观标签")
    data[key] = mined
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return mined


def theme_volume(character_tag, theme_tag):
    """角色×主题的共现图量（safebooru 实时计数）—— 作为"该主题训练量"的代理指标。"""
    try:
        return safebooru_count(f"{character_tag} {theme_tag}")
    except Exception:
        return -1


def character_total(character_tag):
    try:
        return safebooru_count(character_tag)
    except Exception:
        return -1


def expression_tags(character_tag, sample=40, limit=14, verbose=True):
    """
    **挖掘该角色的高频表情/神态标签**（2026-10-12 新增）。

    用途：解决"所有角色都默认微笑、神态不符合人物性格"——
         用**真实二创标签**判定该角色的常态表情（如雷电将军多为 expressionless/serious），
         再据此由代码锁定表情、并在负面里排除笑容。数据来自 safebooru 单人图，**不靠 LLM 杜撰**。
    """
    import collections
    key = (character_tag or "").strip().lower()
    if not key:
        return []
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "booru_expression_cache.json")
    data = {}
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    if key in data:
        return data[key]
    ex_kw = ("expressionless", "serious", "calm", "stoic", "frown", "pout", "angry",
             "smile", "smiling", "grin", "open mouth", "closed mouth", "shouting",
             "sad", "crying", "embarrassed", "blush", "half-closed eyes", "glaring",
             "smug", "surprised", "nervous", "determined", "gentle smile", "evil smile")
    _bare = key.split("(")[0].strip("_ ") or key
    try:
        posts = search_posts(f"{key} solo", limit=sample)
        if len(posts) < max(6, sample // 4) and _bare != key:
            _p2 = search_posts(f"{_bare} solo", limit=sample)      # 标签降级：去掉作品后缀
            if len(_p2) > len(posts):
                posts = _p2
                if verbose:
                    print(f"  [表情标签挖掘] 标签降级命中：{key} → {_bare}")
        if len(posts) < max(6, sample // 4):
            _p3 = search_posts(key, limit=sample)
            if len(_p3) > len(posts):
                posts = _p3
    except Exception:
        return []
    cnt = collections.Counter()
    for p in posts:
        for t in (p.get("tags") or "").split():
            t2 = t.lower().replace("_", " ")      # 归一化：closed_mouth → closed mouth（否则永远匹配不上）
            if t2 in ex_kw:
                cnt[t2] += 1
    thresh = max(3, int(sample * 0.05))     # 3 张即算（0.15 太严：雷神只挖到 closed mouth 一个词，
                                            #   表情锁定后反而变面瘫 → 放宽以取到更多真实神态标签）
    out = [t for t, c in cnt.most_common() if c >= thresh][:limit]
    if verbose:
        print(f"  [表情标签挖掘] {key}: 采样 {len(posts)} 张 → {out}")
    data[key] = out
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return out


# ===========================================================================
# 通道 3：sakizuki Danbooru Tags Searcher（中文名 / 分类 / wiki 描述）
# ===========================================================================
def related_tags(tags, limit=10, show_nsfw=False):
    """
    查某个 Danbooru 标签的关联信息：中文名、分类、wiki 描述。
    wiki 描述对写提示词很有用（会写明服装款式、颜色、配件）。
    """
    if isinstance(tags, str):
        tags = [tags]
    _throttle()
    r = httpx.post(SAKIZUKI_URL, headers={**HEADERS, "Content-Type": "application/json"},
                   timeout=REQUEST_TIMEOUT,
                   json={"tags": tags, "limit": limit, "show_nsfw": show_nsfw})
    r.raise_for_status()
    data = r.json()
    results = data.get("results", data if isinstance(data, list) else [])
    return [{
        "tag": x.get("tag"),
        "cn_name": x.get("cn_name"),
        "category": x.get("category"),
        "wiki": (x.get("wiki") or "")[:400],
    } for x in results]


# ===========================================================================
# 合并查询
# ===========================================================================
def lookup(tag, with_wiki=True):
    """
    一个标签的全量信息：本地总表（拼写+真实投稿数）+ safebooru 实时数
    + sakizuki 中文名/wiki 描述。任何一路失败都不影响其它路。
    """
    cache_key = (tag, with_wiki)
    if cache_key in _cache:
        return _cache[cache_key]

    info = {"tag": tag}
    try:
        info["danbooru"] = tag_info(tag)
    except Exception as e:
        info["danbooru"] = {"found": None, "error": f"{type(e).__name__}: {e}"}
    try:
        info["safebooru_count"] = safebooru_count(tag)
    except Exception as e:
        info["safebooru_count"] = None
        info["safebooru_error"] = f"{type(e).__name__}: {str(e)[:80]}"
    if with_wiki:
        try:
            info["related"] = related_tags([tag], limit=12)
        except Exception as e:
            info["related"] = []
            info["related_error"] = f"{type(e).__name__}: {str(e)[:80]}"

    _cache[cache_key] = info
    return info


def suggest_canonical_tag(keyword, category="character", limit=5):
    """
    拼写纠错：把模型写的不规范标签，纠正成本地总表里真实存在、且投稿数最高的那个。
    例：suggest_canonical_tag("firefly") → firefly_(honkai:_star_rail)
    """
    hits = search_tags(keyword, category=category, limit=limit)
    if hits:
        return hits[0]["tag"], hits
    hits = search_tags(keyword, category=None, limit=limit)
    return (hits[0]["tag"] if hits else None), hits


# ===========================================================================
# 命令行自测
# ===========================================================================
if __name__ == "__main__":
    import sys

    tag = " ".join(sys.argv[1:]).strip() or "firefly_(honkai:_star_rail)"
    print("=" * 72)
    print(f"测试标签：{tag}")

    print("\n[1] 本地标签总表（离线校验 + 真实投稿数）")
    try:
        download_tag_index()
        print("  tag_info:", json.dumps(tag_info(tag), ensure_ascii=False))
        print("  拼写纠错 suggest('firefly', character):",
              json.dumps(suggest_canonical_tag("firefly"), ensure_ascii=False)[:300])
    except Exception as e:
        print(f"  失败：{type(e).__name__}: {e}")

    print("\n[2] safebooru.org（实时计数 + 图片直链）")
    try:
        print("  图片数:", safebooru_count(tag))
        posts = search_posts(tag, limit=2)
        for p in posts:
            print(f"  · id={p['id']} {p['file_url']}")
        if posts and posts[0].get("file_url"):
            _throttle()
            head = httpx.get(posts[0]["file_url"], headers=HEADERS, timeout=30,
                             follow_redirects=True)
            print(f"  首图可下载：HTTP {head.status_code}, "
                  f"{len(head.content) / 1024:.0f} KB, "
                  f"{head.headers.get('content-type')}")
    except Exception as e:
        print(f"  失败：{type(e).__name__}: {e}")

    print("\n[3] sakizuki Danbooru Tags Searcher（中文名 + wiki 服装描述）")
    try:
        for x in related_tags([tag], limit=6):
            print(f"  · [{x['category']}] {x['tag']}")
            print(f"      中文：{x['cn_name']}")
            if x["wiki"]:
                print(f"      wiki：{x['wiki'][:120]}")
    except Exception as e:
        print(f"  失败：{type(e).__name__}: {e}")
