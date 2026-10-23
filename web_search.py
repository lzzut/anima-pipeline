# -*- coding: utf-8 -*-
"""
web_search.py — 客户端联网搜索 / 抓页模块（供 pipeline_character.py 以 function tool 方式调用）

【为什么需要这个模块】
DeepSeek 官方 API 的 Responses 接口「静默忽略」内置工具：
    tools=[{"type": "web_search"}] / tool_choice=...   →  官方文档 Tools 表格：Ignored
也就是说，服务端永远不会真的联网，output 里永远没有 web_search_call。
（实测：output items 只有 ['reasoning']，web_search_call 次数 = 0）

正确做法：把联网能力做成 **function tool**（DeepSeek 完整支持 function 类型），
由模型发起 function_call，Python 端本地执行搜索，再把 function_call_output 回填。
本模块就是那个"本地执行"的部分。

后端（全部免密钥，实测可用）：
  * Bing  RSS   https://cn.bing.com/search?q=...&format=rss   ← 主引擎，返回干净的 XML，含长摘要
  * Bing  HTML  b_algo 解析                                   ← RSS 为空时回退
  * 360   HTML  https://www.so.com/s                          ← 副引擎，中文同人向结果更丰富
  * Tavily API  仅在设置了环境变量 TAVILY_API_KEY 时启用       ← 可选，质量升级路径

用法：
    from web_search import search, fetch_page, WEB_SEARCH_TOOL, WEB_FETCH_TOOL
    data = search("流萤 泳装 同人图")
    print(data["results"][0]["title"])

命令行自测：
    python web_search.py 流萤 泳装 同人图
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse

import httpx

# ===========================================================================
# 配置
# ===========================================================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
}

REQUEST_TIMEOUT = 20.0
ENGINE_RETRIES = 2          # 单个引擎失败重试次数
RETRY_DELAY = 1.2           # 重试间隔（秒）
MIN_REQUEST_INTERVAL = 0.4  # 引擎间最小请求间隔，避免被限流

DEFAULT_MAX_RESULTS = 6
MAX_PER_DOMAIN = 2          # 同一域名最多保留几条，避免结果被百科站刷屏
SNIPPET_LIMIT = 400
PAGE_TEXT_LIMIT = 6000

BING_RSS_URL = "https://cn.bing.com/search"
BING_HTML_URL = "https://cn.bing.com/search"
SO360_URL = "https://www.so.com/s"

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
TAVILY_URL = "https://api.tavily.com/search"

_last_request_ts = 0.0
_cache = {}   # {(query, max_results): result}


# ===========================================================================
# 小工具
# ===========================================================================
def _throttle():
    global _last_request_ts
    wait = MIN_REQUEST_INTERVAL - (time.time() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.time()


def _clean_text(s, limit=None):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\u200b", "").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _xml_field(block, tag):
    """从 RSS item 里取字段，兼容 CDATA。"""
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S | re.I)
    if not m:
        return ""
    val = m.group(1).strip()
    cd = re.match(r"^<!\[CDATA\[(.*?)\]\]>$", val, re.S)
    if cd:
        val = cd.group(1).strip()
    return html.unescape(_clean_text(val))


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    return url.split("#")[0].rstrip("/")


def _domain(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _get(url, params=None, headers=None, timeout=REQUEST_TIMEOUT):
    """带重试的 GET，返回 Response 或抛异常。"""
    last_error = None
    for attempt in range(ENGINE_RETRIES):
        _throttle()
        try:
            resp = httpx.get(url, params=params, headers=headers or HEADERS,
                             timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if attempt < ENGINE_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
    raise last_error


# ===========================================================================
# 引擎 1：Bing RSS（主）
# ===========================================================================
def _search_bing_rss(query, limit):
    resp = _get(BING_RSS_URL, params={
        "q": query,
        "format": "rss",
        "count": str(max(limit, 10)),
    })
    if "<item" not in resp.text:
        raise ValueError("Bing RSS 未返回条目")
    # 防缓存污染：Bing RSS 的 <title> 是「必应：<查询词>」，
    # 若回显与查询词不符，说明拿到了脏缓存/无关结果，直接判失败交给回退引擎
    head = re.search(r"<title>(.*?)</title>", resp.text, re.S)
    if head:
        needle = re.sub(r"\s+", "", query).lower()[:8]
        hay = re.sub(r"\s+", "", html.unescape(head.group(1))).lower()
        if needle and needle not in hay:
            raise ValueError(f"Bing RSS 结果与查询不匹配（回显={head.group(1)[:40]!r}）")
    items = re.findall(r"<item>(.*?)</item>", resp.text, re.S)
    results = []
    for item in items:
        url = _normalize_url(_xml_field(item, "link"))
        if not url:
            continue
        results.append({
            "title": _xml_field(item, "title")[:160],
            "url": url,
            "snippet": _xml_field(item, "description")[:SNIPPET_LIMIT],
        })
    return results


# ===========================================================================
# 引擎 2：Bing HTML（回退）
# ===========================================================================
def _search_bing_html(query, limit):
    resp = _get(BING_HTML_URL, params={"q": query, "count": str(max(limit, 10))},
                headers={**HEADERS, "Accept": "text/html,*/*"})
    results = []
    for block in re.findall(r'<li class="b_algo".*?</li>', resp.text, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = _normalize_url(m.group(1))
        if not url or not url.startswith("http"):
            continue
        snippet = ""
        for pat in (r'<p[^>]*>(.*?)</p>', r'<div class="b_caption".*?>(.*?)</div>'):
            sm = re.search(pat, block, re.S)
            if sm:
                snippet = _clean_text(sm.group(1), SNIPPET_LIMIT)
                if snippet:
                    break
        results.append({
            "title": _clean_text(m.group(2), 160),
            "url": url,
            "snippet": snippet,
        })
    if not results:
        raise ValueError("Bing HTML 未解析到结果")
    return results


# ===========================================================================
# 引擎 3：360 搜索（副，中文同人向结果较多）
# ===========================================================================
def _search_360(query, limit):
    resp = _get(SO360_URL, params={"q": query, "pn": "1"})
    results = []
    blocks = re.findall(r'<li class="res-list.*?</li>', resp.text, re.S)
    if not blocks:
        blocks = re.findall(r'<li[^>]+class="[^"]*res-list[^"]*".*?</li>', resp.text, re.S)
    for block in blocks:
        m = re.search(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            m = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = _normalize_url(m.group(1))
        if not url.startswith("http"):
            continue
        title = _clean_text(m.group(2), 160)
        if not title or "其他人还搜" in title:
            continue
        snippet = ""
        sm = re.search(r'<p[^>]*class="[^"]*res-desc[^"]*"[^>]*>(.*?)</p>', block, re.S)
        if not sm:
            sm = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        if sm:
            snippet = _clean_text(sm.group(1), SNIPPET_LIMIT)
        results.append({"title": title, "url": url, "snippet": snippet})
    if not results:
        raise ValueError("360 搜索未解析到结果")
    return results


# ===========================================================================
# 引擎 4：Tavily（可选，需 TAVILY_API_KEY）
# ===========================================================================
def _search_tavily(query, limit):
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": max(limit, 5),
        "search_depth": "basic",
        "include_answer": False,
    }
    _throttle()
    resp = httpx.post(TAVILY_URL, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [{
        "title": (r.get("title") or "")[:160],
        "url": _normalize_url(r.get("url", "")),
        "snippet": _clean_text(r.get("content", ""), SNIPPET_LIMIT),
    } for r in data.get("results", []) if r.get("url")]


# ===========================================================================
# 对外：search
# ===========================================================================
def available_engines():
    names = ["bing-rss", "bing-html", "so360"]
    if TAVILY_API_KEY:
        names.insert(0, "tavily")
    return names


def _merge(results, limit):
    """按 URL 去重 + 同域名限流，保留顺序。"""
    seen_urls = set()
    seen_domains = {}
    merged = []
    for r in results:
        url = r.get("url", "")
        key = _normalize_url(url).lower()
        if not key or key in seen_urls:
            continue
        dom = _domain(url)
        if dom and seen_domains.get(dom, 0) >= MAX_PER_DOMAIN:
            continue
        seen_urls.add(key)
        if dom:
            seen_domains[dom] = seen_domains.get(dom, 0) + 1
        merged.append(r)
        if len(merged) >= limit:
            break
    return merged


def search(query, max_results=DEFAULT_MAX_RESULTS, use_cache=True):
    """
    联网搜索。返回：
      {"query":..., "engines":[...], "results":[{title,url,snippet,source}], "errors":[...]}
    全部引擎失败时抛 RuntimeError。
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("搜索关键词为空")

    cache_key = (query, max_results)
    if use_cache and cache_key in _cache:
        return _cache[cache_key]

    collected, errors, used = [], [], []

    # 顺序：先跑主引擎，凑够原料（去重/同域名限流后仍能留满）就停，正常只打 1-2 个请求
    plan = []
    if TAVILY_API_KEY:
        plan.append(("tavily", _search_tavily))      # 质量最好，配了 Key 就优先用
    plan.append(("bing-rss", _search_bing_rss))      # 主引擎：RSS，摘要干净
    plan.append(("so360", _search_360))              # 副引擎：中文同人向结果更多
    plan.append(("bing-html", _search_bing_html))    # 回退：RSS 被限流时用

    RAW_ENOUGH = max(max_results * 2, 10)            # 原始命中足够多就不再打下一个引擎

    for name, fn in plan:
        if len(collected) >= RAW_ENOUGH:
            break
        try:
            part = fn(query, max_results) or []
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if part:
            used.append(name)
            for r in part:
                r["source"] = name
                collected.append(r)

    merged = _merge(collected, max_results)
    if not merged:
        raise RuntimeError(
            "所有搜索引擎均未返回结果；" + ("；".join(errors) if errors else "无错误信息")
        )

    result = {
        "query": query,
        "engines": used,
        "results": merged,
    }
    if errors:
        result["errors"] = errors
    if use_cache:
        _cache[cache_key] = result
    return result


# ===========================================================================
# 对外：fetch_page（抓取网页正文，可选）
# ===========================================================================
def fetch_page(url, max_chars=PAGE_TEXT_LIMIT):
    """
    抓取网页正文纯文本。返回 {"url":..., "ok":bool, "text"/"error":...}
    注意：实测 moegirl / 百度百科 有 Cloudflare/安全验证（403），Pixiv 超时；
    因此该能力默认关闭（pipeline 里 WEB_FETCH_ENABLED=False）。
    """
    url = _normalize_url(url)
    if not url.startswith("http"):
        return {"url": url, "ok": False, "error": "非法 URL"}
    try:
        resp = _get(url, headers={**HEADERS, "Accept": "text/html,*/*"})
    except Exception as e:
        return {"url": url, "ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}

    text = resp.text
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer",
                         "header", "form", "aside"]):
            tag.decompose()
        body = soup.body or soup
        text = body.get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) < 80:
        return {"url": url, "ok": False,
                "error": f"正文过短（{len(text)} 字符），可能被反爬拦截"}
    return {"url": url, "ok": True, "text": text[:max_chars],
            "truncated": len(text) > max_chars}


# ===========================================================================
# function tool 定义（交给模型调用）
# ===========================================================================
WEB_SEARCH_TOOL = {
    "type": "function",
    "name": "web_search",
    "description": (
        "联网搜索网页，返回若干条 {title, url, snippet}。"
        "用于查询动漫/二游角色的官方设定（发色、瞳色、标志性特征）、"
        "Danbooru/Pixiv 标签的正确写法、以及某换装主题同人图中实际的服装与场景。"
        "关键词务必用中文（可带日文名），例如「流萤 泳装 同人图」「流萤 danbooru 标签」。"
        "注意：本机走中文区 Bing，**不要只搜单个中文词**（会返回字典页）。"
        "优先用「角色中文名 + 作品 + wiki/fandom」，或者「英文角色标签 + site:fandom.com」；"
        "拿到 fandom / wiki 的链接后，必须用 web_fetch 读正文，不要只看摘要。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，2-4 个词最佳，不要写成一整句话",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}

WEB_FETCH_TOOL = {
    "type": "function",
    "name": "web_fetch",
    "description": "抓取指定网页的正文纯文本，用于深入阅读某个搜索结果页。",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的完整 http(s) 链接"}
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    "strict": True,
}


# ===========================================================================
# 工具分发
# ===========================================================================
def execute_tool(name, arguments, max_results=DEFAULT_MAX_RESULTS):
    """
    本地执行模型发起的工具调用，返回 (输出字符串, 搜索次数, 抓页次数)。
    输出字符串会被原样放进 function_call_output。
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except Exception:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}

    if name == "web_search":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return json.dumps({"error": "query 不能为空"}, ensure_ascii=False), 0, 0
        try:
            data = search(query, max_results=max_results)
        except Exception as e:
            return json.dumps({"error": f"搜索失败：{type(e).__name__}: {e}"},
                              ensure_ascii=False), 1, 0
        return json.dumps(data, ensure_ascii=False), 1, 0

    if name == "web_fetch":
        url = str(arguments.get("url", "")).strip()
        if not url:
            return json.dumps({"error": "url 不能为空"}, ensure_ascii=False), 0, 0
        try:
            data = fetch_page(url)
        except Exception as e:
            return json.dumps({"error": f"抓页失败：{type(e).__name__}: {e}"},
                              ensure_ascii=False), 0, 1
        return json.dumps(data, ensure_ascii=False), 0, 1

    return json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False), 0, 0


# ===========================================================================
# 命令行自测
# ===========================================================================
if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or "流萤 泳装 同人图"
    print(f"引擎：{available_engines()}")
    try:
        out = search(q)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}")
        sys.exit(1)
    print(f"查询：{out['query']}  命中 {len(out['results'])} 条  "
          f"引擎：{'/'.join(out['engines'])}")
    if out.get("errors"):
        print(f"（部分引擎报错：{out['errors']}）")
    for i, r in enumerate(out["results"], 1):
        print(f"\n{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:180]}")
