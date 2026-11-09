"""
web_search.py — 客户端联网搜索 / 抓页模块（供 pipeline_character.py 以 function tool 方式调用）

【现在的联网方式】
DeepSeek 已提供独立的 Search / Fetch 接口：
  POST /v1/tools/search
  POST /v1/tools/fetch
本模块把它们作为 function tool 的后端，由模型发起 function_call，Python 端执行，
再把结果回填给模型。Search 返回的 summary 足够时，不再额外 Fetch。

优先级：
  1. DeepSeek Search / Fetch（若配置了 DEEPSEEK_API_KEY）
  2. Bing RSS / Bing HTML / 360（本地免密钥回退）
  3. Tavily API（仅在设置 TAVILY_API_KEY 时启用）

计费：Search / Fetch 按成功请求计费，¥5 / 1000 次（¥0.005/次），
2026-11-01 00:00（北京时间）开始。可通过 DEEPSEEK_WEB_BUDGET_CNY 限预算。
所有成功调用和预估费用会写入本次运行目录的 web_usage.json。

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

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
}
REQUEST_TIMEOUT = 20.0
ENGINE_RETRIES = 2
RETRY_DELAY = 1.2
MIN_REQUEST_INTERVAL = 0.4
DEFAULT_MAX_RESULTS = 6
MAX_PER_DOMAIN = 2
SNIPPET_LIMIT = 400
PAGE_TEXT_LIMIT = 6000
BING_RSS_URL = "https://cn.bing.com/search"
BING_HTML_URL = "https://cn.bing.com/search"
SO360_URL = "https://www.so.com/s"
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
TAVILY_URL = "https://api.tavily.com/search"
_last_request_ts = 0.0
_cache = {}
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_SEARCH_URL = DEEPSEEK_BASE_URL + "/v1/tools/search"
DEEPSEEK_FETCH_URL = DEEPSEEK_BASE_URL + "/v1/tools/fetch"
DEEPSEEK_WEB_TOOLS = os.environ.get("DEEPSEEK_WEB_TOOLS", "1").strip().lower() not in (
    "0",
    "false",
    "off",
    "no",
)
DEEPSEEK_SEARCH_CONTENT = os.environ.get("DEEPSEEK_SEARCH_CONTENT", "0").strip().lower() in (
    "1",
    "true",
    "on",
    "yes",
)
WEB_TOOL_TIMEOUT = float(os.environ.get("DEEPSEEK_WEB_TIMEOUT", "30"))
WEB_TOOL_UNIT_CNY = 0.005
WEB_TOOL_BUDGET_CNY = float(os.environ.get("DEEPSEEK_WEB_BUDGET_CNY", "0.20"))
WEB_TOOL_BILLING_START = "2026-11-01T00:00:00+08:00"
_web_stats = {
    "search_requests": 0,
    "search_success": 0,
    "fetch_requests": 0,
    "fetch_success": 0,
    "local_search_success": 0,
    "local_fetch_success": 0,
    "errors": [],
}


def web_usage_summary():
    """本次进程内 DeepSeek Search/Fetch 的成功调用与预估费用。"""
    paid = _web_stats["search_success"] + _web_stats["fetch_success"]
    return {
        "enabled": bool(DEEPSEEK_WEB_TOOLS and DEEPSEEK_API_KEY),
        "search_requests": _web_stats["search_requests"],
        "search_success": _web_stats["search_success"],
        "fetch_requests": _web_stats["fetch_requests"],
        "fetch_success": _web_stats["fetch_success"],
        "local_search_success": _web_stats["local_search_success"],
        "local_fetch_success": _web_stats["local_fetch_success"],
        "estimated_cny": round(paid * WEB_TOOL_UNIT_CNY, 4),
        "unit_cny": WEB_TOOL_UNIT_CNY,
        "budget_cny": WEB_TOOL_BUDGET_CNY,
        "billing_start": WEB_TOOL_BILLING_START,
        "errors": list(_web_stats["errors"][-10:]),
        "note": "Only successful Search/Fetch requests are billable; before 2026-11-01 00:00 +08:00 they are free.",
    }


def _deepseek_enabled():
    return bool(DEEPSEEK_WEB_TOOLS and DEEPSEEK_API_KEY)


def _web_budget_left():
    paid = _web_stats["search_success"] + _web_stats["fetch_success"]
    return paid * WEB_TOOL_UNIT_CNY < WEB_TOOL_BUDGET_CNY


def _deepseek_post(url, payload):
    headers = {"Authorization": "Bearer " + DEEPSEEK_API_KEY, "Content-Type": "application/json"}
    last = None
    attempts = 2
    for attempt in range(attempts):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=WEB_TOOL_TIMEOUT)
            if r.status_code in (408, 429) or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                detail = r.text[:160].replace("\n", " ")
                raise RuntimeError(f"HTTP {r.status_code}: {detail}")
            return r.json()
        except httpx.RequestError as e:
            last = f"{type(e).__name__}: {str(e)[:100]}"
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DeepSeek web tool failed: {last}")


def _deepseek_search(query, limit, need_content=None):
    if not _deepseek_enabled():
        return None
    if not _web_budget_left():
        _web_stats["errors"].append("search: 本次运行 web 预算已用尽，回退本地引擎")
        return None
    _web_stats["search_requests"] += 1
    data = _deepseek_post(
        DEEPSEEK_SEARCH_URL,
        {
            "query": query[:128],
            "count": max(1, min(int(limit), 50)),
            "ori_question": query[:128],
            "need_content": DEEPSEEK_SEARCH_CONTENT if need_content is None else bool(need_content),
        },
    )
    rows = data.get("results") or []
    if not rows:
        return None
    _web_stats["search_success"] += 1
    out = []
    for r in rows:
        url = _normalize_url(r.get("url", ""))
        if not url:
            continue
        summary = _clean_text(r.get("summary") or "", 800)
        snippet = _clean_text(r.get("snippet") or "", SNIPPET_LIMIT)
        title = re.sub("\\s*-\\s*Skip to content\\s*$", "", r.get("title") or "", flags=re.I)
        content = str(r.get("content") or "").strip()
        out.append(
            {
                "title": title[:160],
                "url": url,
                "snippet": snippet or summary,
                "summary": summary,
                "content": content[:PAGE_TEXT_LIMIT],
                "content_truncated": len(content) > PAGE_TEXT_LIMIT,
                "date": r.get("date"),
                "modified_at": r.get("modified_at") or r.get("updated_at"),
                "authority": r.get("authority"),
                "rerank_score": r.get("rerank_score"),
                "source": "deepseek-search",
            }
        )
    return out or None


def _deepseek_fetch(url, max_chars):
    if not _deepseek_enabled():
        return None
    if not _web_budget_left():
        _web_stats["errors"].append("fetch: 本次运行 web 预算已用尽，回退本地抓取")
        return None
    _web_stats["fetch_requests"] += 1
    data = _deepseek_post(DEEPSEEK_FETCH_URL, {"url": url})
    content = (data.get("content") or "").strip()
    if not content:
        return None
    _web_stats["fetch_success"] += 1
    return {
        "url": url,
        "ok": True,
        "title": (data.get("title") or "")[:200],
        "text": content[:max_chars],
        "truncated": len(content) > max_chars,
        "source": "deepseek-fetch",
        "modified_at": data.get("modified_at") or data.get("updated_at"),
        "published_date": data.get("published_date"),
    }


def _throttle():
    global _last_request_ts
    wait = MIN_REQUEST_INTERVAL - (time.time() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.time()


def _clean_text(s, limit=None):
    if not s:
        return ""
    s = re.sub("<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\u200b", "").replace("\xa0", " ")
    s = re.sub("\\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _xml_field(block, tag):
    """从 RSS item 里取字段，兼容 CDATA。"""
    m = re.search(f"<{tag}[^>]*>(.*?)</{tag}>", block, re.S | re.I)
    if not m:
        return ""
    val = m.group(1).strip()
    cd = re.match("^<!\\[CDATA\\[(.*?)\\]\\]>$", val, re.S)
    if cd:
        val = cd.group(1).strip()
    return html.unescape(_clean_text(val))


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    try:
        p = urllib.parse.urlsplit(url)
        drop = {"sh", "m", "fbclid", "gclid", "ref", "source", "spm"}
        q = [
            (k, v)
            for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in drop
        ]
        clean = urllib.parse.urlunsplit(
            (p.scheme, p.netloc, p.path or "/", urllib.parse.urlencode(q), "")
        )
        return clean.rstrip("/")
    except Exception:
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
            resp = httpx.get(
                url,
                params=params,
                headers=headers or HEADERS,
                timeout=timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if attempt < ENGINE_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
    raise last_error


def _search_bing_rss(query, limit):
    resp = _get(BING_RSS_URL, params={"q": query, "format": "rss", "count": str(max(limit, 10))})
    if "<item" not in resp.text:
        raise ValueError("Bing RSS 未返回条目")
    head = re.search("<title>(.*?)</title>", resp.text, re.S)
    if head:
        needle = re.sub("\\s+", "", query).lower()[:8]
        hay = re.sub("\\s+", "", html.unescape(head.group(1))).lower()
        if needle and needle not in hay:
            raise ValueError(f"Bing RSS 结果与查询不匹配（回显={head.group(1)[:40]!r}）")
    items = re.findall("<item>(.*?)</item>", resp.text, re.S)
    results = []
    for item in items:
        url = _normalize_url(_xml_field(item, "link"))
        if not url:
            continue
        results.append(
            {
                "title": _xml_field(item, "title")[:160],
                "url": url,
                "snippet": _xml_field(item, "description")[:SNIPPET_LIMIT],
            }
        )
    return results


def _search_bing_html(query, limit):
    resp = _get(
        BING_HTML_URL,
        params={"q": query, "count": str(max(limit, 10))},
        headers={**HEADERS, "Accept": "text/html,*/*"},
    )
    results = []
    for block in re.findall('<li class="b_algo".*?</li>', resp.text, re.S):
        m = re.search('<h2[^>]*>\\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = _normalize_url(m.group(1))
        if not url or not url.startswith("http"):
            continue
        snippet = ""
        for pat in ("<p[^>]*>(.*?)</p>", '<div class="b_caption".*?>(.*?)</div>'):
            sm = re.search(pat, block, re.S)
            if sm:
                snippet = _clean_text(sm.group(1), SNIPPET_LIMIT)
                if snippet:
                    break
        results.append({"title": _clean_text(m.group(2), 160), "url": url, "snippet": snippet})
    if not results:
        raise ValueError("Bing HTML 未解析到结果")
    return results


def _search_360(query, limit):
    resp = _get(SO360_URL, params={"q": query, "pn": "1"})
    results = []
    blocks = re.findall('<li class="res-list.*?</li>', resp.text, re.S)
    if not blocks:
        blocks = re.findall('<li[^>]+class="[^"]*res-list[^"]*".*?</li>', resp.text, re.S)
    for block in blocks:
        m = re.search('<h3[^>]*>\\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            m = re.search('<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = _normalize_url(m.group(1))
        if not url.startswith("http"):
            continue
        title = _clean_text(m.group(2), 160)
        if not title or "其他人还搜" in title:
            continue
        snippet = ""
        sm = re.search('<p[^>]*class="[^"]*res-desc[^"]*"[^>]*>(.*?)</p>', block, re.S)
        if not sm:
            sm = re.search("<p[^>]*>(.*?)</p>", block, re.S)
        if sm:
            snippet = _clean_text(sm.group(1), SNIPPET_LIMIT)
        results.append({"title": title, "url": url, "snippet": snippet})
    if not results:
        raise ValueError("360 搜索未解析到结果")
    return results


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
    return [
        {
            "title": (r.get("title") or "")[:160],
            "url": _normalize_url(r.get("url", "")),
            "snippet": _clean_text(r.get("content", ""), SNIPPET_LIMIT),
        }
        for r in data.get("results", [])
        if r.get("url")
    ]


def available_engines():
    names = ["bing-rss", "bing-html", "so360"]
    if TAVILY_API_KEY:
        names.insert(0, "tavily")
    if _deepseek_enabled():
        names.insert(0, "deepseek-search")
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


def search(query, max_results=DEFAULT_MAX_RESULTS, use_cache=True, *, need_content=None):
    """
    联网搜索。返回：
      {"query":..., "engines":[...], "results":[{title,url,snippet,source}], "errors":[...]}
    全部引擎失败时抛 RuntimeError。
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("搜索关键词为空")
    content_requested = DEEPSEEK_SEARCH_CONTENT if need_content is None else bool(need_content)
    cache_key = (query, max_results, content_requested)
    if use_cache and cache_key in _cache:
        return _cache[cache_key]
    collected, errors, used = ([], [], [])
    if _deepseek_enabled():
        try:
            part = _deepseek_search(query, max_results, need_content=content_requested)
            if part:
                merged = _merge(part, max_results)
                if merged:
                    result = {"query": query, "engines": ["deepseek-search"], "results": merged}
                    if use_cache:
                        _cache[cache_key] = result
                    return result
                errors.append("deepseek-search: 结果去重后为空")
            else:
                errors.append("deepseek-search: 无结果")
        except Exception as e:
            errors.append(f"deepseek-search: {type(e).__name__}: {str(e)[:100]}")
            _web_stats["errors"].append(errors[-1])
    plan = []
    if TAVILY_API_KEY:
        plan.append(("tavily", _search_tavily))
    plan.append(("bing-rss", _search_bing_rss))
    plan.append(("so360", _search_360))
    plan.append(("bing-html", _search_bing_html))
    RAW_ENOUGH = max(max_results * 2, 10)
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
    _web_stats["local_search_success"] += 1
    result = {"query": query, "engines": used, "results": merged}
    if errors:
        result["errors"] = errors
    if use_cache:
        _cache[cache_key] = result
    return result


def fetch_page(url, max_chars=PAGE_TEXT_LIMIT):
    """
    抓取网页正文纯文本。返回 {"url":..., "ok":bool, "text"/"error":...}
    注意：Fandom / 部分百科站可能 403/404，Pixiv 可能超时；
    这类明确拒绝会快速返回，不再本地重试；优先使用 Search 的 summary。
    """
    url = _normalize_url(url)
    if not url.startswith("http"):
        return {"url": url, "ok": False, "error": "非法 URL"}
    if _deepseek_enabled():
        try:
            data = _deepseek_fetch(url, max_chars)
            if data:
                return data
            _web_stats["errors"].append("fetch: DeepSeek 无正文，回退本地")
        except Exception as e:
            msg = f"fetch: {type(e).__name__}: {str(e)[:140]}"
            _web_stats["errors"].append(msg)
            if "HTTP 403" in str(e) or "HTTP 404" in str(e):
                return {"url": url, "ok": False, "error": msg, "source": "deepseek-fetch"}
    try:
        resp = _get(url, headers={**HEADERS, "Accept": "text/html,*/*"})
    except Exception as e:
        return {"url": url, "ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
    text = resp.text
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "lxml")
        for tag in soup(
            ["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"]
        ):
            tag.decompose()
        body = soup.body or soup
        text = body.get_text(" ", strip=True)
    except Exception:
        text = re.sub("<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub("<[^>]+>", " ", text)
        text = html.unescape(text)
    text = re.sub("\\s+", " ", text).strip()
    if len(text) < 80:
        return {"url": url, "ok": False, "error": f"正文过短（{len(text)} 字符），可能被反爬拦截"}
    _web_stats["local_fetch_success"] += 1
    return {
        "url": url,
        "ok": True,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "source": "local-fetch",
    }


WEB_SEARCH_TOOL = {
    "type": "function",
    "name": "web_search",
    "description": (
        "联网搜索网页，返回 {title, url, snippet, summary, authority, date}。用于查询动漫/二游角色的官方设定（发色、瞳色、标志性特征）、Danbooru "
        "标签的正确写法、以及某换装主题同人图中实际的服装与场景。优先使用 DeepSeek 自研搜索；支持 site:、lang:、after:、before: 等语法。一次只搜一个精确 "
        "query，不要连续重复搜索；优先「角色名 + 作品 + site:fandom.com」或「角色名 + site:zh.wikipedia.org」。如果 summary 已经足够回答，不要为了同一信息再调用"
        " web_fetch；只有确实需要正文细节时才 fetch。每次成功 search/fetch 都会产生一次调用费用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，2-4 个词最佳，不要写成一整句话"}
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}
WEB_FETCH_TOOL = {
    "type": "function",
    "name": "web_fetch",
    "description": (
        "抓取指定网页正文（Markdown）。角色性格、眉眼和标志特征应读取角色介绍或台词正文，摘要够用的一般资料可以省略抓取；不要对同一页面重复抓取。Fandom / 部分百科站可能返回 "
        "403/404，遇到失败就改用 search 的 summary，不要反复换 URL 抓同一内容。每次成功 fetch 都会产生一次调用费用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "要抓取的完整 http(s) 链接"}},
        "required": ["url"],
        "additionalProperties": False,
    },
    "strict": True,
}


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
            return (json.dumps({"error": "query 不能为空"}, ensure_ascii=False), 0, 0)
        try:
            data = search(query, max_results=max_results)
        except Exception as e:
            return (
                json.dumps({"error": f"搜索失败：{type(e).__name__}: {e}"}, ensure_ascii=False),
                1,
                0,
            )
        return (json.dumps(data, ensure_ascii=False), 1, 0)
    if name == "web_fetch":
        url = str(arguments.get("url", "")).strip()
        if not url:
            return (json.dumps({"error": "url 不能为空"}, ensure_ascii=False), 0, 0)
        try:
            data = fetch_page(url)
        except Exception as e:
            return (
                json.dumps({"error": f"抓页失败：{type(e).__name__}: {e}"}, ensure_ascii=False),
                0,
                1,
            )
        return (json.dumps(data, ensure_ascii=False), 0, 1)
    return (json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False), 0, 0)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or "流萤 泳装 同人图"
    print(f"引擎：{available_engines()}")
    try:
        out = search(q)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}")
        sys.exit(1)
    print(f"查询：{out['query']}  命中 {len(out['results'])} 条  引擎：{'/'.join(out['engines'])}")
    if out.get("errors"):
        print(f"（部分引擎报错：{out['errors']}）")
    for i, r in enumerate(out["results"], 1):
        print(f"\n{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:180]}")
