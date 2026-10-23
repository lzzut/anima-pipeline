# body_judge.py —— 用 VLM 判定"该角色是否为儿童/萝莉体型"（用户方案 A）
#   流程：booru 抽该角色 3 张参考图 → 逐张问 VLM"图中人物是否为儿童体型" → 多数判定
#   缓存：body_verdicts.json（同一角色只判一次，避免重复花费）
import base64
import io
import json
import os

import httpx
from PIL import Image

import booru_client as bc
import config as C

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "body_verdicts.json")
SAMPLES = 3
RUBRIC = (
    "这些是同一位动漫角色的同人图。请判断该角色的体型/外观是否属于**儿童**"
    "（childlike：儿童体型比例、明显是小孩子、小学生体型、loli 体型）。\n"
    "判定要点：头身比偏大（头大身短）、四肢短小、胸/腰等第二性征未发育、脸型圆幼。\n"
    "若角色是青少年或成年人（即使身高偏矮、画风可爱）→ childlike=false。\n"
    '只回一个 JSON：{"childlike": true 或 false, "confidence": 0~1, "reason": "不超过 20 字"}'
)


def _cache():
    try:
        with open(CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _ask(img_bytes):
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im.thumbnail((512, 512))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    r = httpx.post((C.DEEPSEEK_BASE_URL or "").rstrip("/") + "/chat/completions",
                   headers={"Authorization": "Bearer " + C.DEEPSEEK_API_KEY,
                            "Content-Type": "application/json"},
                   json={"model": C.DEEPSEEK_MODEL,
                         "max_tokens": getattr(C, "LIMB_JUDGE_MAX_TOKENS", 4500),
                         "messages": [{"role": "user", "content": [
                             {"type": "text", "text": RUBRIC},
                             {"type": "image_url",
                              "image_url": {"url": "data:image/png;base64," + b64}}]}]},
                   timeout=180)
    if r.status_code != 200:
        return None
    body = r.json()
    try:
        msg = body["choices"][0]["message"]
    except Exception:
        return None
    txt = (msg.get("content") or "") + "\n" + (msg.get("reasoning_content") or "")
    dec = json.JSONDecoder()
    for i, ch in enumerate(txt):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(txt[i:])
            except Exception:
                continue
            if isinstance(obj, dict) and "childlike" in obj:
                return obj
    return None


def judge(name_en, samples=SAMPLES, verbose=True):
    """返回 {"childlike": bool, "votes": "2/3", "reason": str}（并写缓存）"""
    c = _cache()
    key = str(name_en).lower()
    if key in c:
        return c[key]
    posts = []
    try:
        posts = bc.search_posts(name_en, limit=samples + 2) or []
    except Exception:
        posts = []
    res = []
    for p in posts[:samples]:
        u = p.get("file_url") or p.get("preview_url")
        if not u:
            continue
        try:
            r = httpx.get(u, timeout=60, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and r.content:
                v = _ask(r.content)
                if v:
                    res.append(v)
                    if verbose:
                        print("    [体型判定] %s 第%d张 → childlike=%s (%s) %s" % (
                            name_en, len(res), v.get("childlike"), v.get("confidence"),
                            str(v.get("reason"))[:26]))
        except Exception as e:
            if verbose:
                print("    [体型判定] %s 取图失败 %s" % (name_en, type(e).__name__))
    if not res:
        out = {"childlike": None, "votes": "0/0", "reason": "判定失败（放行）"}
    else:
        yes = sum(1 for v in res if v.get("childlike") is True)
        out = {"childlike": yes * 2 > len(res), "votes": "%d/%d" % (yes, len(res)),
               "reason": str((res[0] or {}).get("reason") or "")[:40]}
    c[key] = out
    _save(c)
    return out


if __name__ == "__main__":
    import sys
    for t in (sys.argv[1:] or ["klee_(genshin_impact)", "bailu_(honkai:_star_rail)",
                               "sigewinne_(genshin_impact)", "arima_kana",
                               "raiden_shogun", "hu_tao_(genshin_impact)",
                               "furina_(genshin_impact)"]):
        print("  %-32s → %s" % (t, judge(t)))
