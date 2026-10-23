# pipeline_character.py
import datetime, json, os, random, time
from pool_manager import (
    load_json, save_json, robust_json_parse,
    POOL_FILE, POOL_SIZE,
)
import comfy_runner
import re
from comfy_runner import generate_images, choose_workflow
import config as _cfg
from openai import OpenAI
from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, FALLBACK_NEGATIVE,
    WORKFLOW_POOL, WORKFLOW_MODEL_INFO,
    CHARACTER_GATE_ATTEMPTS, MAX_WORKFLOW_SWAPS,
    CHAR_POP_OLD_YEAR, CHAR_POP_OLD_MIN, CHAR_POP_NEW_MIN, SERIES_MIN_POSTS,
)
from character_gate import accepts, choose_workflow_for
# 联网搜索改为本地 function tool 执行（见 web_search.py 顶部说明）
from web_search import (
    available_engines, execute_tool, WEB_SEARCH_TOOL, WEB_FETCH_TOOL,
)
from ensure_comfyui import ensure_comfyui
from prompt_style import style_directive

# 允许未设置环境变量时也能导入模块；实际调用会明确返回鉴权错误。
client = OpenAI(api_key=DEEPSEEK_API_KEY or "missing", base_url=DEEPSEEK_BASE_URL)


# ===========================================================================
# 可调配置
# ===========================================================================
# 景物/景别：**只有这两个，二选一**（用户设定，不得擅自更改/扩充）
#   "cowboy shot" = 七分身（膝上）    "full body" = 全身
FRAMING_OPTIONS = ["cowboy shot", "full body"]

# 不经过景别判定的工作流（按用户 2026-10-11 要求）：
#   animagine_xl 在 896x1152 竖幅下用 cowboy shot 容易把头顶/发饰切出画面，
#   → 该工作流跳过景别注入，构图交给提示词生成模型自由决定。
# 不经过景别判定的工作流：
#   animagine_xl —— 896x1152 竖幅下用 cowboy shot 紧构图会把头顶/发饰切出画面（实测 2/3）
#   nova_xl      —— 2026-10-11 实测加入：跳过景别 + 强制胸像构图后 3 张全部合格
#                   （脸更大、头顶完整、细节更清楚；分数 3.020/2.841/2.782）
#   两条都改为"不注入景别、由提示词生成模型按要求给出胸像/半身近景构图"
NO_FRAMING_WORKFLOWS = ()

# "眼睛渲染"加强规则的作用域（当前生产线路不启用）
EYE_RENDER_WORKFLOWS = ()

# 提示词自检不合格时最多重新生成的次数（2026-10-11 新增）
PROMPT_SELFCHECK_RETRIES = 1
WEIGHT_FACE = 1.15
WEIGHT_EXPRESSION = 1.2
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "output", "character")
GATE_REJECT_FILE = os.path.join(BASE_DIR, "gate_rejected.json")
WORKFLOW_LABELS = {
    "api": "Anima-2.9B（KSampler 工作流）",
    "anima_flow": "Anima-2.9B（AnimaFlow 采样器工作流）",
}
# 候选张数：Z-Image 约 40s/张、Anima int8 约 79s/张，10 张≈7~13 分钟
CANDIDATE_COUNT = 5     # 2026-10-21 用户：**5 选 1**（配合四肢质检门时筛掉一张补一张，凑够 5）

# ===========================================================================
# 联网搜索配置
#
# 【根因】DeepSeek 官方 API 会「静默忽略」Responses 接口的内置工具。
#   官方文档 Tools 表：function 支持；web_search / file_search /
#   code_interpreter / computer_use / mcp 等 → Ignored（忽略，不报错）。
#   所以 tools=[{"type":"web_search"}] 无论 tool_choice 写 "auto" 还是
#   {"type":"web_search"} 都不会联网：返回的 output 里恒无 web_search_call，
#   模型只能在"以为自己在搜"的幻觉里编内容。
#
# 【修复】联网改由本地 function tool 完成：
#   模型发 function_call → Python 端真的去 Bing/360 搜 → 回填 function_call_output。
#   （实测该闭环可用：第 1 轮返回 ['reasoning','function_call']，
#     第 2 轮返回 ['message'] + 最终 JSON）
# ===========================================================================
WEB_SEARCH_ENABLED = True
WEB_FETCH_ENABLED = True        # 抓页：Fandom/safebooru 可用；百度/萌娘可能 403，失败自动跳过
WEB_SEARCH_MAX_HINT = 3         # 提示词里告诉模型最多搜几次
WEB_SEARCH_MAX_ROUNDS = 3       # 代码层允许的最大搜索轮数（最后一轮强制输出 JSON）
WEB_SEARCH_MAX_RESULTS = 6      # 每次搜索回给模型几条结果
REASONING_EFFORT = "max"        # 思考强度（deepseek-flash 支持 effort）

# 重试配置
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 30.0
RETRY_JITTER = 0.3

DEBUG_RAW_OUTPUT = True

PUBLISH_HASHTAGS = "#AI绘画 #Anima #二次元"
PROMPT_ORDER = "质量 → 人数 → 角色 → 系列 → 外观 → 动作 → 场景 → 光影 → 构图 → 景深"

_FRAMING_LOWER = {f.lower() for f in FRAMING_OPTIONS}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_SEARCH_TAIL = f"最多搜索 {WEB_SEARCH_MAX_HINT} 次后必须基于已有信息输出 JSON。"
_SEARCH_STRATEGY = (
    "搜索策略：将查询拆解为 2-3 个核心关键词进行单次搜索，"
    "避免生成过长的 queries 数组。优先使用单次搜索，"
    "只在信息不足时才追加搜索。"
)
_NO_ARTIST = "禁止在 JSON 中输出任何画师名、@标签或 artists 字段。"
_NO_FRAMING_NEG = "禁止写景别词（cowboy shot / full body 等）"

# 强制 JSON 输出格式（替代 text.format 参数）
_JSON_OUTPUT = (
    "【输出格式 — 极其重要】\n"
    "必须直接返回一个扁平的 JSON 对象，包含所有字段。\n"
    "严禁返回 {\"type\": \"json_object\", \"content\": {...}} 这种嵌套结构。\n"
    "严禁返回解释性文字。\n"
    "第一字符必须是 {，最后字符必须是 }。\n"
)


# ===========================================================================
# 通用工具
# ===========================================================================
def parse_tags(s):
    return [p.strip() for p in s.split(",") if p.strip()] if s else []


def dedup_tags(s):
    seen = set()
    result = []
    for p in parse_tags(s):
        key = p.lower()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return ", ".join(result)


def weight_tags(s, weight=1.2):
    return ", ".join(
        p if (p.startswith("(") and p.endswith(")")) else f"({p}:{weight})"
        for p in parse_tags(s)
    )


def _escape_anima(s: str) -> str:
    return s.replace("_", " ").replace("(", "\\(").replace(")", "\\)")


def _collapse_double_escape(text):
    """SDXL：把 `\\\\` 缩回 `\\`。

    2026-10-21 用户选 3：ComfyUI 的 escape_important 只吃一个反斜杠，多出来的
    那个会作为字面 `\\` 进入 CLIP token。这里只做字符串归一，不改变权重语义。
    """
    return str(text or "").replace(chr(92) * 2, chr(92))


def build_negative(structured_negative):
    base = structured_negative.strip() if structured_negative else FALLBACK_NEGATIVE
    seen = set()
    result = []
    for p in parse_tags(base):
        key = p.lower()
        if key in _FRAMING_LOWER:
            continue
        if key not in seen:
            seen.add(key)
            result.append(p)
    return ", ".join(result)


def _apply_outfit_swap(structured, theme, name_en, workflow, season=None):
    """换装主题：剥离官方服装 + 物理互斥覆盖 + 服装加权 + 官方服装负面。

    2026-10-21 用户：从四季块里独立出来（原来嵌在 `if _sg2` 里）——
      ① 非四季的换装主题（和服/婚纱/制服…）也要剥离/加权；
      ② 必须在「当季服装整体覆盖」**之后**执行，否则 `wearing (...:1.5)`
         和 OUTFIT_SWAP_COVER 会被后面那句 `structured["outfit"] = 当季服装` 覆盖掉。
    物理互斥的厚重外套只对秋冬（season in 秋/冬）生效；春夏套羽绒服自相矛盾。
    """
    if not isinstance(structured, dict) or not _cfg.is_outfit_swap_theme(theme):
        return
    _strip = tuple(getattr(_cfg, "OUTFIT_STRIP_CLOTHING", ()) or ())
    _char_strip = (getattr(_cfg, "CHAR_OUTFIT_STRIP", {}) or {}).get(str(name_en), ())
    if _char_strip:
        _strip = _strip + tuple(_char_strip)
        print(f"[换装剥离] {name_en} 追加角色专属剥离词 {len(_char_strip)} 个")
    for _fk in ("core_features", "appearance"):
        _fv = str(structured.get(_fk) or "")
        if not (_fv and _strip):
            continue
        _ls = [x.strip() for x in _fv.split(",") if x.strip()]
        _kept = [x for x in _ls if not any(s in x.lower() for s in _strip)]
        if len(_kept) != len(_ls):
            structured[_fk] = ", ".join(_kept)
            print(f"[换装剥离] {_fk}: 删掉 {len(_ls) - len(_kept)} 个官方服装标签，"
                  f"保留 {len(_kept)} 个（发型/头饰/瞳色不动）")
    _neg_key = ("negative" if "negative" in structured
                else ("negatives" if "negatives" in structured else "negative"))
    _of = str(structured.get("outfit") or "").strip()
    if "tan leather" in _of.lower():
        _of = _of.replace("tan leather", "brown leather")
    _cover = (getattr(_cfg, "OUTFIT_SWAP_COVER", "")
              if season in ("秋", "冬") else "")
    if _of and _cover:
        _of = _of + ", " + _cover
        print("[物理互斥] 追加厚重外套覆盖描述")
    _w = float(getattr(_cfg, "OUTFIT_SWAP_WEIGHT_HARD",
                       getattr(_cfg, "OUTFIT_SWAP_WEIGHT", 1.35)))
    if _of and "wearing (" not in _of:
        structured["outfit"] = "wearing (%s:%.2f)" % (_of, _w)
        print(f"[服装加权] 换装服装（物理互斥）→ {_w}")
    # 眼部负面（只对 EYE_ENHANCE_WORKFLOWS，如 animagine；Anima 已由 format_prompt 关闭）
    _en = (getattr(_cfg, "EYE_NEGATIVE", "")
           if workflow in getattr(_cfg, "EYE_ENHANCE_WORKFLOWS", ("animagine_xl",))
           else "")
    if _en:
        _nv = str(structured.get(_neg_key) or "")
        if "smudged eye" not in _nv.lower():
            structured[_neg_key] = ((_nv + ", ") if _nv else "") + _en
            print("[眼部负面] 已追加防涂抹/防遮眼压制")
    # 官方服装负面（与泳装同机制）
    _on = getattr(_cfg, "OUTFIT_SWAP_NEGATIVE", "")
    if _on:
        _nv2 = str(structured.get(_neg_key) or "")
        if "official costume" not in _nv2.lower():
            structured[_neg_key] = ((_nv2 + ", ") if _nv2 else "") + _on
            print("[官方服装负面] 已把它写进负面（与泳装同机制）")
    # 2026-10-21：服装跑偏负面（秋冬装变羽绒服/毛领）—— 只在秋冬加
    if season in ("秋", "冬"):
        _drift = getattr(_cfg, "OUTFIT_DRIFT_NEGATIVE", "")
        if _drift:
            _nv3 = str(structured.get(_neg_key) or "")
            if "puffer jacket" not in _nv3.lower():
                structured[_neg_key] = ((_nv3 + ", ") if _nv3 else "") + _drift
                print("[服装跑偏负面] 已压制羽绒服/毛领大衣")


def _apply_scene_details(structured, theme, workflow):
    """① 按线路覆盖场景；② 按主题追加真实场景细节。

    2026-10-21 用户：原来读写 `structured["scene"]` —— schema 与模板用的都是
    scene_foreground/midground/background，`scene` 根本没人读 → SCENE_DETAILS 一直无效。
    现在写进模板真正读取的 scene_* 字段；`scene` 只做兜底。
    """
    if not isinstance(structured, dict):
        return
    _sc_keys = ("scene_background", "scene_midground", "scene_foreground", "scene")
    _sc_key = next((k for k in _sc_keys
                    if str(structured.get(k) or "").strip()), "scene_background")
    if _sc_key == "scene":
        structured["scene_background"] = str(structured.get("scene") or "").strip()
        _sc_key = "scene_background"
    # ① 按线路覆盖：有本线场景就替换**背景**（不再要求 `structured["scene"]` 存在）
    _ovl2 = (getattr(_cfg, "SEASONAL_OVERRIDE_BY_LINE", {}) or {}).get(workflow, {})
    _sv = _ovl2.get("scene")
    if _sv:
        import random as _rnd2
        structured["scene_background"] = (_rnd2.choice(_sv)
                                          if isinstance(_sv, (list, tuple)) else _sv)
        _sc_key = "scene_background"
        print(f"[场景覆盖] {workflow}：使用本线场景（不再被覆盖）")
    # ② 主题级场景细节词库（所有主题，治"背景平涂/假"）
    try:
        from config import SCENE_DETAILS as _sd
        _t = str(theme or "")
        for _k, _extra in (_sd or {}).items():
            if _k in _t:
                _cur = str(structured.get(_sc_key) or "").strip()
                structured[_sc_key] = ((_cur + ", ") if _cur else "") + _extra
                print(f"[场景细节] 主题「{_k}」补入真实场景细节 → {_sc_key}")
                break
    except Exception:
        pass


def _assemble_scene(structured):
    layers = (
        ("scene_background", "in the distance"),
        ("scene_midground", "in the middle ground"),
        ("scene_foreground", "close around her"),
    )
    parts = []
    for key, prefix in layers:
        v = structured.get(key, "").strip()
        if v:
            parts.append(f"{prefix}, {v}")
    return ", ".join(parts)




# ---------------------------------------------------------------------------
# 2026-10-20 提示词拼装修复（**仅 Anima 两线**）
#   ① 去重复标签（角色标签保留"转义 + 不转义"双写法）
#   ② 缺角色标签则补（插在 solo 之后，避免被 format_prompt 的 subject 截断）
#   ③ 景别长句 → 短标签（Anima 只吃短 tag）
# 2026-10-21 审计调整：
#   · 随机景别档位改为**显式开关**（ANIMA_FRAMING_TIER），默认不注入
#   · 删除"景别前置重排"（模板已在第 3 位，重排会把 upper body framing 削坏）
#   · 身份签名改为紧跟角色标签；帽类签名在 LLM 已写帽子时跳过（防两顶帽子）
# ---------------------------------------------------------------------------
_FRAME_SHORT = ("cowboy shot", "full body", "upper body", "close-up", "portrait")


def _fix_anima_prompt(positive, name_en, series_en=""):
    try:
        tags = [x.strip() for x in str(positive).split(",") if x.strip()]
        seen, out = set(), []
        # 2026-10-21 审计：给"角色标签双写法"留口子（见下方 ① 去重）
        _char_key = re.sub(r"[^a-z0-9]", "", str(name_en or "").replace("_", " ").lower())
        _char_styles = set()
        for t in tags:
            # 2026-10-20：把多重转义归一（\\\\ → \\ ，再统一去反斜杠比较）
            t = t.replace(chr(92) * 2, chr(92))
            k = t.lower().replace(chr(92), "").replace("  ", " ")
            # ③ 丢掉自然语言长句（景别/构图类）
            if any(w in t.lower() for w in ("rule-of-thirds", "placed on", "within a",
                                            "slightly from below", "intersection")):
                continue
            # ① 去重（转义差异视为同一个）
            if k in seen:
                # 2026-10-21：角色标签的**转义/不转义双写法**是 2026-10-12 有意保留的
                #   识别增强 → 只对这一对放行一次，其余仍按归一 key 去重
                if _char_key and re.sub(r"[^a-z0-9]", "", k) == _char_key:
                    _style = "esc" if chr(92) in t else "plain"
                    if _style not in _char_styles:
                        _char_styles.add(_style)
                        out.append(t)
                continue
            seen.add(k)
            if _char_key and re.sub(r"[^a-z0-9]", "", k) == _char_key:
                _char_styles.add("esc" if chr(92) in t else "plain")
            out.append(t)
        _body_low = ", ".join(out).lower()
        # 身份锚定：插入角色标志物（治"人物不像"，仅 Anima 两线）
        #   2026-10-21 审计：原实现插在 `1girl, solo` 后，随后被 framing/档位/头饰连续
        #   重排，角色名反被推到第 9~10 位 → 改为**紧跟角色标签**插入；比较改为归一后匹配。
        try:
            import config as _c_sig
            for _k, _v in (getattr(_c_sig, "CHAR_SIGNATURE", {}) or {}).items():
                if _k not in _body_low:
                    continue
                _need2 = [x.strip() for x in _v.split(",") if x.strip()]
                _flat = re.sub(r"[^a-z0-9]", "", _body_low)
                _has_hat = bool(re.search(r"\bhat\b", _body_low))
                _miss = []
                for _x in _need2:
                    if re.sub(r"[^a-z0-9]", "", _x.lower()) in _flat:
                        continue
                    # LLM 已写过任一帽子 → 不再叠加"以 hat 结尾"的签名标签（防两顶帽子）
                    if _has_hat and re.search(r"\bhat$", _x.strip().lower()):
                        continue
                    _miss.append(_x)
                if _miss:
                    _char_pos = [_i for _i, _t in enumerate(out)
                                 if _char_key and
                                 re.sub(r"[^a-z0-9]", "",
                                        _t.lower().replace(chr(92), "")) == _char_key]
                    if _char_pos:
                        _idx = _char_pos[0]
                        # 双写法都在时插在**两份之后**，保持它们相邻
                        if len(_char_pos) > 1 and _char_pos[1] - _char_pos[0] <= 1:
                            _idx = _char_pos[1]
                        # 作品标签紧跟角色时，签名插在作品之后（保持 danbooru 顺序）
                        if series_en and _idx + 1 < len(out):
                            _nxt = re.sub(r"[^a-z0-9]", "",
                                          out[_idx + 1].lower().replace(chr(92), ""))
                            _ser = re.sub(r"[^a-z0-9]", "",
                                          str(series_en).replace("_", " ").lower())
                            if _nxt == _ser:
                                _idx += 1
                        out[_idx + 1:_idx + 1] = _miss
                    else:
                        out = _miss + out
                break
        except Exception:
            pass
        # ② 缺角色标签则补（用统一的 Anima 转义；不再二次转义）
        #   2026-10-21：原来插在**最前面**，会被 format_prompt 的 subject 截断整段丢掉
        #   → 改为插在 `solo` 之后。
        if name_en:
            try:
                esc = _escape_anima(name_en)
            except Exception:
                esc = str(name_en)
            _blob = ", ".join(out).lower()
            if esc.lower() not in _blob and str(name_en).lower() not in _blob:
                _i = next((_j for _j, _t in enumerate(out) if _t.strip().lower() == "solo"), None)
                if _i is None:
                    _i = next((_j for _j, _t in enumerate(out) if _t.strip().lower() == "1girl"), None)
                if _i is None:
                    out = [esc] + out
                else:
                    out.insert(_i + 1, esc)
        body = ", ".join(out)
        # ③ 景别无短标签则补 cowboy shot
        #   2026-10-21：插在 `solo` 之后 —— 插到最前面会被 format_prompt 的 subject
        #   截断整段丢掉（与角色标签同一类坑）。
        if not any(f in body.lower() for f in _FRAME_SHORT):
            _m2 = re.search(r"\bsolo\b,?", body, re.I)
            if _m2:
                body = body[:_m2.end()] + " cowboy shot," + body[_m2.end():]
            else:
                body = f"cowboy shot, {body}"
        # ① 景别前置加权 —— **2026-10-21 删除**
        #   模板 build_reference_prompt 已把 framing 放在第 3 位（config.py 的
        #   `parts.insert(2, framing)`），这里再移动一次只会把 `upper body framing`
        #   削成 `framing`，并把身份标签挤到后面。
        # ③ 景别档位：按目标景别选一套标签（Anima 靠身体部位驱动镜头）
        #    五分身 = 大腿以上 / 七分身(cowboy) = 膝盖以上 / 全身
        #   2026-10-21 审计：**默认不注入**（原来 random.choice 会与 pipeline 的 framing、
        #   四季块的 waist-up 姿势三方打架）。只有显式指定档位时才用于 A/B。
        try:
            import re as _re_s
            _low = body.lower()
            _swim = any(k in _low for k in ("swimsuit", "bikini", "leotard", "one-piece"))
            _forced = getattr(__import__("config"), "ANIMA_FRAMING_TIER", None)
            _need = []
            if _forced in ("full", "cowboy", "half") and not _swim:
                if _forced == "full":
                    # 不再注入 "standing"：它会把坐姿/上半身姿势强行改成站立
                    _need = ["full body", "legs visible", "feet visible"]
                    _drop = ("cowboy shot", "thighs visible")
                elif _forced == "half":
                    _need = ["thighs visible", "legs visible"]
                    _drop = ("cowboy shot", "full body", "feet visible", "standing")
                else:
                    _need = ["cowboy shot", "legs visible"]
                    _drop = ("full body", "feet visible", "standing")
                for d in _drop:
                    body = _re_s.sub(r"(?i)" + _re_s.escape(d) + r",?\s*", "", body)
            if _need:
                _m = _re_s.search(r"1girl,\s*solo,?", body, _re_s.I)
                _ins = " ".join([x + "," for x in _need]) + " "
                if _m:
                    body = body[:_m.end()] + _ins + body[_m.end():]
                else:
                    body = ", ".join(_need) + ", " + body
                # 去重复景别标签（只保留插入的那一份）
                _parts = [x.strip() for x in body.split(",") if x.strip()]
                _seen = set()
                _out = []
                for _p in _parts:
                    _k = _p.lower()
                    if _k in ("cowboy shot", "full body", "legs visible", "thighs visible",
                              "feet visible", "standing"):
                        if _k in _seen:
                            continue
                        _seen.add(_k)
                    _out.append(_p)
                body = ", ".join(_out)
        except Exception:
            pass
        # ② 头饰前置加权（保留角色标志头饰，避免被季节服装盖掉）
        #   2026-10-21：原来借用上面"景别前置"块里的 `_re_f`，该块已删 → 直接用 re。
        try:
            for kw in ("wide-brim hat", "hat", "hair ornament", "headdress", "crown", "beret"):
                m = re.search(r"[^,]*" + re.escape(kw) + r"[^,]*", body, re.I)
                if m:
                    tag = m.group(0).strip()
                    if tag.lower().startswith("("):
                        break
                    body = body.replace(tag + ", ", "", 1).replace(tag, "", 1)
                    _m3 = re.search(r"1girl,\s*solo,?", body, re.I)
                    body = (body[:_m3.end()] + f" {tag}," + body[_m3.end():]) if _m3 else f"{tag}, {body}"
                    break
        except Exception:
            pass
        # 2026-10-21 用户：构图呆板 / 背景假 → Anima 后处理（正向）
        try:
            _b = body
            # ① 构图：centered / eye-level / front → 动态三分
            _b = re.sub(r"(?i)\bcentered( composition)?\b", "off-center composition", _b)
            _b = re.sub(r"(?i)\bsteady eye-level angle\b", "dynamic three-quarter angle", _b)
            _b = re.sub(r"(?i)\beye-level\b", "dynamic three-quarter angle", _b)
            _b = re.sub(r"(?i)\bfront view\b", "three-quarter view", _b)
            _b = re.sub(r"(?i)\bsymmetrical( composition)?\b", "rule-of-thirds composition", _b)
            # ③ 背景：别全糊 + 去掉假氛围
            _b = re.sub(r"(?i)\bshallow depth of field\b", "medium depth of field", _b)
            _b = re.sub(r"(?i)\bsoftly blurred ([a-z ]+?) behind\b",
                        r"detailed \1 behind", _b)
            _b = re.sub(r"(?i)\bblurred background\b", "detailed background", _b)
            _b = re.sub(r"(?i)\blens flare\b,?\s*", "", _b)
            # ④ 动态姿势 / 空间层次 / 接地阴影（缺则补）
            _add = []
            if not re.search(r"(?i)\b(dynamic pose|contrapposto|weight shift)\b", _b):
                _add.append("dynamic natural pose, weight shift, contrapposto")
            if not re.search(r"(?i)\b(off-center|rule of thirds)\b", _b):
                _add.append("off-center composition, rule of thirds")
            if not re.search(r"(?i)\b(contact shadow|grounded shadow|ambient occlusion)\b", _b):
                _add.append("grounded contact shadows, ambient occlusion, atmospheric perspective")
            if _add:
                _b = _b.rstrip(", ") + ", " + ", ".join(_add)
            # ⑤ 静态姿势兜底：站立/抱手 → 至少给一个动作（坐/卧不强行改）
            if not re.search(r"(?i)\b(sitting|seated|kneeling|lying|reclining)\b", _b):
                if not re.search(r"(?i)\b(walking|mid-step|turning|looking back|leaning|"
                                 r"running|dancing|reaching|adjusting|lifting)\b", _b):
                    if re.search(r"(?i)\bstanding\b", _b):
                        _b = re.sub(r"(?i)\bstanding\b",
                                    "mid-step, slight body turn", _b, count=1)
                    if re.search(r"(?i)\bhands clasped( inside sleeves)?\b", _b):
                        _b = re.sub(r"(?i)\bhands clasped( inside sleeves)?\b",
                                    "one hand lifting the hem of her outfit", _b, count=1)
                    if not re.search(r"(?i)\b(mid-step|walking|turning|adjusting|lifting)\b", _b):
                        _b = _b.rstrip(", ") + ", mid-step, slight body turn"
            # ⑥ 人物融入背景：统一主光方向 + 投影/反射/色彩和谐
            _b = re.sub(r"(?i)\bsoft directional key light from the upper right\b",
                        "key light from the scene's main light source", _b)
            _b = re.sub(r"(?i)\bgentle rim light tracing hair and shoulders\b",
                        "rim light from the main light source", _b)
            if not re.search(r"(?i)\b(cast shadow|character grounded)\b", _b):
                _b = (_b.rstrip(", ") + ", consistent lighting with the scene, "
                      "cast shadow on the floor, color harmony, environment reflections, "
                      "character grounded in the environment")
            body = _b
        except Exception:
            pass
        return body
    except Exception:
        return positive

def assemble_positive_prompt(structured, name_en, series_en, framing, extra_fields=()):
    # 标杆模板（2026-10-12）：按用户手跑好图的结构拼装（平铺无权重 + 解剖强调 + 气质词）；
    # 任何异常都回退到原有拼装逻辑，不影响出图。
    # extra_fields：2026-10-21 —— 长模板默认只读 face_priority/appearance/outfit/...，
    #   eye_colors/body/composition/depth 会被丢掉；Anima 两线通过这个参数补回。
    if _cfg.REF_TEMPLATE:
        try:
            return _cfg.build_reference_prompt(structured, name_en, series_en,
                                               (structured or {}).get("theme"), framing,
                                               extra_fields=extra_fields)
        except Exception as _e:
            print(f"[标杆模板] 回退旧拼装（{type(_e).__name__}）")
    parts = []

    quality = structured.get("quality", "").strip()
    if quality:
        parts.append(quality)

    subject = structured.get("subject", "").strip()
    if subject:
        parts.append(subject)

    # ★ 修 II（2026-10-17 v2）：景别词**紧跟在质量/subject 之后**（第 3 位）
    #   原因：SDXL CLIP 按 77 token 分段，越靠后权重越低；此前景别落在第 90 位 ≈ 无效
    #   放在最前 = 强指令，能压住后面的场景/光照描述
    if framing:
        parts.append(str(framing))

    parts.append(f"{name_en}, {series_en}")

    face = structured.get("face_priority", "").strip()
    if face:
        parts.append(weight_tags(face, WEIGHT_FACE))

    expr = structured.get("expression_priority", "").strip()
    if expr:
        parts.append(weight_tags(expr, WEIGHT_EXPRESSION))

    for key in ("core_features", "appearance", "body", "outfit", "expression", "pose"):
        v = structured.get(key, "").strip()
        if v:
            parts.append(v)

    scene = _assemble_scene(structured)
    if scene:
        parts.append(scene)

    lighting = structured.get("lighting", "").strip()
    if lighting:
        parts.append(lighting)

    composition = structured.get("composition", "").strip()
    # 景别词已在最前面注入 → 这里只放构图描述（不再重复 framing）
    if composition:
        parts.append(composition)

    depth = structured.get("depth", "").strip()
    if depth:
        parts.append(depth)

    return dedup_tags(", ".join(p for p in parts if p))


# ===========================================================================
# JSON 解包（关键修复）
# ===========================================================================
def _unwrap_json(data):
    """
    处理 AI 返回的嵌套 JSON：
      {"type": "json_object", "content": {...实际数据...}}
    →  {实际数据}
    同时处理 content 是字符串的情况（再解析一次）。
    """
    if not isinstance(data, dict):
        return data

    # 只有 type + content 两个字段，且 content 是 dict 或 str
    if "content" in data and isinstance(data["content"], (dict, str)):
        content = data["content"]
        if isinstance(content, str):
            try:
                content = robust_json_parse(content)
            except Exception:
                return data
        if isinstance(content, dict) and content:
            print("  [JSON解包] 检测到嵌套结构，已解包")
            return content

    return data


# ===========================================================================
# 重试工具
# ===========================================================================
def _is_retryable(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code and status_code in _RETRYABLE_STATUS:
        return True
    exc_name = type(exc).__name__
    if exc_name in ("APITimeoutError", "APIConnectionError",
                    "InternalServerError", "RateLimitError"):
        return True
    return False


def _get_retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return None


def _compute_delay(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, RETRY_MAX_DELAY)
    delay = RETRY_BASE_DELAY * (2 ** attempt)
    delay = min(delay, RETRY_MAX_DELAY)
    jitter = delay * RETRY_JITTER * random.random()
    return delay + jitter


# ===========================================================================
# 诊断工具
# ===========================================================================
def _dump_resp_structure(resp, label):
    print(f"  [{label}诊断] output_text = {repr(resp.output_text)[:400]}")
    print(f"  [{label}诊断] output 长度 = {len(resp.output)}")
    for i, item in enumerate(resp.output):
        item_type = getattr(item, "type", "?")
        print(f"  [{label}诊断] item[{i}] type={item_type} "
              f"class={type(item).__name__}")


def _count_tool_calls(resp):
    """统计本轮 output 里的 reasoning 长度与本地 function tool 调用次数。"""
    search_count = 0
    fetch_count = 0
    reasoning_len = 0

    for item in resp.output:
        item_type = getattr(item, "type", "")

        if item_type == "reasoning":
            content = (
                getattr(item, "content", None)
                or getattr(item, "summary", None)
                or getattr(item, "text", None)
            )
            if isinstance(content, list):
                reasoning_len += sum(
                    len(str(getattr(c, "text", c))) for c in content
                )
            elif content:
                reasoning_len += len(str(content))

        elif item_type == "function_call":
            name = getattr(item, "name", "")
            if name == "web_search":
                search_count += 1
            elif name == "web_fetch":
                fetch_count += 1

    return reasoning_len, search_count, fetch_count


# ===========================================================================
# Responses API 通用调用（含「本地 function tool 联网」循环）
# ===========================================================================
USAGE_LOG = []      # 2026-10-18：每次 API 调用的 token 用量（供成本核算/写进 rows.json）


def _usage_brief(resp):
    try:
        u = resp.usage
        detail = getattr(u, "output_tokens_details", None)
        reasoning = getattr(detail, "reasoning_tokens", None) if detail else None
        # 2026-10-18 新增：记录 input/output tokens（Responses API 字段名 input_tokens）
        inp = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", None) or 0
        out = getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", None) or 0
        try:
            USAGE_LOG.append({"input": int(inp or 0), "output": int(out or 0),
                              "reasoning": int(reasoning or 0)})
        except Exception:
            pass
        return (f"status={getattr(resp, 'status', '?')}, "
                f"input_tokens={inp}, output_tokens={out}, "
                f"reasoning_tokens={reasoning}")
    except Exception:
        return f"status={getattr(resp, 'status', '?')}"


def usage_summary(start=0):
    """统计 USAGE_LOG[start:] 的 token 合计"""
    seg = USAGE_LOG[start:]
    return {"calls": len(seg),
            "input_tokens": sum(x["input"] for x in seg),
            "output_tokens": sum(x["output"] for x in seg),
            "reasoning_tokens": sum(x["reasoning"] for x in seg)}


def _create_response(request_kwargs, label):
    """单次 API 请求 + 可重试错误退避"""
    last_error = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            return client.responses.create(**request_kwargs)
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                print(f"  [{label}失败-不可重试] {e}")
                raise
            delay = _compute_delay(attempt, _get_retry_after(e))
            if attempt < RETRY_MAX_ATTEMPTS - 1:
                print(f"  [{label}请求失败-可重试] attempt={attempt+1}/"
                      f"{RETRY_MAX_ATTEMPTS}, 等待 {delay:.1f}s: {e}")
                time.sleep(delay)
            else:
                print(f"  [{label}请求失败-重试耗尽] {e}")
    raise last_error


def _to_input_item(item):
    """
    把上一轮的 output item 转成可回填的 input item。

    【为什么必须回填】deepseek-flash 是 thinking 模式：如果只回填 function_call
    和 function_call_output，下一轮会直接 400 报错：
        The `reasoning_text` in the thinking mode must be passed back to the API.
    所以必须把 reasoning 项（内含 reasoning_text）原样带回去。
    """
    try:
        return item.model_dump(exclude_none=True)
    except Exception:
        pass

    item_type = getattr(item, "type", "")
    if item_type == "function_call":
        return {
            "type": "function_call",
            "call_id": getattr(item, "call_id", ""),
            "name": getattr(item, "name", ""),
            "arguments": getattr(item, "arguments", "") or "{}",
        }
    if item_type == "reasoning":
        content = []
        for part in (getattr(item, "content", None) or []):
            content.append({
                "type": "reasoning_text",
                "text": getattr(part, "text", str(part)),
            })
        return {"type": "reasoning", "content": content}
    return None


def _run_agent_loop(input_text, max_output_tokens, tools, label):
    """
    一次完整的「模型 → 本地搜索 → 模型」循环，直到模型给出最终 JSON。
    返回 (structured_dict, 搜索次数, 抓页次数)。
    """
    input_items = [{
        "role": "user",
        "content": [{"type": "input_text", "text": input_text}],
    }]
    search_count = 0
    fetch_count = 0
    max_rounds = WEB_SEARCH_MAX_ROUNDS if tools else 0
    total_rounds = max_rounds + 1

    for round_idx in range(total_rounds):
        final_round = round_idx >= max_rounds    # 最后一轮禁用工具，逼模型出 JSON

        request_kwargs = {
            "model": DEEPSEEK_MODEL,
            "input": input_items,
            "reasoning": {"effort": REASONING_EFFORT},
            "max_output_tokens": max_output_tokens,
        }
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "none" if final_round else "auto"

        if DEBUG_RAW_OUTPUT:
            print(f"  [{label}请求] 第{round_idx + 1}/{total_rounds}轮 "
                  f"tool_choice={request_kwargs.get('tool_choice', '无工具')}")

        resp = _create_response(request_kwargs, label)

        if DEBUG_RAW_OUTPUT:
            _dump_resp_structure(resp, label)
            r_len, n_search, n_fetch = _count_tool_calls(resp)
            print(f"  [{label}诊断] reasoning={r_len}字符, "
                  f"本轮请求工具：搜索{n_search} 抓页{n_fetch}")

        function_calls = [
            item for item in resp.output
            if getattr(item, "type", "") == "function_call"
        ]
        print(f"  [{label}返回] 第{round_idx + 1}轮 {_usage_brief(resp)}, "
              f"工具调用={len(function_calls)}, "
              f"文本={len(resp.output_text or '')}, "
              f"累计搜索={search_count}, 抓页={fetch_count}")

        if not function_calls:
            content = (resp.output_text or "").strip()
            if not content:
                global LAST_EMPTY_BUDGET_EXHAUSTED
                _b = _usage_brief(resp)
                # 兜底识别（2026-10-12）：reasoning 吃满预算 → status=incomplete 且 reasoning≈预算
                LAST_EMPTY_BUDGET_EXHAUSTED = ("incomplete" in _b
                                               and "reasoning_tokens=" in _b
                                               and "reasoning_tokens=None" not in _b)
                if LAST_EMPTY_BUDGET_EXHAUSTED:
                    print(f"  [{label}兜底] 判定为 reasoning 吃满预算导致空输出 → "
                          f"将由调用方【缩短输入】重试（不再原样重试）")
                raise ValueError(f"{label} 返回空内容（{_b}）")

            structured = robust_json_parse(content)
            if not structured or not isinstance(structured, dict):
                preview = content[:200].replace("\n", " ")
                print(f"  [{label}警告] JSON 解析失败，原始内容：{preview}")
                raise ValueError(f"{label} 返回非 JSON 内容")

            # === 关键修复：解包嵌套 JSON ===
            structured = _unwrap_json(structured)

            if search_count == 0 and tools:
                print(f"  [{label}提醒] 本次模型未调用联网搜索工具（内容是凭记忆写的）")
            return structured, search_count, fetch_count

        if final_round:
            raise ValueError(f"{label} 最后一轮仍在请求工具调用，未能给出 JSON")

        # === 关键：把本轮 output（含 reasoning_text）原样回填 ===
        # thinking 模式必须回填 reasoning，否则下一轮 400 报错
        for item in resp.output:
            dumped = _to_input_item(item)
            if dumped:
                input_items.append(dumped)

        # === 本地真正执行搜索，并把结果回填给模型 ===
        for call in function_calls:
            call_name = getattr(call, "name", "")
            call_args = getattr(call, "arguments", "") or "{}"
            output, n_search, n_fetch = execute_tool(
                call_name, call_args, max_results=WEB_SEARCH_MAX_RESULTS,
            )
            search_count += n_search
            fetch_count += n_fetch

            input_items.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": output,
            })

            try:
                args = json.loads(call_args)
            except Exception:
                args = {}
            try:
                data = json.loads(output)
            except Exception:
                data = {}
            if data.get("error"):
                print(f"      ! {call_name}({args}) 出错：{data['error']}")
            elif data.get("results"):
                print(f"      [本地{call_name}] query={args.get('query', args)!r} "
                      f"→ {'/'.join(data.get('engines', []))} "
                      f"命中 {len(data['results'])} 条：")
                for r in data["results"][:3]:
                    print(f"        · {r.get('title', '')[:60]} "
                          f"| {r.get('url', '')[:60]}")

    raise ValueError(f"{label} 未产出结果")


def _call_responses(input_text, max_output_tokens, enable_web_search=False,
                    label="AI"):
    """统一入口：自动重试整个 agent 循环（含 JSON 解析失败重试）。"""
    tools = []
    if enable_web_search and WEB_SEARCH_ENABLED:
        tools.append(WEB_SEARCH_TOOL)
        if WEB_FETCH_ENABLED:
            tools.append(WEB_FETCH_TOOL)

    last_error = None

    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            structured, search_count, fetch_count = _run_agent_loop(
                input_text, max_output_tokens, tools, label,
            )
            print(f"  [{label}完成] 本地联网搜索 {search_count} 次，"
                  f"抓页 {fetch_count} 次")
            structured.pop("artists", None)
            return structured

        except Exception as e:
            last_error = e

            is_json_error = isinstance(e, ValueError)
            if not _is_retryable(e) and not is_json_error:
                print(f"  [{label}失败-不可重试] {e}")
                raise

            retry_after = _get_retry_after(e)
            delay = _compute_delay(attempt, retry_after)
            remaining = RETRY_MAX_ATTEMPTS - attempt - 1

            if remaining > 0:
                print(f"  [{label}失败-可重试] attempt={attempt+1}/"
                      f"{RETRY_MAX_ATTEMPTS}, 等待 {delay:.1f}s 后重试: {e}")
                time.sleep(delay)
            else:
                print(f"  [{label}失败-重试耗尽] {e}")

    raise last_error


# ===========================================================================
# 第 1 次调用：AI 选角
# ===========================================================================
def _model_range_hint(workflow):
    """把某条工作流的"人物选择范围"写成给选角 AI 看的硬约束"""
    info = WORKFLOW_MODEL_INFO.get(workflow, {})
    _cut = info.get("cutoff_date") or info.get("cutoff") or "未知"
    lines = [
        f"模型：{info.get('label', workflow)}",
        f"家族：{info.get('family', '未知')}",
        f"训练数据：{info.get('source', '未知')}",
        f"知识截止：{info.get('cutoff', '未知')}",
    ]
    if info.get("danbooru_based"):
        lines.append(
            "选角范围（硬约束）：必须是 danbooru 上的**角色标签**（category=4）；"
            f"角色级投稿数：出道年 ≤{CHAR_POP_OLD_YEAR} 的老角色 ≥{CHAR_POP_OLD_MIN}，"
            f"之后的新角色 ≥{CHAR_POP_NEW_MIN}；作品必须是 danbooru 版权标签且投稿 "
            f"≥{SERIES_MIN_POSTS}；角色**本人首次登场日期** ≤ {_cut}"
            f"（{info.get('cutoff')}）；只查得到作品级年份、查不到角色级日期的角色不要选；"
            "越热门这个模型画得越像")
    else:
        lines.append(
            "选角范围（硬约束）：该模型不是 danbooru 系、角色级知识很弱；"
            "请改选其他更容易被模型认识的角色")
    return "\n".join(lines)


def ask_ai_character(excluded_names, target_model="Anima-2.9B",
                     range_hint="", reject_reason="", allow_seasonal=False,
                     avoid_themes=None):
    excluded_str = ", ".join(excluded_names) if excluded_names else "（暂无）"
    reject_block = ""
    # 四季常装只在 Anima-2.9B 两条线上作为可选主题（2026-10-11）
    seasonal_line = ("- 也可选「四季常装」（角色的**日常服装**，如针织衫/围巾/短靴等常服），"
                     "只填「四季常装」四个字即可\n" if allow_seasonal else "")
    # 降权结果回传选题（2026-10-12）：该模型下多次不达标的主题必须避开
    avoid_line = ("- 【本模型下已多次质量不达标的主题，**必须避开**】"
                  + ", ".join(avoid_themes) + "\n") if avoid_themes else ""
    if reject_reason:
        reject_block = (f"\n【上一次选角被打回】原因：{reject_reason}\n"
                        f"→ 请换一个**完全不同的、更热门/更早期**的角色，不要重复同一个。\n")

    input_text = f"""你是二次元AI角色选择助手。请联网搜索后，选 1 个热门动漫/二游女性角色，配一个该角色二创中常见、且已有大量同人图的换装主题。

【目标模型的人物选择范围（硬约束，必须遵守）】
{range_hint}
{reject_block}
【角色要求】
- 角色必须落在上面这个模型的认识范围内；**宁可选经典老热门角色，也不要赌新角色**
- 优先选择热门作品中的主要角色：原神、崩坏星穹铁道、蔚蓝档案、Fate、Vocaloid、Hololive、东方Project、FGO、碧蓝航线、明日方舟、偶像大师、Love Live 等
- 你选的角色会被**本地校验**（danbooru 角色标签 + 角色级投稿数达标 + 角色本人首次登场日期 ≤ 模型知识截止），不满足会被打回重选
- 禁止使用已用过的：{excluded_str}

【name_en 格式】
Danbooru 完整标准标签，有歧义时带系列括号（firefly_(honkai:_star_rail)），无歧义直接写（raiden_shogun）。英文小写，空格转下划线。

【联网搜索工具 — 你必须真的调用它】
- 你有一个名为 web_search 的函数工具，可以真实联网搜索网页，返回「标题 + 链接 + 摘要」
- 这是你获取最新二创信息的唯一途径：禁止凭记忆编造搜索结果
- 关键词一律用中文（角色名可用中文或日文）：本机是中文区 Bing，纯英文关键词会返回无关结果
- 至少调用 1 次，最多 {WEB_SEARCH_MAX_HINT} 次（例：「流萤 泳装 同人图」「白子 女仆 同人」）
- 发起调用后，系统会把搜索结果追加到对话中，你可以继续调用，或直接输出最终 JSON

【联网搜索与主题要求】
- 搜索该角色在 Pixiv / Danbooru / X 上的近期二创作品，确认角色英文标签的正确性
- 搜索该角色最热门的换装主题，选一个已有大量同人图的
- 主题必须是「换装类二创」（泳装 / 浴衣 / 女仆 / 圣诞 / 婚纱 / 制服 / 护士 / 运动等），不是原作场景或没换装的日常
{seasonal_line}{avoid_line}
- 主题只填中文短语
- {_SEARCH_STRATEGY}
- {_SEARCH_TAIL}

{_JSON_OUTPUT}

【JSON 结构】
{{
  "name": "角色中文名",
  "series": "作品中文名",
  "name_en": "角色英文标准标签",
  "series_en": "作品英文标准标签",
  "debut_date": "该角色**本人**首次登场/实装的日期：YYYY-MM-DD；查不到日填 YYYY-MM；查不到月填 null",
  "debut_year": 该角色**本人**首次登场/实装的年份（整数，四位数；与 debut_date 一致；不要写作品的发行年）,
  "theme": "换装主题中文短语"
}}

【debut_date / debut_year 必须联网确认】
· 填**角色本人**首次登场/实装的日期，不是作品发行年份
  （例：雷电将军 = 2021-09-01，芙宁娜 = 2023-11-08，初音未来 = 2007-08-31；
   它们所属作品的年份分别是 2020/2020/2007，务必按角色分别给）。
· 优先查到**月/日**；查不到日就只填 `YYYY-MM`；查不到月填 null；**不要猜**。
· `debut_year` 填同一角色的四位数年份（与 debut_date 一致）。
"""

    return _call_responses(
        input_text=input_text,
        max_output_tokens=12000,   # 原 4000：选角+联网搜索调用，预算太紧易被 reasoning 吃满
        enable_web_search=True,
        label="AI选角",
    )


# ===========================================================================
# 第 2 次调用：AI 生成提示词
# ===========================================================================
# 兜底信号（2026-10-12）：上一次 LLM 调用是否因 reasoning 吃满预算而空输出
LAST_EMPTY_BUDGET_EXHAUSTED = False


def _prompt_selfcheck(structured, name_en, series_en, theme=None):
    """
    提示词自检（2026-10-11 新增，修"不同角色质量不齐 / 特征混搭"）。

    返回 (是否合格, 原因列表)。检查：
      ① 角色标签在不在（core_features/appearance 里必须出现该角色英文标签或其 token）
      ② 三类外观锚点是否齐全：发色/发型、瞳色、头饰/发饰（任一缺失即不合格）
      ③ 主题服从：泳装主题下 outfit 必须含泳装词，且不得含制服/礼服类词
         （实测芙宁娜被画成军装礼服 = 这条没兜住）
    """
    blob = json.dumps(structured or {}, ensure_ascii=False).lower()
    reasons = []
    token = (name_en or "").split("(")[0].strip("_ ").lower()
    # **去掉一切非字母数字**再比对：LLM 写的是 `furina \(genshin impact\)`，
    # 只去空格/下划线会漏掉反斜杠与括号 → 永远匹配不上（实测踩过）
    flat = re.sub(r"[^a-z0-9]", "", blob)
    if token and re.sub(r"[^a-z0-9]", "", token) not in flat:
        # 降级为**警告**：assemble_positive_prompt 本来就会把角色标签拼进正向，
        # LLM 字段里没有 ≠ 最终提示词里没有，不该据此重生成
        reasons.append("警告：字段里没看到角色标签（最终提示词会自动补上）")
    if not any(h in blob for h in ("hair", "发色", "发型")):
        reasons.append("缺发色/发型锚点")
    if not any(e in blob for e in ("eye", "eyes", "瞳", "眼")):
        reasons.append("缺瞳色锚点")
    if not any(a in blob for a in ("headband", "hair ornament", "hairband", "ribbon",
                                   "hat", "choker", "necklace", "earring", "bow",
                                   "发饰", "发箍", "头饰", "帽", "颈饰", "choker")):
        reasons.append("缺头饰/发饰锚点")
    th = theme or ""
    if any(k in th for k in ("泳装", "沙滩", "度假", "水着", "泳衣")):
        outfit = str((structured or {}).get("outfit", "")).lower()
        if not any(s in outfit for s in ("swimsuit", "bikini", "one-piece", "halter")):
            reasons.append("主题不服从：outfit 里没有泳装")
        # 制服/礼服类用**词边界**匹配：否则 "suit" 会命中 "swimsuit"（踩过这个坑）
        forbid = ("uniform", "military", "coat", "suit", "dress shirt", "gown", "cape",
                  "礼服", "制服")
        for b in forbid:
            if re.search(r"(^|[^a-z])" + re.escape(b) + r"([^a-z]|$)", outfit):
                reasons.append(f"主题不服从：outfit 含「{b}」")
                break
    return (len([r for r in reasons if not r.startswith("警告")]) == 0), reasons


def ask_ai_prompt(name, series, name_en, series_en, theme,
                  framing="cowboy shot", workflow="api"):
    name_en_anima = _escape_anima(name_en)
    series_en_anima = _escape_anima(series_en)
    target_model = WORKFLOW_MODEL_INFO.get(workflow, {}).get(
        "label", WORKFLOW_LABELS.get(workflow, workflow))
    directive = style_directive(workflow)
    framing_line = (f"景别固定 {framing}，务必让**头部与头饰完整入镜**（不要裁掉帽子/发饰）。"
                    if framing else
                    "不指定固定景别，但**必须以脸和上半身为画面主体**：采用**胸像/半身近景**"
                    "（`close-up, upper body, portrait`），人物占画幅 70% 以上，"
                    "**头顶、发饰、头箍必须完整入框不裁切**，背景简洁并虚化（海滩/海面），"
                    "确保脸型、五官、眼型与发饰有足够像素细节——这是本条的硬性要求。")
    _anima_direct = ""
    if workflow in ("api", "anima_flow"):
        _anima_direct = (
            "- 【Anima 姿势/构图/背景 · 重要】`pose` 必须是一个**有动作的瞬间**"
            "（行走/转身/回头/抬手扶帽/提裙/托盘侧身/整理袖口/倚栏），"
            "禁止 `standing straight, arms at sides, hands clasped, facing viewer` 的证件照；\n"
            "  `composition` 用 `off-center, rule of thirds, three-quarter view, dynamic angle, "
            "foreground depth`，禁止 `centered, symmetrical, steady eye-level, front view`；\n"
            "  背景三层写具体材质与空间关系，`depth` 用 `medium depth of field, detailed "
            "background`，不要只写 bokeh/虚化；写接触阴影、环境光、大气透视。"
        )

    # 眼睛渲染加强规则：**仅 animagine_xl**（用户 2026-10-11）；其他工作流不加
    if workflow in EYE_RENDER_WORKFLOWS:
        eye_render_line = (
            "- 【眼睛渲染 · 通用 · 重要】`eye_colors` 必须写成 **danbooru 标签体**，"
            "且每个颜色都带 `eyes`：\n"
            "  ① 单瞳色：`blue eyes, detailed eyes`\n"
            "  ② 异色瞳：`heterochromia, dark blue eyes, light blue eyes, detailed eyes`\n"
            "     —— 两侧颜色**各写一个「颜色 + eyes」标签**，不要只写 `heterochromia` 就完事\n"
            "  ③ **禁止用自然语言描述瞳孔形状或瞳孔高光**（如 `teardrop-shaped pupil`、"
            "`star-shaped pupil`）——瞳孔与高光交给 `detailed eyes` 标签和表情字段；"
            "自然语言写瞳孔最容易糊成色块\n"
            "  ④ **必须带 `detailed eyes`**：给双眼细节兜底，避免\"一只眼精细、另一只眼色块\"\n"
            "  （以上与具体角色无关，任何瞳色组合都照此写）")
    else:
        eye_render_line = ""

    input_text = f"""你是AI绘画提示词助手，为 **{target_model}** 生成提示词。只负责画面描述。

【目标模型】
- 模型名称：**{target_model}**
- 提示词会按「{PROMPT_ORDER}」的顺序拼接
- 每个字段只填该字段内容，不要跨字段混填

{directive}

本次生成：{name}（{series}），主题 {theme}，
人物英文标签 {name_en_anima}, {series_en_anima}。{('景别固定 ' + framing + '。') if framing else '不指定景别。'}

【联网搜索工具 — 你必须真的调用它】
- 你有一个名为 web_search 的函数工具，可以真实联网搜索网页，返回「标题 + 链接 + 摘要」
- 这是你获取角色设定与二创服装信息的唯一途径：禁止凭记忆编造搜索结果
- 关键词优先「角色中文名 + 作品 + wiki/fandom」；中文搜不到再用「英文角色标签 + site:fandom.com」
- 拿到 fandom / wiki 的链接后，必须用 web_fetch 读正文，不要只看摘要
- 至少调用 1 次，最多 {WEB_SEARCH_MAX_HINT} 次
- 发起调用后，系统会把搜索结果追加到对话中，然后再一次性输出最终 JSON

【必须检索以下信息】
- 角色的官方设定：发色、发型、瞳色、标志性特征
- 角色的性格特征，用于决定 face_priority 和 expression_priority
- 该角色在「{theme}」主题下的二创服装：搜索该角色 + 主题关键词，提取服装的实际颜色、款式、配饰、花纹
- 该角色近期（2024-2025）二创作品中的常见场景氛围与构图习惯
- {_SEARCH_STRATEGY}
- {_SEARCH_TAIL}

【内容要求】
- 【克制 · 别用力过猛】总长度控制在 **1200 字符以内**。不要堆砌 bokeh/景深/氛围/光斑类词，不要堆同义形容词。
- 【禁止通用美颜词】`face_priority` 严禁出现 youthful oval face / soft round face / soft cheeks / delicate features / delicate small nose / large expressive eyes / detailed sparkling eyes / glossy lips / flawless skin 这类**不指向角色**的词；
  只写该角色**官方辨识特征**（眼型、眉形、发型如何框住脸、特征痣/纹样/头饰）。
- 【场景必须贴题 · 别自作聪明】主题是**泳装/沙滩/度假**时，背景只允许**自然海滩元素**（海、沙滩、蓝天白云、椰树、遮阳伞、沙滩椅、贝壳、海鸥），
  **禁止**出现城市天际线、城堡、教堂、塔楼、欧式建筑、现代都市、霓虹、室内、泳池、以及漂浮泡泡/珍珠/光斑等人造粒子。
  不要因为角色来自某个世界观就把该世界观的建筑搬进背景（例如芙宁娜 → 枫丹 → 城堡塔楼，这是错的）。
- 场景三层（远/中/近）**每层只写 1-2 个元素**，不要堆砌。
- 构图：{framing_line}
- 【构图字段写法 · 重要】`composition` 字段**必须写成 danbooru 标签**（逗号分隔的英文标签），
  **不要写自然语言句子**（该底模只吃标签，句子等于没写）。例如：`close-up, upper body, portrait, looking at viewer`。
{_anima_direct}
- 【人物锚点必须齐全 · 重要】把该角色**最具辨识度的官方外观锚点逐条写全**，尤其是
  **头饰类（发箍/发带/发夹/帽子/发饰）**、颈饰、瞳色、发型与发色渐变 —— 这些是"像不像"的关键。
  必须**先搜索**该角色的官方设定与二创高频标签，再落到 `appearance` / `core_features` 字段，
  **不得遗漏**（例：流萤必须有 `black headband` 黑色发箍 + 叶片发饰；芙宁娜必须有金冠礼帽 + 蓝宝石颈饰）。
  写完后自查一遍：该角色身上最显眼的 3 个头面部配饰是否都出现了。
- 【体型必须按官方设定 · 重要】`body_type` 只能填 adult_mature / adult_slim / adult_petite / teen / child / nonhuman；
  `body` 写该角色官方体型（年龄感、身高、骨架、曲线），**不要一律写 petite slender figure**；
  成年角色不要写成幼态，小体型/未成年角色也不要强行写成成女。体型档位会直接影响后续正向锚点和防幼负面。
- 【眼睛必须写准 · 重要】若该角色是异色瞳，`eye_colors` 里必须**分别写清左眼、右眼各自的颜色**（例：`left eye dark blue, right eye light blue`），
  并以官方设定为准，禁止只写 `heterochromia` 就完事；若官方是单一瞳色，就只写那个颜色，**禁止凭空臆造异色瞳**。
  查证时请专门搜索"角色名 + 异色瞳 / 眼睛颜色 / 左眼 右眼"，不要在没查到的情况下猜。
{eye_render_line}
- 【饰品必须标签化 · 通用 · 重要】腰饰、吊坠、颈饰、发饰等**小物件必须写成 danbooru 标签**
  （如 `jeweled waist ornament`、`blue gemstone pendant`、`gold waist bow`），
  **禁止用自然语言长句描述**（该底模不吃句子，等于没写）；
  对最关键的 1~2 件饰品可适度加权（如 `(blue gemstone pendant:1.15)`）。
- 【脸部干净 · 通用】表情字段里腮红**只写 `blush`**，禁止 `heavy blush` / `deep blush` 这类加重写法
  （会把脸糊成一片红斑）；正向必须带 `detailed face`。
- 【负面清单要含】`blurry blush, smeared makeup, extra ornament, duplicate pendant, floating accessory, misplaced jewelry`
- 【服装必须服从主题 · 重要】主题为泳装/沙滩/度假时，`outfit` **必须是泳装**（`swimsuit` / `bikini` /
  `one-piece swimsuit` / `halter neck` 等），**严禁**出现制服、军装、礼服、外套、衬衫、长裙、披风
  （`uniform / military / coat / suit / dress shirt / gown / cape`）——实测芙宁娜被画成军装礼服就是这个原因。
- 【严禁混入其他角色 · 重要】`appearance` / `core_features` **只能包含该角色本人的特征**；
  联网搜索时若结果里出现**同作品的其他角色**，**不得把她们的外观特征写进来**（发色/瞳色/发饰/服装都算）。
  写完后自查：这些外观标签换个角色名还成立吗？成立说明写太通用了，必须补该角色**独有**的锚点。
- 颜色要与角色主色调呼应
- 表情要有层次，不要顶格也不要完全压死
- 光影必须包含光源方向 + 光线质感 + 一个具体光影效果 + 环境光反光

【重要】
- {_NO_ARTIST}

{_JSON_OUTPUT}

【JSON 结构】
{{
  "quality": "质量前缀标签",
  "subject": "人数标签",
  "face_priority": "脸型标签，3-5 个",
  "eye_colors": "瞳色（英文短标签）。异色瞳必须写 left eye <颜色>, right eye <颜色>；单色就写 <颜色> eyes。以官方设定为准，查不到只写单一瞳色，禁止臆造",
  "expression_priority": "表情标签，2-4 个",
  "core_features": "标志性特征，2-4 个",
  "appearance": "发色、发型、眼妆、头饰、耳饰（【禁止写瞳色】，瞳色统一写在 eye_colors）",
  "body_type": "adult_mature | adult_slim | adult_petite | teen | child | nonhuman（按官方设定）",
  "body": "按官方设定的体型：年龄感、身高、骨架、曲线；不要默认 petite slender figure",
  "outfit": "该角色在「{theme}」主题下的二创服装描述",
  "expression": "补充表情（如 face_priority 已写全则留空）",
  "pose": "姿势动作描述",
  "scene_foreground": "近景具体元素（靠近镜头、不抢主体）",
  "scene_midground": "中景具体道具或建筑",
  "scene_background": "远景天际线元素",
  "lighting": "光源方向 + 光线质感 + 具体光影效果 + 环境光反光",
  "composition": "构图描述",
  "depth": "景深描述",
  "negative": "配套负面，包含基础质量项、肢体异常项、AI味项、过度表情项、嫌弃脸项。{_NO_FRAMING_NEG}"
}}"""

    return _call_responses(
        input_text=input_text,
        max_output_tokens=16000,   # 8000→12000→30000→45000→16000（实测 reasoning 会吃满任何预算，
                                   # 高预算只是把 token 白烧掉 → 回调到"答案量+余量"，靠空输出兜底）
        enable_web_search=True,
        label="AI生成",
    )


# ===========================================================================
# 主流程
# ===========================================================================
def cleanup_empty_dir(dir_path):
    if os.path.isdir(dir_path):
        try:
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
        except Exception:
            pass


def _load_gate_blacklist():
    """读取独立的门控黑名单；文件损坏时返回空表，不阻塞主流程。"""
    try:
        data = load_json(GATE_REJECT_FILE, {})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_gate_record(v):
    return isinstance(v, dict) and any(
        k in v for k in ("status", "name_en", "gate_reason", "rejected_at"))


def _normalize_gate_blacklist(raw, default_model):
    """把黑名单统一成 {model_key: {name_en: record}}。

    旧版是扁平格式 {name_en: record}；新版按模型分组。旧记录如果带
    workflow 就按其 model_key 迁移，否则归到当前模型。返回 (数据, 是否迁移)。
    """
    if not raw:
        return {}, False
    if any(_is_gate_record(v) for v in raw.values()):
        out = {}
        for key, rec in raw.items():
            if not _is_gate_record(rec):
                continue
            rec = dict(rec)
            wf = str(rec.get("workflow") or "").strip()
            mk = str(rec.get("model_key") or
                     (_cfg.model_key(wf) if wf else default_model))
            rec["model_key"] = mk
            out.setdefault(mk, {})[key] = rec
        return out, True
    out = {k: v for k, v in raw.items() if isinstance(v, dict)}
    return out, out != raw


def _gate_entries(blacklist, model_key):
    d = blacklist.get(model_key) if isinstance(blacklist, dict) else None
    return d if isinstance(d, dict) else {}


def _mark_gate_rejected(blacklist, excluded, cand, name_en, series_en,
                        reason, scope, model_key, workflow=None,
                        include_in_excluded=True):
    """把门控拒绝的角色写入指定模型的独立持久黑名单。

    与 character_pool.json 完全分离：不占 35 条滚动名额，也不会被自动释放。
    返回 True 表示写入了标记；False 表示没有可用的角色名。
    """
    key = (name_en or cand.get("name") or "").strip()
    if not key:
        return False

    model_bl = blacklist.setdefault(model_key, {})
    if not isinstance(model_bl, dict):
        model_bl = {}
        blacklist[model_key] = model_bl

    now = datetime.datetime.now().isoformat(timespec="seconds")
    prev = model_bl.get(key) if isinstance(model_bl.get(key), dict) else {}
    try:
        count = int(prev.get("count") or 0) + 1
    except Exception:
        count = 1
    rec = {
        "name": (cand.get("name") or key).strip(),
        "name_en": key,
        "series": (cand.get("series") or series_en or "").strip(),
        "series_en": (series_en or "").strip(),
        "theme": (cand.get("theme") or "").strip(),
        "scope": scope,
        "workflow": workflow or "",
        "model_key": model_key,
        "status": "gate_rejected",
        "gate_reason": str(reason or "")[:500],
        "first_rejected_at": prev.get("first_rejected_at") or now,
        "rejected_at": now,
        "count": count,
    }
    model_bl[key] = rec
    if include_in_excluded and key not in excluded:
        excluded.append(key)
    print(f"  [门控拉黑] {key} 写入模型 {model_key} 的独立黑名单"
          f"（累计 {count} 次）：{str(reason or '')[:90]}")
    return True


def _migrate_legacy_gate_rejects(pool, blacklist, excluded, scope, default_model):
    """把旧版写在 character_pool.json 里的 gate_rejected 记录迁到独立黑名单。"""
    legacy = [c for c in pool.get("characters", [])
              if isinstance(c, dict) and c.get("status") == "gate_rejected"]
    if not legacy:
        return False
    for c in legacy:
        wf = str(c.get("workflow") or "").strip()
        mk = str(c.get("model_key") or
                 (_cfg.model_key(wf) if wf else default_model))
        include = (mk == default_model)
        _mark_gate_rejected(
            blacklist, excluded, c, c.get("name_en"), c.get("series_en"),
            c.get("gate_reason") or "legacy gate rejection",
            c.get("scope") or scope, mk, c.get("workflow"),
            include_in_excluded=include)
        if not include:
            try:
                excluded.remove(c.get("name_en"))
            except (ValueError, TypeError):
                pass
        try:
            pool["characters"].remove(c)
        except ValueError:
            pass
    return True


def main():
    today = datetime.date.today().isoformat()
    out_dir = os.path.join(DEFAULT_OUTPUT_DIR, today)

    # 景别判定作用域（2026-10-11 按用户要求）：
    #   animagine_xl 的"丢失一部分画面"问题源于 cowboy shot 属紧构图 + 896x1152 竖幅留头空间不足，
    #   而"头顶完整入画"这类自然语言 danbooru 系模型不认（只吃标签），无法靠标签化解。
    #   → animagine_xl **不再经过景别判定**，直接把构图交给提示词生成模型自由决定。
    workflow = choose_workflow()
    model_info = WORKFLOW_MODEL_INFO.get(workflow, {})
    target_model = model_info.get("label", WORKFLOW_LABELS.get(workflow, workflow))
    # 2026-10-13 用户要求：**nova_xl 固定半身构图**（"和 Animagine 一样半身就行，
    #   不要全身或七分身"）。此前 nova_xl 走"跳过景别"，构图由 LLM 自由决定 →
    #   实测出现全身/七分身，用户认为不好看。这里改为强制注入 upper body。
    # ---- 2026-10-17 用户要求：SDXL 两线**不再对复杂双眼做特殊景别**，与其他角色一致 ----
    #   复杂双眼/普通角色 一律**跳过景别判定**（不锁构图），且启用短提示词模式
    # 2026-10-21 审计：原来的 "[Anima 年份]" 补丁在这里引用了**尚未赋值**的
    #   `structured`（UnboundLocalError 被 except 吞掉），而且写进 quality 字段也
    #   不会被模板读取 → 已删除；年份统一由 config.ANIMA_PREFIX 带上（year 2025）。

    if workflow in ("animagine_xl", "nova_xl"):
        if workflow == "nova_xl":
            # 2026-10-18 回滚（照抄用户手跑配方）：nova **不注入景别、不用短模式**、
            #   不加体型锚点/防幼负面/中性光 —— 你手跑那批就是这个配方
            framing = ""
            _cfg.SHORT_PROMPT_ACTIVE = False
            print("[回滚] nova_xl：不注入景别 / 不用短模式（照抄你手跑配方）")
        else:
            framing = getattr(_cfg, "SDXL_CROP_FRAMING", "upper body, three-quarter view")
            # 2026-10-19 用户：**不准用短提示词**（154 词被 CLIP 77 截断 → 服装/场景/质量词全丢 ✗）
            _cfg.SHORT_PROMPT_ACTIVE = False
            print(f"[景别] animagine_xl 收紧构图：{framing}（长模板，不再用短提示词）")
    elif workflow in _cfg.FRAMING_POOL_WORKFLOWS or workflow in ("api", "anima_flow"):
        # Anima 两线 / Nova 池子：**不启用**短提示词模式（保持原长模板，避免影响这两条线）
        _cfg.SHORT_PROMPT_ACTIVE = False
        # 2026-10-14 用户要求：**Anima-2.9B 把景别判断加回去**（与 SDXL 线一致走判定）
        #   api/anima_flow → 随机 cowboy shot / full body（FRAMING_OPTIONS）
        #   FRAMING_OVERRIDE 非空时按指定景别注入（实验用）
        if _cfg.FRAMING_OVERRIDE:
            framing = _cfg.FRAMING_OVERRIDE
            print(f"[景别锁定] {workflow} 按指定景别注入：{framing}")
        elif workflow in _cfg.FRAMING_POOL_WORKFLOWS:
            framing = random.choice(_cfg.NOVA_FRAMING_POOL)
            if _cfg.NOVA_FRAMING_EXTRA:
                framing = f"{framing}, {_cfg.NOVA_FRAMING_EXTRA}"
            if random.random() < getattr(_cfg, "NOVA_FRAMING_FROM_BELOW_PROB", 0.0):
                framing = f"{framing}, from below"
            print(f"[景别锁定] {workflow} 紧凑构图池随机 →：{framing}")
        else:
            framing = random.choice(FRAMING_OPTIONS)
            print(f"[景别锁定] {workflow}（Anima-2.9B）景别判断已恢复 →：{framing}")
    elif workflow == "animagine_xl":
        # 2026-10-13 用户指定：按他们手跑三张的构图 —— 脸部特写为主
        framing = _cfg.FRAMING_OVERRIDE or _cfg.ANIMAGINE_FRAMING
        print(f"[景别锁定] animagine_xl 固定用户指定构图：{framing}")
    elif workflow in _cfg.FRAMING_POOL_WORKFLOWS:
        # 2026-10-13：紧凑构图池随机（保多样性），全身/远景走负面压制
        #   作用域：nova_xl + animagine_xl（用户要求两条 SDXL 线一致）
        #   FRAMING_OVERRIDE 非空时强制使用（A/B 实验用）
        if _cfg.FRAMING_OVERRIDE:
            framing = _cfg.FRAMING_OVERRIDE
            print(f"[景别锁定] {workflow} 实验指定构图：{framing}")
        else:
            framing = random.choice(_cfg.NOVA_FRAMING_POOL)
            if _cfg.NOVA_FRAMING_EXTRA:
                framing = f"{framing}, {_cfg.NOVA_FRAMING_EXTRA}"
            # from below：20% 低频随机（实测平均最差但个别角色最佳，且三臂差距很小）
            if random.random() < getattr(_cfg, "NOVA_FRAMING_FROM_BELOW_PROB", 0.0):
                framing = f"{framing}, from below"
            print(f"[景别锁定] {workflow} 紧凑构图池随机 →：{framing}")
    elif workflow in NO_FRAMING_WORKFLOWS:
        framing = ""
        print(f"[景别判定] {workflow} 已按设定跳过景别判定（不注入景别，构图由提示词自由决定）")
    else:
        framing = random.choice(FRAMING_OPTIONS)
        print(f"[景别锁定] 今天使用：{framing}")
    print("[工作流-模型对照]")
    for wf in WORKFLOW_POOL:
        mi = WORKFLOW_MODEL_INFO.get(wf, {})
        mark = "← 本次使用" if wf == workflow else ""
        print(f"  {wf:13} → {mi.get('label', '?'):38} | {mi.get('family', '?')[:30]:32} "
              f"| 截止 {mi.get('cutoff', '?')} {mark}")
    print(f"[工作流] 今天使用：{workflow} → {target_model}")

    # 出图前确保 ComfyUI 在跑，没开就自动拉起（不再依赖手点 start_comfyui.bat）
    try:
        ensure_comfyui()
    except Exception as e:
        print(f"[ComfyUI 不可用] {e}\n[中断] 未产出，未记录。")
        return

    pool = load_json(POOL_FILE, {"characters": []})
    _mk_now = _cfg.model_key(workflow)
    _raw_gate = _load_gate_blacklist()
    gate_blacklist, _gate_migrated = _normalize_gate_blacklist(_raw_gate, _mk_now)
    # 2026-10-14 用户要求：**已用角色名单按线路作用域分离，互不干扰**
    #   "artist"    → 有画师线路（api / anima_flow）各用一份 35 人名单
    #   "no_artist" → 无画师线路（animagine_xl / nova_xl）各用一份
    #   同一人物若只在"无画师"名单里，那么在 Anima 有画师线上**仍可被选中** ✓
    #   老数据（无 scope 字段）→ 视为两线都禁用（与改动前行为一致）
    _scope_now = "artist" if workflow in _cfg.ARTIST_TAGS_WORKFLOWS else "no_artist"
    excluded = [c.get("name_en", c.get("name", "")) for c in pool["characters"]
                if c.get("scope") in (None, "", _scope_now)]
    excluded = [x for x in excluded if x]

    # 旧版把 gate_rejected 写在 character_pool.json 里；迁移到独立黑名单，
    # 避免它继续占用 35 条滚动名额、或在轮换时被释放。
    _pool_migrated = _migrate_legacy_gate_rejects(
        pool, gate_blacklist, excluded, _scope_now, _mk_now)
    if _pool_migrated or _gate_migrated:
        try:
            if _pool_migrated:
                save_json(POOL_FILE, pool)
            save_json(GATE_REJECT_FILE, gate_blacklist)
            print("[门控黑名单] 已迁移旧格式记录到按模型分组")
        except Exception as _e_mig:
            print(f"[门控黑名单] 迁移落盘失败：{type(_e_mig).__name__}")

    _model_gate = _gate_entries(gate_blacklist, _mk_now)
    for _bk in _model_gate:
        if _bk not in excluded:
            excluded.append(_bk)

    print(f"[禁用名单] 本线作用域={_scope_now}｜本线排除 {len(excluded)} 个"
          f"（已用角色池 {len(pool['characters'])}/{POOL_SIZE}，"
          f"模型 {_mk_now} 门控黑名单 {len(_model_gate)} 个，"
          f"共 {len(gate_blacklist)} 个模型）")
    print(f"[联网搜索] {'启用' if WEB_SEARCH_ENABLED else '关闭'}"
          f"（本地 function tool，引擎={'/'.join(available_engines())}，"
          f"最多 {WEB_SEARCH_MAX_ROUNDS} 轮，每次 {WEB_SEARCH_MAX_RESULTS} 条）")
    print(f"[网页抓取] {'启用' if WEB_FETCH_ENABLED else '关闭'}")
    print(f"[重试配置] max_attempts={RETRY_MAX_ATTEMPTS}, "
          f"base_delay={RETRY_BASE_DELAY}s, "
          f"max_delay={RETRY_MAX_DELAY}s, "
          f"jitter={RETRY_JITTER}")

    # 降权结果回传选题（2026-10-12）：该模型下多次不达标的主题 → 明确要求避开
    _avoid_themes = []
    try:
        _avoid_themes = comfy_runner.low_weight_themes(
            _cfg.model_key(workflow), _cfg.IDENTITY_JUDGE_WEIGHT_FLOOR)
        if _avoid_themes:
            print(f"  [选题避让] {_cfg.model_key(workflow)} 下已降权主题（要求避开）：{_avoid_themes}")
    except Exception:
        _avoid_themes = []
    print("[第1次调用] 选角色和主题（联网搜索 + 人物范围门控）……")
    char_info, gate_reason = None, ""
    last_reject, last_char = "", {}
    swaps = 0
    alt_why = []
    # 非 danbooru 系模型（Z-Image）是"模型级"限制：不管换什么角色都画不好，
    # 所以只试 1 次就换工作流，不烧 3 次选角
    attempts_per_round = (CHARACTER_GATE_ATTEMPTS
                          if WORKFLOW_MODEL_INFO.get(workflow, {}).get("danbooru_based")
                          else 1)
    while char_info is None:
        for attempt in range(1, attempts_per_round + 1):
            try:
                cand = ask_ai_character(
                    excluded, target_model=target_model,
                    range_hint=_model_range_hint(workflow),
                    reject_reason=last_reject,
                    allow_seasonal=(workflow in _cfg.SEASONAL_WORKFLOWS),
                    avoid_themes=_avoid_themes,
                )
            except Exception as e:
                print(f"[选角失败] {e}\n[中断] 未产出，未记录。")
                return

            name_en_try = (cand.get("name_en") or "").strip()
            series_en_try = (cand.get("series_en") or "").strip()
            # 门控**之前**先规范化（2026-10-11 补）：否则门控拿别名去查本地标签表会查不到
            try:
                from character_gate import canonical_tag as _ct
                _c1 = _ct(name_en_try)
                if _c1 and _c1 != name_en_try:
                    print(f"  [标签规范化·门控前] 角色 {name_en_try} → {_c1}")
                    name_en_try = _c1
                    cand["name_en"] = _c1
                _c2 = _ct(series_en_try)
                if _c2 and _c2 != series_en_try:
                    print(f"  [标签规范化·门控前] 作品 {series_en_try} → {_c2}")
                    series_en_try = _c2
                    cand["series_en"] = _c2
            except Exception:
                pass
            # ★ 注意：此处**主题尚未定稿**（主题在第 2 次 LLM 调用后才确定）→ 绝不能引用 theme，
            #   否则 NameError 会打断整条流水线（2026-10-14 我犯过这个错）。
            #   这里用"候选自带主题"；取不到就传 None（跳过体型判据，不影响其它门控）
            _t_gate = str(cand.get("theme") or "").strip() or None
            _llm_debut = cand.get("debut_date") or cand.get("debut_year")
            if name_en_try and name_en_try in excluded:
                ok, why = False, (f"{name_en_try} 已在本线排除名单"
                                  f"（跳过重复门控，直接换人）")
            else:
                ok, why = accepts(workflow, name_en_try, series_en_try,
                                  name_cn=(cand.get("name") or "").strip(),
                                  series_cn=(cand.get("series") or "").strip(),
                                  theme=_t_gate,        # 方案B：体型×暴露主题 组合判定需要主题
                                  llm_debut=_llm_debut)  # 2026-10-21：LLM 日期兜底
            # 角色 × 模型 黑名单（2026-10-12）：该角色在此模型上反复不达标 → 直接打回换人
            if ok and comfy_runner.char_blacklisted(_cfg.model_key(workflow), name_en_try):
                ok = False
                why = (f"{name_en_try} 在 {_cfg.model_key(workflow)} 下已被拉黑"
                       f"（反复不达标）→ 请换一个完全不同的角色")
            print(f"  [门控 {attempt}/{CHARACTER_GATE_ATTEMPTS}] {name_en_try} "
                  f"（{series_en_try}） → {'通过' if ok else '打回'}：{why}")
            if ok:
                # 2026-10-21 用户：**以模型为导向** —— 只在能画这个人物的模型里随机：
                #   通过 2/3 个基础模型 → 随机；1 个 → 不随机；
                #   选中 Anima-2.9B 后，再在通过的 api/anima_flow 里随机。
                try:
                    _alt, _alt_why = choose_workflow_for(
                        name_en_try, series_en_try, exclude=(),
                        name_cn=(cand.get("name") or "").strip(),
                        series_cn=(cand.get("series") or "").strip(),
                        theme=_t_gate, llm_debut=_llm_debut,
                        wf_filter=lambda _wf: not comfy_runner.char_blacklisted(
                            _cfg.model_key(_wf), name_en_try),
                        verbose=True)
                    if _alt:
                        if _alt != workflow:
                            print(f"  [模型导向] {workflow} → {_alt}（提示词/画师按最终模型重跑）")
                        workflow = _alt
                        target_model = WORKFLOW_MODEL_INFO.get(workflow, {}).get("label", workflow)
                        model_info = WORKFLOW_MODEL_INFO.get(workflow, {})
                        why = _alt_why
                except Exception as _e_pick:
                    print(f"  [模型导向] 跳过（{type(_e_pick).__name__}: {str(_e_pick)[:60]}）")
                char_info, gate_reason = cand, why
                # 2026-10-13 用户规则：Anima 线按**角色出道年**分两档画师策略
                #   ≤ FORCE_ARTIST_MAX_YEAR(2022) → 强制加画师（老角色还原度不够）
                #   ≥ 2023                        → 走 50% 随机（新角色还原没问题）
                # 年份从门控信息里解析（门控已联网/本地表核实过，是同一个数）
                # 方案 A：优先用 LLM 联网确认的角色出道日期（写入本地缓存）
                _llm_y = cand.get("debut_year")
                _llm_d = cand.get("debut_date")
                if _llm_y or _llm_d:
                    _saved = _cfg.set_char_debut_year(name_en_try, _llm_y, source="llm",
                                                      date=_llm_d)
                    if _saved:
                        print(f"  [出道日期] LLM 确认 {name_en_try} = {_llm_d or _saved} → 已写入本地缓存")
                # 取角色级年份：本地缓存优先 → 再退到门控同一套联网查询
                _yr, _scope = None, None
                try:
                    _yr = _cfg.char_debut_year(name_en_try)
                    if _yr:
                        _scope = "character"
                except Exception:
                    _yr = None
                if not _yr:
                    try:
                        import character_gate as _cgx
                        _w = _cgx.web_character_info(name_en_try, series_en_try,
                                                     (cand.get("name") or "").strip(),
                                                     (cand.get("series") or "").strip())
                        _yr, _wd, _scope = _w.get("year"), _w.get("date"), _w.get("scope")
                        if not _yr and _wd:
                            try:
                                _yr = int(str(_wd)[:4])
                            except Exception:
                                _yr = None
                        if _scope == "character" and (_yr or _wd):
                            _cfg.set_char_debut_year(name_en_try, _yr, source="web", date=_wd)
                    except Exception as _e:
                        print(f"  [画师策略] 年份查询异常：{type(_e).__name__}")
                # 2026-10-13 修（用户指出日志误导）：画师串只对 ARTIST_TAGS_WORKFLOWS
                # （api / anima_flow）生效；SDXL 两线（animagine_xl / nova_xl）**不注入画师**，
                # 所以这些线上不该打印"强制加画师"，也不该设 FORCE_ARTIST_OVERRIDE。
                if workflow not in _cfg.ARTIST_TAGS_WORKFLOWS:
                    _cfg.FORCE_ARTIST_OVERRIDE = None
                    _cfg.NO_ARTIST_OVERRIDE = None
                    print(f"  [画师策略] {workflow} 不吃画师串（仅 Anima 两条线支持）→ 本线跳过"
                          f"（已记录出道年 {_yr}，供门控/统计用）")
                elif _scope == "character" and _yr:
                    # 2026-10-14 用户规则：**只把强制线从 2022 缩到 2021**；2022+ 仍走原有 50% 随机
                    _cfg.FORCE_ARTIST_OVERRIDE = (_yr <= _cfg.FORCE_ARTIST_MAX_YEAR)
                    _cfg.NO_ARTIST_OVERRIDE = None
                    _tier = ("老角色(≤%d)：**强制加画师**" % _cfg.FORCE_ARTIST_MAX_YEAR
                             if _cfg.FORCE_ARTIST_OVERRIDE
                             else "新角色(≥%d)：不强制 → 走 50%% 随机（原逻辑）"
                                  % getattr(_cfg, "NO_ARTIST_MIN_YEAR", 2022))
                    print(f"  [画师策略] 角色级出道年 {_yr} → {_tier}")
                else:
                    _cfg.FORCE_ARTIST_OVERRIDE = None
                    _cfg.NO_ARTIST_OVERRIDE = None
                    print(f"  [画师策略] 未取到角色级年份（scope={_scope}）→ 走 50% 随机（原逻辑）")
                break
            last_reject = why
            last_char = {"name_en": name_en_try, "series_en": series_en_try,
                         "name": (cand.get("name") or "").strip(),
                         "series": (cand.get("series") or "").strip(),
                         "debut_date": cand.get("debut_date"),
                         "debut_year": cand.get("debut_year")}
            # 门控拒绝：立刻标记到本线排除名单，并写入本次 excluded。
            # 下一轮 ask_ai_character 会明确避开；模型若仍返回同一人，
            # 上面的 excluded 检查会直接换人，不再重复消耗门控调用。
            if _mark_gate_rejected(gate_blacklist, excluded, cand, name_en_try,
                                   series_en_try, why, _scope_now,
                                   _cfg.model_key(workflow), workflow=workflow):
                try:
                    save_json(GATE_REJECT_FILE, gate_blacklist)
                    print("  [门控拉黑] 已写入 gate_rejected.json"
                          "（按模型隔离、独立持久）")
                except Exception as _e_pool:
                    print(f"  [门控拉黑] 写黑名单失败：{type(_e_pool).__name__}")

        if char_info:
            break

        # 连续打回 → 该模型画不好这类角色：**当场换一条认识他的工作流继续**，
        # 不浪费整轮（尤其 Z-Image 这类非 danbooru 系，基本必被打回）
        if swaps >= MAX_WORKFLOW_SWAPS:
            print(f"[舍弃此人物] 已换过 {swaps} 次工作流仍无人能保证还原度：")
            for r in (alt_why or [])[:6]:
                print(f"    - {r}")
            print("[中断] 请重新运行换人"
                  "（config.CHAR_POP_OLD_MIN / CHAR_POP_NEW_MIN 也可放宽）")
            return

        old_wf, old_model = workflow, target_model
        alt, alt_why = choose_workflow_for(last_char.get("name_en", ""),
                                          last_char.get("series_en"),
                                          exclude=(workflow,),
                                          name_cn=last_char.get("name"),
                                          series_cn=last_char.get("series"),
                                          theme=_t_gate,
                                          llm_debut=(last_char.get("debut_date")
                                                     or last_char.get("debut_year")),
                                          wf_filter=lambda _wf: not comfy_runner.char_blacklisted(
                                              _cfg.model_key(_wf),
                                              last_char.get("name_en", "")),
                                          verbose=True)
        if not alt:
            print(f"[舍弃此人物] {last_char.get('name_en', '')} 没有任何工作流能保证还原度：")
            for r in (alt_why or [])[:6]:
                print(f"    - {r}")
            print("[中断] 请重新运行换人")
            return

        swaps += 1
        workflow = alt
        model_info = WORKFLOW_MODEL_INFO.get(workflow, {})
        target_model = model_info.get("label", workflow)
        last_reject = (f"上一个模型（{old_model}）不认识你上次选的角色，"
                       f"现在改由 {target_model} 出图，请重新选一个该模型认识的热门角色")
        print(f"[换工作流 {swaps}/{MAX_WORKFLOW_SWAPS}] {old_wf} → {workflow}"
              f"（{target_model}）：{alt_why}")

    print(f"[门控通过] {gate_reason}")

    name = char_info.get("name", "").strip()
    series = char_info.get("series", "").strip()
    name_en = char_info.get("name_en", "").strip()
    series_en = char_info.get("series_en", "").strip()
    theme = char_info.get("theme", "").strip()

    # ---- A：角色/作品标签规范化（2026-10-11）----
    # 用本地 danbooru 别名表把 LLM 给的名字纠正成**官方标签**，再进后续所有环节
    # （门控查投稿数、提示词标签都用规范后的值；标签写错 = 底模不认识 = 脸不像）
    try:
        from character_gate import canonical_tag
        cn = canonical_tag(name_en)
        if cn and cn != name_en:
            print(f"[标签规范化] 角色 {name_en} → {cn}")
            name_en = cn
        cs = canonical_tag(series_en)
        if cs and cs != series_en:
            print(f"[标签规范化] 作品 {series_en} → {cs}")
            series_en = cs
    except Exception as e:
        print(f"[标签规范化] 跳过（{type(e).__name__}）")

    if not (name and name_en and theme):
        print(f"[选角异常] 关键字段缺失：name={name!r}, name_en={name_en!r}, theme={theme!r}")
        print(f"[选角异常] 完整返回：{char_info}")
        print("[中断] 未产出，未记录。")
        return

    print(f"[今日角色] {name}（{series}）")
    print(f"  英文标签：{name_en}, {series_en}")
    print(f"  主题：{theme}")

    # ---- 四季常装（2026-10-11；2026-10-14 用户要求扩大到**全部四条线路**）----
    # 主题命中"四季常装"时按**当天日期**定季节，把该季节的常服 + 场景作为硬要求注入，
    # 并禁止泳装/海滩（非该主题一律不动）。作用域由 config.SEASONAL_WORKFLOWS 控制。
    theme_display = theme
    prompt_theme = theme          # ← 必须先定义：下面四季块/外观块都在它基础上追加
    try:
        _sg = _cfg.seasonal_guide(theme, workflow)
        if _sg:
            _season, _g, theme_display = _sg
            # 2026-10-19：按线路覆盖（只对表里列出的线路；列表则随机取一项）
            _ovl = (getattr(_cfg, "SEASONAL_OVERRIDE_BY_LINE", {}) or {}).get(workflow, {})
            if _ovl:
                import random as _rnd
                _g = dict(_g)          # 副本，避免污染共享的四季配置
                for _k, _v in _ovl.items():
                    _g[_k] = _rnd.choice(_v) if isinstance(_v, (list, tuple)) else _v
                print(f"[按线路覆盖] {workflow}：场景/姿势/光照按本线配置（不影响其它线）")
            print(f"[四季常装] 今天属【{_season}】季 → 按{_season}季常装出装"
                  f"（展示主题：{theme_display}）")
            # 2026-10-21 审计：四季常装的姿势会被下方强制块改成上半身
            #   → Anima 两线的景别必须跟着收紧，否则 `full body` 会与
            #   `waist-up composition, upper body framing` 直接对撞。
            #   实验用的 FRAMING_OVERRIDE 优先，不在这里覆盖。
            if (workflow in ("api", "anima_flow") and not _cfg.FRAMING_OVERRIDE
                    and str(framing).strip().lower() == "full body"):
                framing = "cowboy shot"
                print(f"[四季常装] {workflow} 景别随上半身姿势收紧：full body → cowboy shot")
            prompt_theme = (prompt_theme + "\n"
                            f"【{_season}季常装要求（硬约束）】这是日常常装主题：\n"
                            f"  服装：{_g['outfit']}\n"
                            f"  设计感/材质（必须体现）：{_cfg.SEASONAL_DESIGN_RULES}\n"
                            f"  场景：{_g['scene']}\n"
                            f"  场景加权（写进正向时带权重）：{_g['weighted']}\n"
                            f"  姿势/构图（必须体现，禁止正面站直）：{_g['pose']}\n"
                            f"  负面必须包含：{_g['negative']}；{_cfg.SEASONAL_POSE_NEGATIVE}")
    except Exception as e:
        print(f"[四季常装] 跳过（{type(e).__name__}）")

    # 2026-10-22 用户景别策略：默认 cowboy shot + upper body；full body 只给
    #   泳装/礼服/动作这类主题。实验用 FRAMING_OVERRIDE / ANIMA_FRAMING_TIER 优先。
    try:
        if not _cfg.FRAMING_OVERRIDE and getattr(_cfg, "ANIMA_FRAMING_TIER", None) is None:
            _old_fr = framing
            framing = _cfg.choose_framing(theme, workflow)
            print(f"[景别策略] {theme} → {framing}（原：{_old_fr or '无'}）")
    except Exception as _e_fr:
        print(f"[景别策略] 跳过（{type(_e_fr).__name__}）")

    # ---- B：外观标签挖掘（2026-10-11）----
    # 从 safebooru 该角色的真实二创帖里挖高频外观标签，作为【已核实事实】交给 LLM 筛选。
    # 不直接写进提示词：多角色同框帖会带进 blonde_hair 之类的**冲突噪音**，
    # 而 LLM 知道官方发色，能自动丢掉噪音、同时补上它不知道的冷门细节（如 drop-shaped_pupils）。
    # 2026-10-21：**不再**在这里 `prompt_theme = theme` —— 那会把上面刚拼好的四季硬约束
    #   整体复位，LLM 从没看到过当季服装/场景/姿势。外观标签改为追加到同一串。
    try:
        from booru_client import appearance_tags
        _hints = appearance_tags(name_en, sample=40)
        if _hints:
            # 只给前 10 个（缩短输入、避免推理膨胀把输出预算吃光）
            _top = _hints[:10]
            prompt_theme = (
                f"{prompt_theme}\n"
                f"【已核实的该角色高频创作标签（来自真实二创）】{', '.join(_top)}\n"
                f"要求：从这些标签里挑选与该角色**官方设定一致**的作为外观锚点；"
                f"与官方发色/瞳色冲突的属于多角色同框图噪音，**必须忽略**。"
            )
            print(f"[外观标签] 注入 {len(_top)} 个已核实标签供 LLM 筛选"
                  f"（{', '.join(_top[:6])}…）")
    except Exception as e:
        print(f"[外观标签] 跳过（{type(e).__name__}）")

    # ---- 主题训练量门槛（2026-10-12）----
    # 主题不随训练量走 → 低量主题必崩（实测雷神：kimono 2520 张 vs swimsuit 70 张）。
    # 规则：角色×主题共现量需同时满足 绝对量≥150 且 占比≥3%；不达标则回退到候选里量最大的主题。
    try:
        from booru_client import theme_volume, character_total
        _t_tag = _cfg.THEME_TAG_MAP.get(theme, "")
        if not _t_tag:
            for _k, _v in _cfg.THEME_TAG_MAP.items():
                if _k in theme:
                    _t_tag = _v
                    break
        if _t_tag:
            _total = character_total(name_en)
            _vol = theme_volume(name_en, _t_tag)
            _ratio = (_vol / _total) if (_total and _total > 0 and _vol >= 0) else 0
            _ok = (_vol >= _cfg.THEME_GATE_MIN_POSTS) and (_ratio >= _cfg.THEME_GATE_MIN_RATIO)
            print(f"[主题门槛] {name_en} × {theme}(={_t_tag}): 共现 {_vol} 张 / 角色总量 {_total}"
                  f" = {_ratio*100:.1f}%  → {'放行' if _ok else '低于参考线'}"
                  + ("" if _cfg.THEME_GATE_SWAP else "（仅记录，不换主题）"))
            if (not _ok) and _cfg.THEME_GATE_SWAP:
                _best, _best_vol = "", -1
                for _c in _cfg.THEME_CANDIDATES:
                    _v2 = theme_volume(name_en, _c)
                    print(f"   候选 {_c:<16} {_v2} 张")
                    if _v2 > _best_vol:
                        _best, _best_vol = _c, _v2
                _bt = (_best_vol / _total) if (_total and _total > 0) else 0
                if _best_vol >= _cfg.THEME_GATE_MIN_POSTS and _bt >= _cfg.THEME_GATE_MIN_RATIO:
                    _cn = {v: k for k, v in _cfg.THEME_TAG_MAP.items()}.get(_best, _best)
                    print(f"  [主题门槛] 换主题：{theme} → {_cn}（{_best} {_best_vol} 张，"
                          f"{_bt*100:.1f}%，训练量达标）")
                    theme = _cn
                    prompt_theme = theme
                    theme_display = theme
                else:
                    print(f"  [主题门槛] 无达标候选（最高 {_best} {_best_vol} 张）→ 保留原主题")
    except Exception as e:
        print(f"[主题门槛] 跳过（{type(e).__name__}）")

    _cfg.THEME_CTX = str(theme or "")   # 2026-10-18：供 comfy_runner 判断换装主题
    print(f"[第2次调用] 生成提示词（景别={framing}，联网搜索）……")
    structured = None
    for _try in range(PROMPT_SELFCHECK_RETRIES + 1):
        try:
            structured = ask_ai_prompt(
                name, series, name_en, series_en, prompt_theme,
                framing=framing, workflow=workflow,
            )
        except Exception as e:
            # 兜底（2026-10-12）：若是 reasoning 吃满预算导致的空输出，
            # **不原样重试**，而是去掉附加注入（外观标签/季节约束）缩短输入后再试一次
            if globals().get("LAST_EMPTY_BUDGET_EXHAUSTED") and prompt_theme != theme:
                print("  [兜底] 上次空输出系 reasoning 吃满预算 → 去掉附加注入、缩短输入后重试")
                prompt_theme = theme
                globals()["LAST_EMPTY_BUDGET_EXHAUSTED"] = False
                continue
            print(f"[提示词生成失败] {e}\n[中断] 未产出，未记录。")
            return
        ok, why = _prompt_selfcheck(structured, name_en, series_en, theme)
        hard = [w for w in why if not w.startswith("警告")]
        warn = [w for w in why if w.startswith("警告")]
        if warn:
            print(f"[提示词自检·提示] {'、'.join(warn)}")
        if ok:
            print(f"[提示词自检] 通过（第 {_try + 1} 次）")
            break
        print(f"[提示词自检] 不合格：{'、'.join(hard)}"
              + ("→ 重新生成一次" if _try < PROMPT_SELFCHECK_RETRIES else "→ 已用尽重试，按现状继续"))

    # 2026-10-23 用户：Nova 的场景主题走“自由换装”，Animagine 保留官方服装锁。
    try:
        if (structured and str(theme or "") in tuple(getattr(_cfg, "SCENE_ONLY_THEMES", ()) or ())
                and workflow != "nova_xl"):
            _official = (getattr(_cfg, "CHAR_OFFICIAL_OUTFIT", {}) or {}).get(name_en)
            if _official:
                structured["outfit"] = _official
                print(f"[原装锁定] {name_en} × {theme} → 官方服装（只换背景）")
        elif structured and str(theme or "") in tuple(getattr(_cfg, "SCENE_ONLY_THEMES", ()) or ()):
            print(f"[自由换装] Nova × {theme} → 不锁官方服装，交给 LLM/主题")
    except Exception as _e_off:
        print(f"[原装锁定] 跳过（{type(_e_off).__name__}）")

    # ---- 四季常装：**确定性强制**（2026-10-12）----
    # 实测：把季节要求写进"主题"字符串会被 LLM 忽略（出图元数据里加权场景词/反季负面全都没有）
    # → 改为结构化返回后由**代码强制写入**，不依赖 LLM 自觉（与 eye_lock/角色锚点同一思路）。
    try:
        _sg2 = _cfg.seasonal_guide(theme, workflow)
        if _sg2 and isinstance(structured, dict):
            _se, _gd, _ = _sg2
            print(f"[四季常装·强制] structured 字段: {list(structured.keys())}")

            def _add(field, text):
                if not text:
                    return
                cur = str(structured.get(field) or "").strip()
                if text.split(",")[0].strip().lower() in cur.lower():
                    return
                structured[field] = (cur + ", " + text).strip(", ") if cur else text

            _hit_scene = False
            # 真实字段名（2026-10-12 实测）：scene_foreground / scene_midground / scene_background
            for _k in ("scene_background", "scene_midground", "scene_foreground",
                       "scene", "background", "environment"):
                if _k in structured:
                    _add(_k, _gd["weighted"])
                    _hit_scene = True
                    break
            if not _hit_scene:
                _add("scene_background", _gd["weighted"])
            # === 覆盖式强制（2026-10-12 v3）===
            # 实测：追加式会与 LLM 打架 —— LLM 写"戏服/礼服/高跟靴 + 正面全身 + 手放胸前"，
            # 与强制的"秋装 + 侧坐端杯"矛盾 → **冲突比缺失更伤质量**（美学分掉到 2.27）。
            # 因此：姿势整体**覆盖**；服装只在"明显跑偏"时覆盖（否则保留 LLM 按角色配色改写的版本）。
            _conflict = (r"(?i)\b(standing|standing straight|walking|leaning against|"
                         r"hand on [a-z ]{0,14}|fingers touching [a-z ]{0,14}|"
                         r"full body|from front|front view|one graceful pose|"
                         r"symmetrical composition)\b,?\s*")
            for _pf in ("pose", "composition"):
                if structured.get(_pf):
                    structured[_pf] = re.sub(_conflict, "", str(structured[_pf])).strip(", ")
            structured["pose"] = _gd["pose"]                    # ← 姿势覆盖
            # ===== 修 III v2（2026-10-17）：**全局**清除"环境/远景"导向词 + 光照压缩 =====
            #   上一版只清了 composition/depth，实测 cinematic composition / detailed background /
            #   lens flare 仍出现在 4/4 的提示词里 ✗ → 改为对所有字段做一次统一清理
            _ENV_WORDS = (r"cinematic composition|dynamic angle|detailed background|lens flare|"
                          r"depth of field|environmental portrait|scenery")
            for _fk in list(structured.keys()):
                if _fk == "negative":
                    continue
                _fv = structured.get(_fk)
                if isinstance(_fv, str) and _fv:
                    _nv = re.sub(r"(?i)\b(%s)\b,?\s*" % _ENV_WORDS, "", _fv).strip(", ")
                    if _nv != _fv:
                        structured[_fk] = _nv
            # 光照压缩到最多 2 个短语（原来 5~8 个如"god rays/warm rim light/dappled shadows…"）
            _lt = str(structured.get("lighting") or "")
            if _lt:
                _ls = [x.strip() for x in _lt.split(",") if x.strip()]
                structured["lighting"] = ", ".join(_ls[:2]) if _ls else ""
                print("[四季常装·强制] 光照压缩 → %s" % structured["lighting"])
            print("[四季常装·强制] 已全局清除环境/远景导向词（cinematic/detailed background/…）")

            # ===== 旧"复杂双眼→近景"块已删除（2026-10-18）=====
            #   用户已要求：复杂双眼不特殊处理、构图统一收紧 →
            #   景别由**前面的统一分支**决定（SDXL 两线 = SDXL_CROP_FRAMING），
            #   这里**不得再给 framing 赋值**，否则会覆盖先进分支的值（这就是"收紧不生效"的真因）
            # ===== SDXL 两线的三项修复（2026-10-18）=====
            #   ① 防黄：光照改中性 + 负面压制暖色偏
            #   ② 防黄：负面压制暖色偏；防幼体型负面统一由后面的 body_type 档位块处理
            if workflow == "animagine_xl":   # 2026-10-18 回滚：nova 不再加这些修复
                try:
                    structured["lighting"] = _cfg.SDXL_NEUTRAL_LIGHT
                    _neg0 = str(structured.get("negative") or "")
                    _extra = str(getattr(_cfg, "SDXL_SKIN_NEGATIVE", "") or "")
                    structured["negative"] = ((_neg0 + ", ") if _neg0 else "") + _extra
                    print("[SDXL修复] 光照→中性；负面加防黄")
                except Exception as _e3:
                    print(f"[SDXL修复] 跳过（{type(_e3).__name__}）")

            # 2026-10-21：按线路的 lighting 覆盖（原来只写进 _g、从未落盘 → 死键）
            #   放在 SDXL 防黄修复之后：本线配置优先（animagine 的串里也带 natural skin tone）
            _line_light = str(_gd.get("lighting") or "").strip()
            if _line_light:
                structured["lighting"] = _line_light
                print(f"[四季常装·强制] 光照按本线覆盖 → {_line_light[:48]}")

            # ===== 2026-10-19：剥离独立作品标签（治游戏 LOGO 贴图；仅 SDXL 两线）=====
            try:
                if workflow in ("animagine_xl", "nova_xl"):
                    _brands = ("genshin impact", "genshin_impact", "honkai: star rail",
                               "honkai:_star_rail", "honkai star rail", "vocaloid", "blue archive")
                    for _fk in ("appearance", "core_features", "subject"):
                        _v = str(structured.get(_fk) or "")
                        if not _v:
                            continue
                        _ls = [x.strip() for x in _v.split(",") if x.strip()]
                        _kept = [x for x in _ls
                                 if not any(x.lower().strip() == b for b in _brands)]
                        if len(_kept) != len(_ls):
                            structured[_fk] = ", ".join(_kept)
                            print(f"[作品标签剥离] {_fk}: 删掉 {len(_ls)-len(_kept)} 个独立作品标签")
            except Exception as _eb:
                print(f"[作品标签剥离] 跳过（{type(_eb).__name__}）")

            # ===== 2026-10-19：角色标签去作品名（治游戏 LOGO；仅 SDXL 两线）=====
            #   `furina_(genshin_impact)` → `furina`；作品标签只保留给检索/门控
            try:
                if workflow in ("animagine_xl", "nova_xl"):
                    import re as _re_ch
                    for _fk in ("subject", "appearance", "core_features", "face_priority"):
                        _v = str(structured.get(_fk) or "")
                        if not _v or "_(" not in _v:
                            continue
                        _new = _re_ch.sub(r"([A-Za-z0-9_]+)_\([^()]*\)", r"\1", _v)
                        if _new != _v:
                            structured[_fk] = _new
                            print(f"[作品名剥离] {_fk}: 角色标签已去作品名")
            except Exception as _ec:
                print(f"[作品名剥离] 跳过（{type(_ec).__name__}）")

            # ===== 角色瞳色锚定（2026-10-18 方案 A）=====
            #   LLM 有时把异色瞳简化成单色 → 命中缓存则**强制覆盖** eye_colors，
            #   并从 core_features/appearance 里剔除单色眼标签（保留发型/头饰）
            try:
                # 2026-10-19 用户："nova 去掉眼睛相关的补强措施" → 眼部锚定只对 animagine 生效
                _eye_enh = workflow in getattr(_cfg, "EYE_ENHANCE_WORKFLOWS", ())
                # 2026-10-20：LLM 没写 heterochromia 的角色（如三月七）不做锚定覆盖
                _llm_eye = str(structured.get("eye_colors") or "")
                if _eye_enh and "heterochromia" not in _llm_eye.lower():
                    _eye_enh = False
                    print(f"[瞳色锚定] {name_en} 非异色瞳 → 不覆盖（保留 LLM 写法）")
                    _anchor = _cfg.char_eye_anchor(name_en, simple=False)   # 完整左右分色写法
                else:
                    _anchor = None
                if _anchor:
                    _old = str(structured.get("eye_colors") or "")
                    structured["eye_colors"] = _anchor
                    print(f"[瞳色锚定] {name_en} → {_anchor}（原: {_old[:40] or '空'}）")
                    if "heterochromia" in _anchor.lower():
                        _eye_re2 = re.compile(r"(?i)^(light |dark |pale |deep |bright )?"
                                              r"(red|blue|green|purple|violet|aqua|teal|yellow|"
                                              r"orange|pink|gold|amber|grey|gray|brown) eyes?$")
                        for _fk2 in ("core_features", "appearance", "face_priority"):
                            _v2 = str(structured.get(_fk2) or "")
                            if not _v2:
                                continue
                            _keep2 = [x.strip() for x in _v2.split(",")
                                      if x.strip() and not _eye_re2.match(x.strip())]
                            if len(_keep2) != len([x for x in _v2.split(",") if x.strip()]):
                                structured[_fk2] = ", ".join(_keep2)
            except Exception as _e2:
                print(f"[瞳色锚定] 跳过（{type(_e2).__name__}）")

            # 2026-10-21：换装剥离/加权/官方服装负面已提到 `if _sg2` 外，统一由
            #   `_apply_outfit_swap()` 在所有换装主题上执行（且在当季服装覆盖之后）。

            # ===== 修 I / III（2026-10-17，用户反馈"上半身维持不住"）=====
            #  I) 姿势改成**上半身可完成**：原 config 姿势含 "both feet resting on the ground /
            #     knees together" → 与近景 `upper body` 直接互斥（必须画脚=全身）✗
            _pose_ub = ("one hand touching hair, slight three-quarter turn, shoulders relaxed, "
                        "waist-up composition, upper body framing")
            structured["pose"] = _pose_ub
            _add("composition", _pose_ub)
            # III) 场景**替换**而不是追加：原来把 LLM 的 9~13 个环境词全保留 → 镜头被推远 ✗
            #      只留按季节加权过的 2~4 个氛围/环境锚点
            for _sk in ("scene_foreground", "scene_midground", "scene_background",
                        "scene", "background", "environment"):
                structured.pop(_sk, None)
            structured["scene_background"] = _gd["weighted"]
            # 环境导向构图词一并去掉（cinematic composition / dynamic angle /
            # detailed background / lens flare ≈ "给我一个远景环境"）
            for _ck in ("composition", "depth"):
                _cv = str(structured.get(_ck) or "")
                if _cv:
                    structured[_ck] = re.sub(
                        r"(?i)\b(cinematic composition|dynamic angle|detailed background|"
                        r"lens flare)\b,?\s*", "", _cv).strip(", ")
            _off = str(structured.get("outfit") or "")
            # 2026-10-23 用户：四季常装不强制固定服装（大衣/毛衣/围巾不再硬覆盖）
            if getattr(_cfg, "SEASONAL_OUTFIT_FORCE", False):
                structured["outfit"] = _gd["outfit"] + ", " + _cfg.SEASONAL_DESIGN_RULES
                print("[四季常装·强制] 服装**一律覆盖**为当季常装（含默认服装标志词清理）")
                # 默认服装标志词清理：**只清服装类**（外套/礼服/制服/甲胄…）
                #   2026-10-17 用户选 B：**保留角色标志性头部配饰**（帽子/耳麦/发饰 = 身份锚点）
                #   → `top hat` 等头部饰物**不再清除**；"超大帽子/举在头顶"由既有负面约束拦 ✓
                for _fk in ("appearance", "core_features", "body"):
                    _fv = str(structured.get(_fk) or "")
                    if _fv:
                        _new = re.sub(r"(?i)\b(theatrical|costume|tailcoat|tuxedo|gown|"
                                      r"uniform|armor|evening dress|kimono|sleeveless shirt)\b,?\s*",
                                      "", _fv).strip(", ")
                        if _new != _fv:
                            structured[_fk] = _new
                            print("[四季常装·强制] 清除服装类默认词（保留帽子/头饰）")
            # 坐姿 + "long legs" 叠加会放大腿长比例失真 → 坐姿时去掉该标签（2026-10-12）
            if "sitting" in _gd["pose"] and "body" in structured:
                _bd = str(structured.get("body") or "")
                if re.search(r"(?i)\blong legs\b", _bd):
                    structured["body"] = re.sub(r"(?i)\blong legs\b,?\s*", "", _bd).strip(", ")
                    print("[四季常装·强制] 坐姿 → 已去掉 body 里的 long legs（防腿型失真）")
            # 2026-10-17 修（用户反馈"构图不符合之前的要求"）：
            #   SDXL 上仅有正向 `upper body` 会被"公园长椅/庭院/坐姿"等场景词拉成全身 ✗
            #   ⇒ 四季常装主题下，负面**额外压制全身/远景**，把构图钉在近景半身
            _neg_add = (_gd["negative"] + ", " + _cfg.SEASONAL_POSE_NEGATIVE
                        + ", full body, full-length, wide shot, feet visible, "
                          "standing legs visible, distant view, zoomed out")
            if ("negative" in structured) or ("negatives" in structured):
                _add("negative" if "negative" in structured else "negatives", _neg_add)
            else:
                _add("negative", _neg_add)
            print(f"[四季常装·强制] 已写入 场景加权/姿势构图/设计感/反季负面（{_se}季）")

            # 正面反季词清理（2026-10-12）：LLM 会主动写反季元素（实测秋季写了
            # "blue hydrangea flower bed"）→ 从**正向各字段**里删掉反季词（负面不动）。
            _anti = {
                "秋": ("hydrangea", "cherry blossom", "spring", "green leaves",
                       "blue flower", "wildflower", "blossom", "sunflower",
                       "morning glory", "lotus", "blooming flower"),
                "春": ("autumn leaves", "maple", "ginkgo", "snow"),
                "夏": ("autumn leaves", "snow", "ginkgo", "maple"),
                "冬": ("cherry blossom", "hydrangea", "green leaves", "sunflower"),
            }.get(_se, ())
            if _anti:
                _removed = set()
                for _k2, _v2 in list(structured.items()):
                    if _k2 in ("negative", "negatives") or not isinstance(_v2, str) or not _v2:
                        continue
                    _nv = _v2
                    for _w in _anti:
                        _new = re.sub(r"(?i)\b[\w-]*" + re.escape(_w) + r"[\w-]*\b,?\s*", "", _nv)
                        if _new != _nv:
                            _removed.add(_w)
                            _nv = _new
                    structured[_k2] = _nv.strip(", ")
                if _removed:
                    print(f"[四季常装·强制] 正面清除反季词: {sorted(_removed)}")
    except Exception as e:
        print(f"[四季常装·强制] 跳过（{type(e).__name__}）")

    # 2026-10-21 用户：animagine 后续角色体型必须按官方设定（不能一律成女/幼态）
    #   body_type（LLM）→ 体型档位；per-char 覆盖（Furina/Miku）优先
    try:
        if workflow == "animagine_xl" and isinstance(structured, dict):
            _bt_in = str(structured.get("body_type") or "")
            _body_txt = str(structured.get("body") or "")
            _anchor_b, _neg_kind, _bt = _cfg.animagine_body_profile(
                _bt_in, name_en, _body_txt)
            if _anchor_b:
                _app = str(structured.get("appearance") or "")
                if _anchor_b.split(",")[0].strip().lower() not in _app.lower():
                    structured["appearance"] = (
                        (_app + ", ") if _app else "") + _anchor_b
                    print(f"[体型] body_type={_bt} → 追加：{_anchor_b}")
            _nk = ("negative" if "negative" in structured
                   else ("negatives" if "negatives" in structured else "negative"))
            _nv0 = str(structured.get(_nk) or "")
            _add_neg = []
            if _neg_kind == "adult":
                if "childlike proportions" not in _nv0.lower():
                    _add_neg.append(getattr(_cfg, "SDXL_BODY_NEGATIVE", ""))
                if "baby face" not in _nv0.lower():
                    _add_neg.append(getattr(_cfg, "SDXL_AGE_NEGATIVE", ""))
            elif _neg_kind == "adult_petite":
                if "childlike proportions" not in _nv0.lower():
                    _add_neg.append(getattr(_cfg, "SDXL_BODY_NEGATIVE_PETITE", ""))
                if "baby face" not in _nv0.lower():
                    _add_neg.append(getattr(_cfg, "SDXL_AGE_NEGATIVE_PETITE", ""))
            elif _neg_kind == "teen":
                if "childlike proportions" not in _nv0.lower():
                    _add_neg.append(getattr(_cfg, "SDXL_TEEN_NEGATIVE", ""))
            elif _neg_kind == "child":
                if "mature female" not in _nv0.lower():
                    _add_neg.append(getattr(_cfg, "SDXL_CHILD_NEGATIVE", ""))
            _add_neg = [x for x in _add_neg if x]
            if _add_neg:
                structured[_nk] = ((_nv0 + ", ") if _nv0 else "") + ", ".join(_add_neg)
                print(f"[体型] body_type={_bt} → 负面档位：{_neg_kind}")
    except Exception as _e_body:
        print(f"[体型] 跳过（{type(_e_body).__name__}）")

    # ---- 提示词丰富度强制（2026-10-12 v2：针对"缺的那一层"叠加 + 字段长度上限）----
    # v1 只补"太短"的字段 → 净增益≈0（LLM 写得长但写得虚时判定失效）。
    # v2：改用**具体关键词**判定该层是否已写实；缺则叠加一层；字段达到上限就不再叠加（防膨胀）。
    try:
        if isinstance(structured, dict):
            _enriched = []
            for _f, _mk, _cap, _txt in _cfg.PROMPT_RICHNESS:
                _cur = str(structured.get(_f) or "").strip()
                if len(_cur) >= _cap:
                    continue                                   # 已达上限 → 不叠加
                _low = _cur.lower()
                if _mk and any(m in _low for m in _mk):
                    continue                                   # 该层已具体描述过
                _room = _cap - len(_cur) - 2
                # 去重（2026-10-12）：逐子句检查，概念已在本字段出现过的跳过（避免 blush/smile 重复）
                _keep = []
                for _p in [x.strip() for x in _txt.split(",") if x.strip()]:
                    _ws = [w for w in re.findall(r"[a-z]{5,}", _p.lower())]
                    if _ws and all(w in _low for w in _ws):
                        continue
                    _keep.append(_p)
                # 按**子句边界**累加：超空间就整体丢弃该子句（绝不切词 —— 修 rule-of-thir 截断 bug）
                _acc = []
                for _p in _keep:
                    if len(", ".join(_acc + [_p])) > _room:
                        break
                    _acc.append(_p)
                _t = ", ".join(_acc)
                if not _t.strip():
                    continue
                structured[_f] = (_cur + ", " + _t).strip(", ") if _cur else _t
                _enriched.append(f"{_f}(+{len(_t)})")
            if _enriched:
                print(f"[丰富度强制] 叠加层次: {_enriched}")
    except Exception as e:
        print(f"[丰富度强制] 跳过（{type(e).__name__}）")

    # ---- 表情/性格锁定（2026-10-12）----
    # 问题：所有角色都出微笑脸，神态不符人物性格（雷电将军应是威严/冷淡）。
    # 做法：用**真实二创表情标签**判定该角色的常态表情（数据驱动、不杜撰）：
    #   若"非笑容"标签占优 → 清除正/负里的微笑标签，并把笑容写进负面。
    try:
        from booru_client import expression_tags as _et
        _ex = [t.lower() for t in (_et(name_en, sample=40) or [])]
        if _ex:
            _smile = [t for t in _ex if ("smile" in t or "grin" in t or "open mouth" in t)]
            _serious = [t for t in _ex
                        if t in ("expressionless", "serious", "calm", "stoic", "frown",
                                 "pout", "glaring", "closed mouth", "half-closed eyes")]
            if _serious and len(_serious) > len(_smile):     # 必须**严格多于**笑容
                _strip = (r"(?i)\b(smiling|smile|grin|gentle smile|cheerful|happy|"
                          r"open mouth smile|grinning)\b,?\s*")
                for _f in ("expression", "expression_priority", "face_priority"):
                    if structured.get(_f):
                        structured[_f] = re.sub(_strip, "", str(structured[_f])).strip(", ")
                _add_neg = ("smiling, grin, cheerful, happy expression, "
                            "expressionless, blank stare, dead eyes, doll-like stare, "
                            "stiff expression, emotionless, lifeless eyes")
                if "negative" in structured:
                    _cur_n = str(structured.get("negative") or "")
                    if "smiling" not in _cur_n.lower():
                        structured["negative"] = (_cur_n + ", " + _add_neg).strip(", ")
                _keep = ", ".join(_serious[:3])
                structured["expression"] = (str(structured.get("expression") or "").strip(", ")
                                            + ", " + _keep).strip(", ")
                print(f"[表情锁定] 该角色二创以非笑容为主 → 清除微笑并锁定神态：{_keep}")
            else:
                print(f"[表情锁定] 该角色允许笑容（挖掘：{_ex[:4]}），不做更改")
    except Exception as e:
        print(f"[表情锁定] 跳过（{type(e).__name__}）")

    # ---- 外观特征强制 v3（2026-10-12，按你给的好图结构改）----
    # 好图样本实测：**加权五官特征紧跟在角色标签之后**（如 Nova 好图：
    #   `1girl, solo, hina \(blue archive\), (detailed face:1.15), (slender face:1.15),
    #    (narrow sharp eyes:1.15), (straight bangs framing face:1.15), (calm gaze:1.15)…`）
    # 而旧版把强制锚点**追加在末尾**（等于稀释）→ 改为：
    #   · 五官/发型类锚点 → 写进 **face_priority 并加权 1.15**（紧跟角色标签，影响力最大）
    #   · 配饰/服饰类锚点 → 仍写进 appearance（不加权）
    try:
        from booru_client import appearance_tags as _at2
        _ap2 = [t.lower().replace("_", " ") for t in (_at2(name_en, sample=40) or [])]
        structured["theme"] = theme      # ★ 2026-10-12：模板需要主题才能做"泳装↔默认服装"冲突过滤
        if _ap2:
            _face_anchors = ("mole under eye", "mole", "freckles", "scar", "blunt bangs",
                             "braid", "single braid", "sidelocks", "ahoge",
                             "hair between eyes", "hair over one eye", "sharp eyes")
            _fp = str(structured.get("face_priority") or "")
            _ap = str(structured.get("appearance") or "")
            _fp_low, _ap_low = _fp.lower(), _ap.lower()
            _moved = []
            for _t in _ap2:
                if _t in _fp_low:
                    continue
                if _t in _face_anchors:
                    if _t not in _ap_low or _t in _face_anchors:
                        # 平铺写入（2026-10-12：标杆实测**不带权重**，去掉 (xxx:1.15)）
                        _fp = (_fp + ", " + _t).strip(", ")
                        _fp_low += " " + _t
                        _moved.append(_t)
                elif _t not in _ap_low:
                    _ap = (_ap + ", " + _t).strip(", ")
                    _ap_low += " " + _t
                    _moved.append(_t)
            structured["face_priority"] = _fp
            structured["appearance"] = _ap
            if _moved:
                print(f"[外观强制] 五官类→face_priority(加权)、其余→appearance：{_moved[:8]}")

        # 角色标签"双写法"（转义 + 不转义）：好图样本同时使用两种写法 → 提高识别率
        _plain = (name_en or "").replace("_", " ")
        _cf = str(structured.get("core_features") or "")
        if _plain and _plain not in _cf:
            structured["core_features"] = (_plain + ", " + _cf).strip(", ")
            print(f"[标签双写法] 补入未转义角色标签：{_plain}")
    except Exception as e:
        print(f"[外观强制] 跳过（{type(e).__name__}）")

    # 2026-10-21：换装机制独立执行 —— 所有换装主题（含和服/婚纱/制服），
    #   放在「当季服装覆盖 + 外观挖掘」之后：这样 booru 新补的官方服装标签也会被剥离，
    #   wearing(...:1.5) 与 OUTFIT_SWAP_COVER 也不会再被冲掉。
    try:
        _sg_os = _cfg.seasonal_guide(theme, workflow)
        _apply_outfit_swap(structured, theme, name_en, workflow,
                           _sg_os[0] if _sg_os else None)
    except Exception as _e_os:
        print(f"[换装剥离] 跳过（{type(_e_os).__name__}）")

    # （A：Anima 线瞳色保障 已于 2026-10-12 撤销 —— 实测与不补的区别不大，用户决定不要）
    name_en_anima = _escape_anima(name_en)
    series_en_anima = _escape_anima(series_en)

    # ===== 2026-10-20 用户：全部主题的"背景太假" → 最终拼装前补真实场景细节 =====
    # 2026-10-21：提取为 `_apply_scene_details()`，写进模板真正读取的 scene_* 字段。
    try:
        _apply_scene_details(structured, theme, workflow)
    except Exception as _e_sc:
        print(f"[场景细节] 跳过（{type(_e_sc).__name__}）")

    # 2026-10-21 审计：两条 Anima 线把**未转义**的角色/作品标签交给模板 —— 模板自己会
    #   转义一次（config.build_reference_prompt 的 esc/plain），这样才能得到真正的
    #   "转义 + 不转义"双写法。此前传的是已转义版本 → 双重转义，第二份仍是转义写法，
    #   之后被 _fix 的去重当成同一份丢掉（日志里只剩一条角色标签）。
    #   SDXL 两线保持原样，不改它们已验证的模板输入。
    if workflow in ("api", "anima_flow"):
        _asm_name, _asm_series = name_en, series_en
        _extra_tpl = tuple(getattr(_cfg, "ANIMA_EXTRA_TEMPLATE_FIELDS", ()) or ())
    else:
        _asm_name, _asm_series = name_en_anima, series_en_anima
        _extra_tpl = ()
    positive = assemble_positive_prompt(
        structured, _asm_name, _asm_series, framing, extra_fields=_extra_tpl,
    )
    # 2026-10-20 提示词拼装修复（仅 Anima 两线）
    try:
        if workflow in ("api", "anima_flow"):
            positive = _fix_anima_prompt(positive, name_en, series_en)
        else:
            # 2026-10-21 用户选 3：SDXL 双转义 → 单转义（两份都变成正确的字面标签）
            positive = _collapse_double_escape(positive)
    except Exception:
        pass
    # 2026-10-21：LLM 偶尔返回 `negatives` —— 与四季块的 `_add` 口径一致，两个字段都认，
    #   避免整段负面被静默丢掉（build_negative 会回退 FALLBACK）。
    negative = build_negative(structured.get("negative") or structured.get("negatives", ""))
    # 2026-10-21 用户：Anima 构图呆板/表情木讷/背景假 → 负面与正向配套
    if workflow in ("api", "anima_flow"):
        try:
            _dyn_neg = str(getattr(_cfg, "ANIMA_DYNAMIC_NEGATIVE", "") or "")
            if _dyn_neg and "mannequin pose" not in negative.lower():
                negative = (negative + ", " + _dyn_neg).strip(", ")
            _integ_neg = str(getattr(_cfg, "ANIMA_INTEGRATION_NEGATIVE", "") or "")
            if _integ_neg and "pasted character" not in negative.lower():
                negative = (negative + ", " + _integ_neg).strip(", ")
            print("[构图/表情/背景] Anima 已加动态/接地/融合负面")
        except Exception as _e_dyn:
            print(f"[构图/表情/背景] 跳过（{type(_e_dyn).__name__}）")

    if not positive:
        print("[中断] 正向提示词为空。")
        return

    print(f"  [正向] {positive}")
    print(f"  [负向] {negative}")

    pool["characters"].append({
        "name": name, "name_en": name_en,
        "series": series, "series_en": series_en, "theme": theme,
        "scope": _scope_now,     # ★ 2026-10-14：记录作用域，两线名单互不干扰
    })
    # 只统计/释放**本线作用域**内的条目（每条线各自最多 POOL_SIZE 人）
    _same = [i for i, c in enumerate(pool["characters"])
             if c.get("scope") in (None, "", _scope_now)]
    if len(_same) > POOL_SIZE:
        released = pool["characters"].pop(_same[0])
        print(f"[释放] {released.get('name', released.get('name_en', '未知'))}"
              f"（解除本线排除：{_scope_now}）")

    save_json(POOL_FILE, pool)
    print(f"[禁用名单] 更新后 本线({_scope_now}) {len(_same)}/{POOL_SIZE}｜"
          f"名单合计 {len(pool['characters'])}")

    try:
        images = generate_images(
            prompt_list=[{
                "positive": positive,
                "negative": negative,
                "identity": {
                    "name_en": name_en,
                    "series_en": series_en,
                    # 瞳色唯一来源（正文里的冲突瞳色会被 normalize_eyes 删掉）
                    "eye_colors": structured.get("eye_colors", "").strip(),
                },
                # 主题：用于背景贴题清理（泳装 → 只留自然海滩）
                "theme": theme,
            }],
            output_dir=out_dir, candidates=CANDIDATE_COUNT,
            workflow=workflow,
        )
    except Exception as e:
        print(f"[出图失败] {e}\n[中断] 未产出，未记录。")
        cleanup_empty_dir(out_dir)
        return

    valid_images = [p for p in (images or [])
                    if os.path.isfile(p) and os.path.getsize(p) > 0]

    # ---- ① 四肢质检门（2026-10-13，**仅 Anima 两条线**）----------------------
    #   筛掉四肢结构不合格的候选；不足 7 张 → 补图（复用本次同一组生成参数）
    #   注意：generate_images 返回的是**路径列表**（旧代码按 .candidates 取一直是空的）
    #   整段包在 try 里：质检失败不影响出图主流程
    if (_cfg.LIMB_JUDGE and valid_images
            and workflow in getattr(_cfg, "LIMB_JUDGE_WORKFLOWS", ())):
        try:
            import limb_filter as _lf
            print(f"  [四肢质检门] 启用（目标合格 {_cfg.LIMB_JUDGE_TARGET} 张，"
                  f"每张判 {_cfg.LIMB_JUDGE_VOTES} 次，上限 {_cfg.LIMB_JUDGE_MAX_TOTAL} 张）")

            def _more(n):
                _pl = [{
                    "positive": positive, "negative": negative,
                    "identity": {"name_en": name_en, "series_en": series_en,
                                 "eye_colors": structured.get("eye_colors", "").strip()},
                    "theme": theme,
                }]
                try:
                    _im = generate_images(prompt_list=_pl, output_dir=out_dir,
                                          candidates=n, workflow=workflow)
                except Exception as _e:
                    print(f"  [补图失败] {type(_e).__name__}: {str(_e)[:60]}")
                    return []
                return [p for p in (_im or [])
                        if os.path.isfile(p) and os.path.getsize(p) > 0]

            _good = _lf.ensure_n_good(valid_images, _more)
            if _good:
                valid_images = _good
                print(f"  [四肢质检门] 合格 {len(_good)} 张 → 参与打分选择")
            else:
                print("  [四肢质检门] 无合格候选 → 本次不出图")
                cleanup_empty_dir(out_dir)
                return
        except Exception as _e:
            print(f"  [四肢质检门] 跳过（{type(_e).__name__}: {str(_e)[:60]}）")
    if not valid_images:
        print("[出图失败] 无有效图片。\n[中断] 未产出，未记录。")
        cleanup_empty_dir(out_dir)
        return

    # ---- 自动质量闸门：视觉核对 + 账本（2026-10-12）----
    # 出图后让视觉模型对照真实二创特征核对，并累积到 (工作流×主题) 账本；
    # 连续不合格 → 自动标记降级（下次避开该组合）—— 标准来自数据、判定来自看图，零人工维护。
    # ---- 质量闸门 v2：逐候选核对（2026-10-12 用户规格）----
    #   · 本次生成的多张图里，**不达标 ≥3 张** → 本次算失败：不出图 + 对该(模型×主题)降权
    #   · 不达标 <3 张 → 把这**几张筛掉、不参与评分**，从剩下的里择优输出
    #   （旧版用错变量名 chosen_path/best_path 导致异常被吞、闸门静默失效 —— 已改真实变量 images/valid_images）
    try:
        _mk = _cfg.model_key(workflow)
        _bad, _rec = comfy_runner.identity_bad(_mk, theme)
        if _bad:
            print(f"[质量闸门] ⚠ {_mk} × {theme} 权重已降"
                  f"（{_rec.get('weight')}，不合格{_rec.get('bad')}次）")
        _cands = list(getattr(images, "candidates", None) or [])
        if _cfg.IDENTITY_JUDGE and _cands:
            _badc = []
            for _c in _cands[:int(_cfg.IDENTITY_JUDGE_MAX_CANDIDATES)]:
                _jd = comfy_runner.identity_judge(_c.get("path"), name_en, verbose=False)
                _c["identity_score"] = int(_jd.get("identity_score") or 0) if _jd else 0
                _c["missing"] = _jd.get("missing_features")
                if _jd and _c["identity_score"] < _cfg.IDENTITY_JUDGE_MIN_SCORE:
                    _badc.append(_c)
            print(f"  [质量闸门] 逐候选核对 {len(_cands)} 张 → 不达标 {len(_badc)} 张")
            # 不达标 ≥3 张 → **自动重跑**（2026-10-12 用户规格：当天没发图就要重新跑图）
            _rounds = int(_cfg.IDENTITY_JUDGE_RERUNS)
            _r = 0
            while len(_badc) >= 3 and _r < _rounds:
                _r += 1
                print(f"  [质量闸门] 不达标 {len(_badc)} 张（≥3）→ 自动重跑 第 {_r}/{_rounds} 轮")
                try:
                    images = generate_images(
                        prompt_list=[{
                            "positive": positive,
                            "negative": negative,
                            "identity": {"name_en": name_en, "series_en": series_en,
                                         "eye_colors": structured.get("eye_colors", "").strip()},
                            "theme": theme,
                        }],
                        output_dir=out_dir, candidates=CANDIDATE_COUNT,
                        workflow=workflow,
                    )
                except Exception as _e:
                    print(f"  [质量闸门] 重跑失败：{type(_e).__name__} {str(_e)[:60]}")
                    break
                _cands = list(getattr(images, "candidates", None) or [])
                _badc = []
                for _c in _cands[:int(_cfg.IDENTITY_JUDGE_MAX_CANDIDATES)]:
                    _jd = comfy_runner.identity_judge(_c.get("path"), name_en, verbose=False)
                    _c["identity_score"] = int(_jd.get("identity_score") or 0) if _jd else 0
                    _c["missing"] = _jd.get("missing_features")
                    if _jd and _c["identity_score"] < _cfg.IDENTITY_JUDGE_MIN_SCORE:
                        _badc.append(_c)
                print(f"    重跑{_r} 结果：{len(_cands)} 张 → 不达标 {len(_badc)} 张")
            if len(_badc) >= 3:
                comfy_runner.record_identity(_mk, theme, _cfg.IDENTITY_JUDGE_MIN_SCORE - 1)
                print(f"  [质量闸门] ✗ 重跑 {_r} 轮后仍不达标 {len(_badc)} 张（≥3）"
                      f" → **本次不出图**、已降权")
                cleanup_empty_dir(out_dir)
                return
            _good = [c for c in _cands
                     if c.get("identity_score", 0) >= _cfg.IDENTITY_JUDGE_MIN_SCORE]
            if _good:
                _bestc = max(_good, key=lambda c: c.get("score", 0))
                valid_images = [_bestc["path"]]
                comfy_runner.record_identity(_mk, theme, _bestc["identity_score"])
                print(f"  [质量闸门] ✓ 筛除 {len(_badc)} 张不达标 → 从 {len(_good)} 张达标图里择优："
                      f"身份分 {_bestc['identity_score']}/5、美学分 {_bestc.get('score')}")
    except Exception as e:
        print(f"[质量闸门] 跳过（{type(e).__name__}: {str(e)[:60]}）")

    print("[输出]")
    for p in valid_images:
        print(f"  {p}")
    print("[完成] 角色流水线执行完毕。")


if __name__ == "__main__":
    main()