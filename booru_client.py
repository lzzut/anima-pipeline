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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json,*/*"}
TAG_INDEX_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "danbooru_tags.csv"
)
TAG_INDEX_URLS = [
    "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/master/tags/danbooru.csv",
    "https://ghproxy.net/https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/master/tags/danbooru.csv",
]
SAFEBOORU_URL = "https://safebooru.org/index.php"
SAKIZUKI_URL = "https://sakizuki-danboorusearch.hf.space/api/related"
REQUEST_TIMEOUT = 25.0
MIN_INTERVAL = 0.5
CATEGORY_NAMES = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
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


def download_tag_index(force=False, verbose=True):
    """下载 Danbooru 标签总表（约 1.4MB），已存在则跳过。返回本地路径。"""
    if os.path.exists(TAG_INDEX_FILE) and (not force):
        size = os.path.getsize(TAG_INDEX_FILE)
        if size > 500000:
            if verbose:
                print(f"[标签总表] 已存在：{TAG_INDEX_FILE}（{size / 1024:.0f} KB）")
            return TAG_INDEX_FILE
    last_error = None
    for url in TAG_INDEX_URLS:
        try:
            if verbose:
                print(f"[标签总表] 下载中：{url[:80]} …")
            _throttle()
            with httpx.stream(
                "GET", url, headers=HEADERS, timeout=120, follow_redirects=True
            ) as resp:
                resp.raise_for_status()
                total = 0
                tmp = TAG_INDEX_FILE + ".part"
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(65536):
                        f.write(chunk)
                        total += len(chunk)
            if total < 500000:
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
    if not os.path.exists(TAG_INDEX_FILE) or os.path.getsize(TAG_INDEX_FILE) < 500000:
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
        for t, (cat, cnt, alias) in index.items():
            if key in [a.strip() for a in alias.split(",") if a.strip()]:
                return {
                    "tag": tag,
                    "found": True,
                    "canonical": t,
                    "category": CATEGORY_NAMES.get(cat, str(cat)),
                    "post_count": cnt,
                    "matched_by": "alias",
                }
        return {"tag": tag, "found": False, "hint": "本地总表里没有这个标签，可能拼写有误或太新"}
    cat, cnt, alias = hit
    return {
        "tag": key,
        "found": True,
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
    return [
        {
            "tag": t,
            "category": CATEGORY_NAMES.get(c, str(c)),
            "post_count": n,
            "aliases": [a.strip() for a in al.split(",") if a.strip()][:6],
        }
        for n, t, c, al in hits[:limit]
    ]


def safebooru_count(tag):
    """查 safebooru.org 上该标签的实时图片数（<posts count="N">）。"""
    _throttle()
    r = httpx.get(
        SAFEBOORU_URL,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        params={"page": "dapi", "s": "post", "q": "index", "limit": 0, "tags": tag},
    )
    r.raise_for_status()
    m = re.search('count="(\\d+)"', r.text)
    return int(m.group(1)) if m else 0


def search_posts(tags, limit=5, pid=0):
    """在 safebooru.org 上搜图，返回帖子信息（含图片直链，可用于参考图）。"""
    _throttle()
    r = httpx.get(
        SAFEBOORU_URL,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        params={
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": 1,
            "limit": limit,
            "pid": pid,
            "tags": tags,
        },
    )
    r.raise_for_status()
    try:
        posts = r.json()
    except Exception:
        return []
    out = []
    for p in posts if isinstance(posts, list) else []:
        out.append(
            {
                "id": p.get("id"),
                "file_url": p.get("file_url"),
                "preview_url": p.get("preview_url"),
                "created_at": p.get("created_at") or "",
                "tags": (p.get("tags") or "")[:400],
            }
        )
    return out


def character_first_post_date(character_tag):
    """角色级首帖日期（safebooru 最老一张单人图），用于门控的出道日期。"""
    key = (character_tag or "").strip().lower()
    if not key:
        return ""
    data = _first_dates
    if data.get(key):
        return data[key]
    date = ""
    try:
        q = f"{character_tag} solo"
        total = safebooru_count(q)
        if total > 0:
            pid = max(0, (total - 1) // 100)
            posts = search_posts(q, limit=100, pid=pid)
            dates = [
                str(p.get("created_at") or "")[:10]
                for p in posts
                if str(p.get("created_at") or "")[:10]
            ]
            if dates:
                date = min(dates)
            elif posts:
                oldest = min(posts, key=lambda p: p.get("id") or 0)
                try:
                    from web_search import fetch_page

                    url = "https://safebooru.org/index.php?page=post&s=view&id=%s" % oldest.get(
                        "id"
                    )
                    page = fetch_page(url, max_chars=4000)
                    if page.get("ok"):
                        m = re.search("(20\\d{2}-\\d{2}-\\d{2})", page.get("text") or "")
                        if m:
                            date = m.group(1)
                except Exception:
                    pass
    except Exception:
        date = ""
    data[key] = date
    return date


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


def related_tags(tags, limit=10, show_nsfw=False):
    """
    查某个 Danbooru 标签的关联信息：中文名、分类、wiki 描述。
    wiki 描述对写提示词很有用（会写明服装款式、颜色、配件）。
    """
    if isinstance(tags, str):
        tags = [tags]
    _throttle()
    r = httpx.post(
        SAKIZUKI_URL,
        headers={**HEADERS, "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
        json={"tags": tags, "limit": limit, "show_nsfw": show_nsfw},
    )
    r.raise_for_status()
    data = r.json()
    results = data.get("results", data if isinstance(data, list) else [])
    return [
        {
            "tag": x.get("tag"),
            "cn_name": x.get("cn_name"),
            "category": x.get("category"),
            "wiki": (x.get("wiki") or "")[:400],
        }
        for x in results
    ]


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
        return (hits[0]["tag"], hits)
    hits = search_tags(keyword, category=None, limit=limit)
    return (hits[0]["tag"] if hits else None, hits)


if __name__ == "__main__":
    import sys

    tag = " ".join(sys.argv[1:]).strip() or "firefly_(honkai:_star_rail)"
    print("=" * 72)
    print(f"测试标签：{tag}")
    print("\n[1] 本地标签总表（离线校验 + 真实投稿数）")
    try:
        download_tag_index()
        print("  tag_info:", json.dumps(tag_info(tag), ensure_ascii=False))
        print(
            "  拼写纠错 suggest('firefly', character):",
            json.dumps(suggest_canonical_tag("firefly"), ensure_ascii=False)[:300],
        )
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
            head = httpx.get(
                posts[0]["file_url"], headers=HEADERS, timeout=30, follow_redirects=True
            )
            print(
                f"  首图可下载：HTTP {head.status_code}, {len(head.content) / 1024:.0f} KB, {head.headers.get('content-type')}"
            )
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
_first_dates = {}
