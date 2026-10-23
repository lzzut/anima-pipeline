# comfy_runner.py
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import json, random, re, shutil
from comfyui_xy import ComfyUiClient
from config import (
    COMFY_URL,
    FALLBACK_NEGATIVE, WORKFLOW_SETTINGS, KSAMPLER_COMBOS,
    ANIMA_FLOW_SETTINGS, CLIP_SKIP, GENERIC_FACE_TAGS,
    EXTRA_NEGATIVE, EYE_NEGATIVE, theme_scene_rule,
    ANIMA_PREFIX, ANIMA_NEGATIVE, anima_artist_combos,
    SANE_PLACEMENT_NEGATIVE, CLOTHING_CLARITY_NEGATIVE, SANE_PLACEMENT_WORKFLOWS,
    ANIMA_EXTRA_POSITIVE, EYE_LOCK, EYE_LOCK_WEIGHT, EYE_WRONG_COLORS,
    HIRES_FIX, HIRES_WORKFLOWS, HIRES_SCALE, HIRES_DENOISE, HIRES_STEPS, HIRES_CFG,
    ARTIST_TAGS_WORKFLOWS, ARTIST_TAGS_AT_PREFIX, seed_max_for, artist_roll,
    anima_model_roll, set_active_unet,
    EYE_TAG_MODE_WORKFLOWS,
    EYE_VLM_CHECK, EYE_VLM_PENALTY, EYE_VLM_TIMEOUT, EYE_VLM_MAX_EXTRA,
    IDENTITY_JUDGE_MIN_SCORE, IDENTITY_JUDGE_BAD_LIMIT,
    IDENTITY_JUDGE_MAX_TOKENS, IDENTITY_JUDGE_WEIGHT_FLOOR,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
)
from prompt_style import style_directive  # noqa: F401  (保持对外可导入)

client = ComfyUiClient(url=COMFY_URL)

CANDIDATE_COUNT = 5


class GenResult(list):
    """
    `generate_images()` 的返回值（2026-10-11 接口改进）。

    为什么需要：它以前只返回 **最终选中图路径列表**，而最终文件名**不含 seed**
    （设计上就是"当天最优"的稳定名）→ 同一目录多次运行会**互相覆盖**，下游若按
    "每个 seed 一个路径"去取图就会取到同一张（实测踩过：对照实验四行贴成同一张图）。

    现在：**仍然是一个 list**（元素是最终选中图路径，旧调用方完全兼容、零改动），
    另外携带结构化信息：
      .selected   -> [最终选中图路径, ...]（与 list 本身一致）
      .candidates -> [{"path", "seed", "score"}, ...]（**带 seed 的真实候选图**）
    """

    def __init__(self, selected_paths, candidates=None):
        super().__init__(selected_paths or [])
        self.selected = list(selected_paths or [])
        self.candidates = list(candidates or [])

    def by_seed(self, seed):
        return next((c for c in self.candidates if c.get("seed") == seed), None)

    def candidate_paths(self):
        return [c["path"] for c in self.candidates]


# ---------------------------------------------------------------------------
# Anima 两条线路：api / anima_flow 二选一
#   → 再叠画师标签开/不开（50/50，触发时 CFG 固定 3.7）
#   → 再叠原生 bf16 / int8 二选一
#   → api 线从 KSAMPLER_COMBOS 随机抽采样器组合
#     （anima_flow 是固定 flow 采样，不参与采样器抽签）
# ---------------------------------------------------------------------------
WORKFLOW_TRACKS = {
    "anima": ("api", "anima_flow"),
}


def choose_track():
    return random.choice(list(WORKFLOW_TRACKS.keys()))


def choose_workflow():
    """先选线路，再在线路内二选一（见 WORKFLOW_TRACKS 说明）"""
    track = choose_track()
    wf = random.choice(WORKFLOW_TRACKS[track])
    print(f"  [线路] {track} → 线路内选中 {wf}")
    return wf



def describe_workflow(workflow):
    """给日志用的一句话描述"""
    st = WORKFLOW_SETTINGS[workflow]
    name = {
        "api": "workflow_api.json (KSampler)",
        "anima_flow": "workflow_anima_flow.json (AnimaFlowCorrectiveSampler)",
    }[workflow]
    model = st.get("unet") or st.get("ckpt") or "?"
    return f"{name}, model={model}"


def _weights_tag(workflow):
    """
    从**实际加载的权重文件名**推出量化/版本标识，用于文件名标注。

    为什么需要：原来的前缀是写死的 "Anima2.9B_int8_..."，即使换成原生 bf16 也照样写 int8
    → 翻图库时**无法分辨哪张是哪个模型出的**（实测踩过）。
    """
    st = WORKFLOW_SETTINGS.get(workflow, {}) or {}
    f = (st.get("unet") or st.get("ckpt") or "").lower()
    if "int8" in f:
        return "int8"
    if "fp8" in f:
        return "fp8"
    if "q8" in f:
        return "q8"
    if "q4" in f:
        return "q4"
    if "-opt" in f:
        return "opt"
    if "bf16" in f:
        return "bf16"
    return "fp16"


def run_tag(workflow, anchor=None, sampler=None, scheduler=None):
    """
    出图标注：把"绘图模型名 + 权重版本 + 采样配置"做成文件名前缀 / SaveImage 前缀，
    这样翻 output 目录时一眼能看出哪张是**哪个模型**出的。

    模型名部分由 `_weights_tag()` 从真实权重文件名推导（int8/fp8/opt/bf16/fp16），
    **不再写死** —— 否则换模型后文件名会撒谎。
    """
    w = _weights_tag(workflow)
    if workflow == "anima_flow":
        return f"Anima2.9B_{w}_flow_euler"
    if workflow == "animagine_xl":
        return f"AnimagineXL4_{w}_{sampler}_{scheduler}".replace(" ", "")
    if workflow == "nova_xl":
        return f"NovaAnimeXL_{w}_{sampler}_{scheduler}".replace(" ", "")
    return f"Anima2.9B_{w}_{sampler}_{scheduler}".replace(" ", "")

# ===========================================================================
# 工作流与采样配置（2026-10-10 实测定档）
#
# 每次跑图：api / anima_flow / animagine_xl / nova_xl 四选一（config.WORKFLOW_POOL）。
#   · 选中 workflow_api.json → 再从 config.KSAMPLER_COMBOS 随机抽一套采样器组合
#     （Euler+sgm_uniform、er_sde+beta57、res_multistep+linear_quadratic 等，
#      每套带自己的推荐步数/CFG）
#   · 选中 anima_flow      → flow_euler + diffusers_linear_shift + cfg5 + 50步（项目统一）
#   · 选中 animagine_xl    → Animagine XL 4.0 官方卡参数（28步/cfg5/euler_a，质量词放末尾）
#   · 选中 nova_xl         → Illustrious 系惯例（28步/cfg5/euler_a）
#
# 实测单张耗时（1024x1536，Anima int8 / bf16）：
#   Anima int8    30步 cfg5 euler+simple           ≈ 79s
#   Anima bf16    30步 cfg5 euler+simple           ≈ 115s
#   Anima bf16    50步 cfg3.7 pc3_damped+rf_shift  ≈ 356s（旧 anima_flow 配置）
# ===========================================================================

_scorer = None


def _get_scorer():
    global _scorer
    if _scorer is None:
        from transformers import pipeline
        _scorer = pipeline(
            "image-classification",
            model="kawaimasa/kawai-aesthetic-scorer-convnextv2"
        )
    return _scorer


def _top_edge_penalty(image_path):
    """
    顶部裁切惩罚 —— **已标定失败，默认关闭（恒定返回 0）**。
    2026-10-11 实测：灰度标准差与边缘密度都无法区分"切到头发"和"有云有鸟的天空"
    （切头 0.11~0.17 vs 正常 0.10~0.14，区间重叠）。像素启发式不可靠，
    不做这种脆弱判定，改从根因解决（负面上限 + 分辨率留头空间 + 景别约束）。
    保留函数以便将来有可靠判据时替换实现。
    """
    return 0.0


# ===========================================================================
# 自动质量闸门：视觉核对（是否本人 / 表情 / 构图）
# ===========================================================================
IDENTITY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "identity_verdicts.json")
# 角色 × 模型 黑名单（2026-10-12）：某角色在某模型上反复不达标 → 该模型下不再选她
CHAR_BLACKLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "character_model_blacklist.json")


def _load_char_blacklist():
    try:
        with open(CHAR_BLACKLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def char_blacklisted(model_key, name_en, verbose=False):
    """该角色是否已在该模型下被拉黑（按模型分别记录，互不影响其它模型）

    2026-10-23 用户恢复：Nova 芙宁娜、Animagine 雷电/芙宁娜质量不行 → 按模型拉黑。
    """
    d = _load_char_blacklist()
    hit = name_en in ((d.get(model_key) or {}).get("characters") or {})
    if hit and verbose:
        rec = (d[model_key]["characters"] or {})[name_en]
        print(f"  [角色黑名单] {name_en} 已在 {model_key} 下被拉黑：{str(rec.get('reason'))[:50]}")
    return hit


def blacklist_char(model_key, name_en, reason="", verbose=True):
    d = _load_char_blacklist()
    m = d.setdefault(model_key, {"characters": {}})
    m.setdefault("characters", {})[name_en] = {"reason": reason, "ts": ""}
    try:
        with open(CHAR_BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    if verbose:
        print(f"  [角色黑名单] 已拉黑：{name_en} @ {model_key}（{str(reason)[:50]}）")
    return d


def _load_identity():
    try:
        with open(IDENTITY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def identity_bad(workflow, theme):
    """该 (工作流 × 主题) 是否已被自动判定为"不合格组合"（连续低分 → 避开）"""
    d = _load_identity()
    rec = d.get(f"{workflow}|{theme}") or {}
    return (rec.get("bad", 0) >= IDENTITY_JUDGE_BAD_LIMIT), rec


def record_identity(workflow, theme, score, missing=None, verbose=True):
    """
    记账（key = 模型 × 主题）并**按规则自动降权**（2026-10-12 用户规格）：
      · 不达标(身份分<合格线) → weight ×= 0.5（连续失败持续衰减，几乎不可能再被选中）
      · 达标                → weight 缓慢回升（×1.1，上限 1.0）
    """
    d = _load_identity()
    k = f"{workflow}|{theme}"
    rec = d.get(k) or {"n": 0, "sum": 0, "bad": 0, "weight": 1.0, "missing": []}
    rec.setdefault("weight", 1.0)
    rec["n"] += 1
    rec["sum"] += score
    if score < IDENTITY_JUDGE_MIN_SCORE:
        rec["bad"] += 1
        rec["weight"] = round(max(0.01, rec["weight"] * 0.5), 3)   # 衰减
    else:
        rec["weight"] = round(min(1.0, rec["weight"] * 1.1), 3)    # 回升
    if missing:
        rec["missing"] = list(dict.fromkeys((rec.get("missing") or []) + list(missing)))[:12]
    rec["avg"] = round(rec["sum"] / max(1, rec["n"]), 2)
    d[k] = rec
    try:
        with open(IDENTITY_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    if verbose:
        print(f"  [质量账本] {k}: 第{rec['n']}次 身份分{score} 均分{rec['avg']} "
              f"不合格{rec['bad']}次 权重={rec['weight']}"
              + ("  → 权重已降，后续更不易被选中" if score < IDENTITY_JUDGE_MIN_SCORE else ""))
    return rec


def theme_weight(model_key, theme):
    """该 (模型 × 主题) 当前权重（默认 1.0；失败会衰减）"""
    d = _load_identity()
    return float((d.get(f"{model_key}|{theme}") or {}).get("weight", 1.0))


def low_weight_themes(model_key, floor=None):
    """权重低于 floor 的主题列表（应在选主题时避开）"""
    fl = IDENTITY_JUDGE_WEIGHT_FLOOR if floor is None else floor
    d = _load_identity()
    out = []
    for k, rec in d.items():
        if not k.startswith(str(model_key) + "|"):
            continue
        if float(rec.get("weight", 1.0)) < fl:
            out.append(k.split("|", 1)[1])
    return out


def identity_judge(image_path, name_en, verbose=True):
    """
    让视觉模型对照该角色**真实二创挖到的高频特征**客观核对出图。

    返回 dict：is_target_character / confidence / identity_score / visible_features /
              missing_features / expression / composition（失败返回 {}）。
    """
    try:
        import base64, io, httpx
        from PIL import Image
        from booru_client import appearance_tags
        _feat = [t.replace("_", " ") for t in (appearance_tags(name_en, sample=40) or [])][:12]
        canon = f"{name_en} 的官方/二创高频特征：{', '.join(_feat)}" if _feat else name_en
        im = Image.open(image_path).convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        q = (f"目标角色：{canon}\n请客观核对图中可见特征，只输出 JSON："
             '{"is_target_character": true/false, "confidence": 0-100, '
             '"visible_features": [...], "missing_features": [...], '
             '"identity_score": 1-5, "expression": "...", "composition": "..."}')
        r = httpx.post((DEEPSEEK_BASE_URL or "").rstrip("/") + "/chat/completions",
                       headers={"Authorization": "Bearer " + DEEPSEEK_API_KEY,
                                "Content-Type": "application/json"},
                       json={"model": DEEPSEEK_MODEL, "max_tokens": IDENTITY_JUDGE_MAX_TOKENS,
                             "messages": [{"role": "user", "content": [
                                 {"type": "text", "text": q},
                                 {"type": "image_url",
                                  "image_url": {"url": "data:image/png;base64," + b64}}]}]},
                       timeout=180)
        if r.status_code != 200:
            return {}
        txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return {}
        d = json.loads(m.group(0))
        if verbose:
            print(f"  [视觉核对] 是否本人={d.get('is_target_character')}"
                  f"({d.get('confidence')}%) 身份分={d.get('identity_score')}/5"
                  f" 缺失={str(d.get('missing_features'))[:60]}")
        return d
    except Exception as e:
        if verbose:
            print(f"  [视觉核对] 跳过（{type(e).__name__}）")
        return {}


def _is_complex_eyes(identity):
    """是否属于"复杂瞳"（异色瞳/逐眼不同色/渐变瞳）——只有这类角色才做视觉复核。"""
    ec = ((identity or {}).get("eye_colors") or "").lower()
    if not ec:
        return False
    if "heterochromia" in ec:
        return True
    if re.search(r"(left|right)\s+eye", ec):
        return True
    if "gradient" in ec or "two-tone" in ec or "multicolor" in ec:
        return True
    return False


def _eye_abnormal(image_path):
    """
    视觉复核：把脸部区域裁出来交给视觉模型，判断眼睛有没有"变成纯色块/缺瞳仁"。

    返回 (是否异常, 原因)。**任何失败都返回 (False, '')**（fail-open：不因复核故障影响出图）。
    只对复杂瞳角色调用（由调用方用 _is_complex_eyes 控制），避免无谓开销。
    """
    try:
        from PIL import Image
        import base64, io, json as _json
        import httpx
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        # 脸部/眼部在画面上半部的中央区域，裁宽 70%、高 45%
        crop = img.crop((int(w * 0.15), int(h * 0.02), int(w * 0.85), int(h * 0.47)))
        crop.thumbnail((512, 512))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        prompt = ("这是一张动漫角色插画的脸部特写。请判断：角色的眼睛有没有出现"
                  "「虹膜/瞳孔缺失、整只眼糊成一块纯色、只剩一个高光点」这种异常？"
                  "只回答 JSON：{\"abnormal\": true/false, \"reason\": \"不超过20字\"}")
        body = {"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64," + b64}}]}],
            "max_tokens": 120}
        r = httpx.post((DEEPSEEK_BASE_URL or "").rstrip("/") + "/chat/completions",
                       headers={"Authorization": "Bearer " + DEEPSEEK_API_KEY,
                                "Content-Type": "application/json"},
                       json=body, timeout=EYE_VLM_TIMEOUT)
        if r.status_code != 200:
            return False, ""
        txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return ("abnormal" in txt.lower() and "true" in txt.lower()), ""
        data = _json.loads(m.group(0))
        return bool(data.get("abnormal")), str(data.get("reason") or "")[:40]
    except Exception:
        return False, ""


def _score_image(image_path):
    try:
        from PIL import Image
    except ImportError:
        return random.random()
    try:
        scorer = _get_scorer()
        img = Image.open(image_path).convert("RGB")
        results = scorer(img)
        label_map = {
            "SS_tier": 5, "S_tier": 4, "A_tier": 3, "B_tier": 2, "C_tier": 1
        }
        total = 0.0
        for item in results:
            total += label_map.get(item["label"], 0) * item["score"]
        return total
    except Exception as e:
        print(f"    评分失败：{e}")
        return 0.0


EYE_COLOR_WORDS = (
    "blue", "sapphire", "azure", "aqua", "cyan", "teal", "purple", "violet",
    "green", "emerald", "amber", "golden", "crimson", "red", "pink", "yellow",
    "brown", "grey", "gray", "silver", "orange",
)
MAKEUP_WORDS = ("eyeliner", "eyeshadow", "eyelash", "eyebrow", "makeup", "eye shadow")


def strip_generic_face(positive):
    """
    提示词减法：删掉通用美颜词（含带权重的写法）。

    为什么：这些词不指向任何角色特征，带权重后会把模型"认识的角色脸"
    拉成通用可爱脸 —— 实测芙宁娜反而更不像了。角色脸交给底模对角色的认知，
    我们只保留角色专属特征（发色/瞳色/服饰/配饰）。
    """
    kept = []
    for frag in (positive or "").split(","):
        low = frag.lower()
        if any(tag in low for tag in GENERIC_FACE_TAGS):
            continue
        kept.append(frag.strip())
    return ", ".join(k for k in kept if k)


def sanitize_background(positive, theme):
    """
    按主题清理背景：泳装/沙滩就只留自然海滩元素，删掉建筑/城市/室内/人造粒子。

    问题来源：指令要求"场景三层都填满"，模型就把角色世界观搬进背景
    （芙宁娜 → 枫丹 → 城堡塔楼天际线 + 漂浮泡泡），泳装图完全不着调。
    命中禁止词时，用一句干净的海滩背景替换，避免删完背景变空、模型乱编。
    """
    rule_name, rule = theme_scene_rule(theme)
    if not rule:
        return positive, []

    kept, removed = [], []
    for frag in (positive or "").split(","):
        low = frag.lower()
        # forbid 里是正则（词边界/短语），避免 towering→tower、headroom→room 误删
        if any(re.search(pat, low) for pat in rule["forbid"]):
            removed.append(frag.strip())
            continue
        kept.append(frag.strip())

    body = ", ".join(k for k in kept if k)
    if removed:
        body = f"{body}, {rule['keep']}"
    return body, removed


def eye_lock(positive, negative, identity, workflow=None):
    """
    瞳色锁定：把官方瞳色写成带权重的标签（正向锚定），
    并把非官方色系从负面排掉（但排除角色本身就用那个色的情况）。

    为什么需要：底模自由发挥时紫/粉瞳色会盖过提示词，
    而"只压紫眼"会漂成绿眼 —— 所以要正向锚定蓝系 + 负向排掉其它色系。
    返回 (positive, negative)
    """
    if not EYE_LOCK:
        return positive, negative
    eye_colors = ((identity or {}).get("eye_colors") or "").strip()
    if not eye_colors:
        return positive, negative

    # 正向：**不再对颜色短语加权**（A+C 方案，2026-10-11）
    #   实测：`(left eye dark blue:1.25)` 这种"把颜色词加权"会让模型把那一侧画成
    #   一整块填充色（无瞳仁，只剩水滴高光）—— 问题总出现在被加权的那一侧。
    #   改为：把逐眼颜色**转写成规范标签形式** `dark blue eyes`（不加权），
    #   再加上 detailed eyes 兜底；颜色正确性交给标签语义 + 负面排色。
    # 2026-10-23：不再只删末尾，改为全文移除，避免配方里 eye_colors 在中间时重复追加
    positive = positive.replace(eye_colors, "").strip(" ,")
    positive = re.sub(r",\s*,+", ", ", positive)
    parts = [p.strip() for p in eye_colors.split(",") if p.strip()]
    # purple / violet 视为同色系，避免互相误伤
    canon = eye_colors.lower()
    if "purple" in canon:
        canon += " violet"
    if "violet" in canon:
        canon += " purple"
    if workflow in EYE_TAG_MODE_WORKFLOWS:
        # ===== A+C 方案（仅限 EYE_TAG_MODE_WORKFLOWS，如 animagine_xl）=====
        #   正向不加权，改写为规范标签（dark blue eyes）+ detailed eyes；
        #   负面照旧排掉非官方色系。
        tags, colors = [], []
        for p in parts:
            if p.startswith("(") and p.endswith(")"):
                tags.append(p)
                continue
            m = re.search(r"(?:left|right)\s+eye\s+(.+)$", p, re.I)
            if m:
                color = m.group(1).strip()
                colors.append(color if color.lower().endswith("eyes")
                              else f"{color} eyes")
            else:
                tags.append(p)          # heterochromia 等修饰标签原样保留
        # 2026-10-11 撤回"异色瞳只保留单色标签"实验：实测对眼白无改善，
        # 反而让部分 seed 掉分（2.832→2.616），故恢复"两侧颜色各写一个标签"。
        tags.extend(colors)
        if tags and not any(t.lower() == "detailed eyes" for t in tags):
            tags.append("detailed eyes")
        if tags:
            positive = f"{positive}, {', '.join(tags)}"
        wrong = [w for w in EYE_WRONG_COLORS if w.split()[0] not in canon]
        # 同日撤回眼白负面（solid color eyes / colored sclera）：实测无效（底模不认这两个标签）
        if wrong:
            negative = _dedup_csv(f"{negative}, {', '.join(wrong)}")
        return positive, negative

    # ===== 原方案（其他工作流）：逐眼颜色加权 =====
    weighted = []
    for p in parts:
        if p.startswith("(") and p.endswith(")"):
            weighted.append(p)
        elif re.search(r"(left|right)\s+eye", p, re.I):
            weighted.append(f"({p}:{EYE_LOCK_WEIGHT})")
        else:
            weighted.append(p)
    positive = f"{positive}, {', '.join(weighted)}"

    # 负向：排掉非官方色系
    wrong = [w for w in EYE_WRONG_COLORS if w.split()[0] not in canon]
    if wrong:
        negative = _dedup_csv(f"{negative}, {', '.join(wrong)}")
    return positive, negative


def normalize_eyes(positive, identity, weight=None):
    """
    瞳色去重 + 唯一来源：
      ① 删掉正文里与 identity.eye_colors 冲突的瞳色描述（实测踩过坑：
         正文写 "left eye pale sky blue, right eye deep sapphire"，
         face_identity 写反，两处打架 → 模型混出紫色）
      ② 把权威瞳色追加到末尾；weight 不为 None 时加权（SDXL 系对标签权重更敏感）
    妆容类（eyeliner/eyeshadow）颜色不算瞳色，保留。
    """
    eye_colors = ((identity or {}).get("eye_colors") or "").strip()
    if not eye_colors:
        return positive

    kept = []
    for frag in (positive or "").split(","):
        low = frag.lower()
        has_color = any(c in low for c in EYE_COLOR_WORDS)
        mentions_eye = any(k in low for k in ("eye", "iris", "pupil", "heterochrom"))
        is_makeup = any(m in low for m in MAKEUP_WORDS)
        if mentions_eye and has_color and not is_makeup:
            continue
        kept.append(frag.strip())

    body = ", ".join(k for k in kept if k)

    if weight:
        parts = [p.strip() for p in eye_colors.split(",") if p.strip()]
        eye_colors = ", ".join(
            p if (p.startswith("(") and p.endswith(")")) else f"({p}:{weight})"
            for p in parts
        )
    return f"{body}, {eye_colors}"


def eye_negative(identity):
    """角色官方瞳色不含紫/紫罗兰时，负面里压掉"异色瞳=紫眼"的模型先验"""
    eye_colors = ((identity or {}).get("eye_colors") or "").lower()
    if not eye_colors:
        return ""
    if "purple" in eye_colors or "violet" in eye_colors:
        return ""
    return EYE_NEGATIVE


_SUBJECT_RE = re.compile(r"(1girl|1boy|1other|2girls|multiple girls)", re.I)


def _dedup_csv(text):
    seen, out = set(), []
    for p in (text or "").split(","):
        k = p.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(p.strip())
    return ", ".join(out)


def _norm_tag(frag):
    """归一化一个标签片段用于比较：去掉转义符/括号，小写，下划线转空格"""
    return re.sub(r"[\\()\[\]]", "", frag or "").strip().lower().replace("_", " ")


def _first_series(prompt_list):
    """取第一条提示词的角色作品标签（同一角色的多套提示词共用一个画师串）"""
    for item in prompt_list or []:
        if isinstance(item, dict):
            s = (item.get("identity") or {}).get("series_en")
            if s:
                return s
    return None


def _insert_after_series(positive, inject, identity):
    """
    把画师串插到「作品名」标签之后（danbooru 惯例的标签顺序）。

    注意：必须按**逗号分段**匹配整段标签，不能用子串查找 ——
    否则 "genshin impact" 会先命中角色标签 `furina \\(genshin impact\\)` 内部，
    画师串就会被塞进角色名括号里（实测踩过这个坑）。
    """
    series = _norm_tag((identity or {}).get("series_en") or "")
    frags = [f.strip() for f in (positive or "").split(",")]
    if series:
        for i, frag in enumerate(frags):
            if _norm_tag(frag) == series:
                frags.insert(i + 1, inject)
                return re.sub(r"\s{2,}", " ", ", ".join(frags))

    m = _SUBJECT_RE.search(positive or "")
    if m:
        comma = positive.find(",", m.end())
        if comma > 0:
            return f"{positive[:comma]}, {inject}{positive[comma:]}"
    return f"{inject}, {positive}"


def format_prompt(workflow, positive, negative, identity=None, theme=None,
                  artist_combo=None):
    """
    按底模的训练规范调整提示词结构（不同底模规范不一样，别一套打天下）：

    · animagine_xl（Animagine XL 4.0，官方卡）：
        结构 = 1girl → 角色 → 作品 → rating → 其它 → **质量/分数标签放最后**
        质量要用 score 类：masterpiece, high score, great score, absurdres
        负面要含 low score / bad score / average score
    · 其他工作流：保持原样（Illustrious 系与 Anima/Z-Image 都是质量词前置）
    """
    st = WORKFLOW_SETTINGS.get(workflow, {})

    # --- Anima-2.9B：按官方模型卡规范（score_7 前缀 + 官方负面 + 强制画师串）---
    if workflow in ("api", "anima_flow"):
        m = _SUBJECT_RE.search(positive or "")
        if m:
            body = positive[m.start():].strip(" ,")
            positive = f"{ANIMA_PREFIX}, {body}"          # 换掉通用质量前缀
        elif positive:
            positive = f"{ANIMA_PREFIX}, {positive}"
        if artist_combo:
            positive = _insert_after_series(positive, artist_combo, identity)
        negative = _dedup_csv(f"{ANIMA_NEGATIVE}, {negative}")
        if ANIMA_EXTRA_POSITIVE:
            positive = f"{positive}, {ANIMA_EXTRA_POSITIVE}"

    # --- SDXL 系（Animagine / Nova）：按实测**不加画师串** ---
    #     （用户实测：画师标签在 Animagine 上不如 Anima 有效，加了反而更差）

    # --- SDXL 两线构图负面（2026-10-13 用户要求，nova_xl + animagine_xl 一致）---
    try:
        from config import FRAMING_NEGATIVE_WORKFLOWS as _fpw, NOVA_FRAMING_NEGATIVE as _nfn
    except Exception:
        _fpw, _nfn = (), ""
    if workflow in _fpw and _nfn:
        negative = _dedup_csv(f"{negative}, {_nfn}")

    # --- 通用防错位 / 防服饰糊块（作用域由 config 决定，默认只 Anima 两条）---
    if workflow in SANE_PLACEMENT_WORKFLOWS:
        negative = _dedup_csv(f"{negative}, {SANE_PLACEMENT_NEGATIVE}, "
                              f"{CLOTHING_CLARITY_NEGATIVE}")

    # 2026-10-11：我加的"SDXL 角色身份锚"（(角色:1.2)+(作品:1.1)+character focus）已按用户
    # 要求**撤回** —— 用户明确表示满意的是"动手之前"那一版（AnimagineXL4_..._00003/00015/00031）。
    # 教训：不要往已验证满意的版本里加东西；像不像的问题先问，别自己改。

    # 2026-10-11 撤回"景别约束"（原 FRAMING_GUARD="head to toe, entire body in frame..."）：
    # 实测它把人物硬推到全身远景 → 人小、四肢比例崩、道具抢戏（分数 2.5 vs 历史 3.9）。
    # 防切头改由 EXTRA_NEGATIVE + 偏近景的 FRAMING_OPTIONS（cowboy shot/upper body/portrait）承担。

    if st.get("quality_at_end"):
        m = _SUBJECT_RE.search(positive or "")
        if m:
            rest = positive[m.start():].strip(" ,")        # 丢掉原在开头的那块质量词
            positive = f"{rest}, {st.get('quality_tags', '')}".strip(" ,")
        elif st.get("quality_tags"):
            positive = f"{positive}, {st.get('quality_tags')}"

    if st.get("negative"):
        negative = _dedup_csv(f"{st['negative']}, {negative}")

    # --- ② 姿势规避负面（2026-10-13 方案②）：最易崩的姿势/道具交互 ---
    try:
        from config import LIMB_POSE_NEGATIVE as _lpn, LIMB_POSE_WORKFLOWS as _lpw
    except Exception:
        _lpn, _lpw = "", ()
    if _lpn and workflow in _lpw:
        negative = _dedup_csv(f"{negative}, {_lpn}")

    # --- Animagine 过紧裁切负面（2026-10-14 用户反馈"头又丢了一部分"）---
    #   close-up / extreme close-up / head out of frame … → 与正向的 upper body 形成"别裁太紧"
    if workflow == "animagine_xl":
        try:
            from config import ANIMAGINE_FRAMING_NEGATIVE as _afn
        except Exception:
            _afn = ""
        if _afn:
            negative = _dedup_csv(f"{negative}, {_afn}")

    if EXTRA_NEGATIVE:
        negative = _dedup_csv(f"{negative}, {EXTRA_NEGATIVE}")
    # 2026-10-18 用户："兔女郎全角色禁用" → 全局负面兜底（即使提示词泄漏也不画）
    try:
        from config import BANNED_THEME_NEGATIVE as _btn
        if _btn:
            negative = _dedup_csv(f"{negative}, {_btn}")
    except Exception:
        pass
    # 2026-10-19 用户：**按线路**加负面（不许影响其他模型）
    try:
        from config import LINE_EXTRA_NEGATIVES as _line_neg
        _extra_neg = (_line_neg or {}).get(workflow, "")
        if _extra_neg:
            negative = _dedup_csv(f"{negative}, {_extra_neg}")
    except Exception:
        pass
    # 2026-10-21 用户：**两条 Anima 线不吃眼部负面**（EYE_NEGATIVE 里的
    #   smudged eye / asymmetrical eyes / hair covering eye 等是给 SDXL 的补强）。
    #   nova 本次不动。
    eye_neg = "" if workflow in ("api", "anima_flow") else eye_negative(identity)
    if eye_neg:
        negative = _dedup_csv(f"{negative}, {eye_neg}")
    rule_name, rule = theme_scene_rule(theme)
    if rule and rule.get("negative"):
        negative = _dedup_csv(f"{negative}, {rule['negative']}")

    return positive, negative


def _build_workflow(workflow, positive, negative, seed, steps, cfg,
                    sampler=None, scheduler=None, unet_name=None,
                    flow_settings=None, tag=None, ckpt_name=None):
    st = WORKFLOW_SETTINGS[workflow]
    workflow_path = st["path"]
    unet_name = unet_name or st.get("unet")
    ckpt_name = ckpt_name or st.get("ckpt")

    with open(workflow_path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    _pos_ids = []
    for _nid, node in graph.items():
        title = node.get("_meta", {}).get("title", "")
        class_type = node.get("class_type", "")
        if title == "positive_prompt":
            node["inputs"]["text"] = positive
            _pos_ids.append(str(_nid))
        elif title == "negative_prompt":
            node["inputs"]["text"] = negative
        elif title == "ksampler":
            node["inputs"].update({
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler
            })
        elif title == "anima_sampler":
            node["inputs"].update({
                "seed": seed,
                "steps": steps,
                "cfg": cfg
            })
            if flow_settings:
                node["inputs"].update(flow_settings)
        elif class_type == "UNETLoader" and unet_name:
            node["inputs"]["unet_name"] = unet_name
        elif class_type == "CheckpointLoaderSimple" and ckpt_name:
            node["inputs"]["ckpt_name"] = ckpt_name
        elif class_type == "CLIPSetLastLayer":
            node["inputs"]["stop_at_clip_layer"] = CLIP_SKIP
        elif class_type == "SaveImage" and tag:
            # ComfyUI 自己存的那份也带上模型名，方便在 output 里辨认
            node["inputs"]["filename_prefix"] = tag

    # ---- 二段高清修复（有 hires_sampler 节点才处理；关掉则只出第一段）----
    hires_on = (HIRES_FIX and workflow in HIRES_WORKFLOWS
                and any(n.get("_meta", {}).get("title") == "hires_sampler"
                        for n in graph.values()))
    for node in graph.values():
        title = node.get("_meta", {}).get("title", "")
        if title == "hires_sampler":
            node["inputs"].update({"steps": HIRES_STEPS, "cfg": HIRES_CFG,
                                   "denoise": HIRES_DENOISE,
                                   "seed": (seed + 1) % (2 ** 32)})
            if sampler:
                node["inputs"]["sampler_name"] = sampler
            if scheduler:
                node["inputs"]["scheduler"] = scheduler
        elif title == "latent_upscale":
            base = next((n for n in graph.values()
                         if n.get("class_type") == "EmptyLatentImage"), None)
            if base:
                w = int(base["inputs"].get("width", 896) * HIRES_SCALE)
                h = int(base["inputs"].get("height", 1152) * HIRES_SCALE)
                node["inputs"].update({"width": w // 8 * 8, "height": h // 8 * 8})
    if any(n.get("_meta", {}).get("title") == "hires_sampler" for n in graph.values()) \
            and not hires_on:
        # 没开高清修复 → 直接把保存节点接到第一段的解码上
        for node in graph.values():
            if node.get("class_type") == "SaveImage":
                node["inputs"]["images"] = ["7", 0]

    return graph


def _run_once(workflow, positive, negative, seed, output_path,
              steps=30, cfg=5.0, sampler=None, scheduler=None,
              unet_name=None, flow_settings=None, tag=None,
              ckpt_name=None):
    graph = _build_workflow(
        workflow, positive, negative, seed, steps, cfg,
        sampler, scheduler, unet_name, flow_settings, tag, ckpt_name,
    )
    results = client.process_workflow(graph)
    for result in results:
        if result.file_type == "image":
            result.save(output_path)
            return output_path
    return None


def generate_images(prompt_list, output_dir,
                    workflow=None,
                    steps=None,
                    cfg=None,
                    candidates=CANDIDATE_COUNT):
    """
    出图并自动打分选优。

    workflow: "api" / "anima_flow"，传 None 则二选一随机。
              - api          : KSampler，采样器组合从 KSAMPLER_COMBOS 随机抽（每套自带步数/CFG）
              - anima_flow   : AnimaFlowCorrectiveSampler（cfg5/50步，项目统一）
    steps/cfg: 显式传入则覆盖该工作流的默认值。
    """
    os.makedirs(output_dir, exist_ok=True)
    selected_files = []

    workflow = workflow or choose_workflow()
    if workflow not in WORKFLOW_SETTINGS:
        raise ValueError(f"未知工作流：{workflow}（可选 {list(WORKFLOW_SETTINGS)}）")

    st = WORKFLOW_SETTINGS[workflow]
    unet_name = st.get("unet")
    ckpt_name = st.get("ckpt")
    flow_settings = None
    sampler = scheduler = None
    artist_combo = None

    if workflow == "api":
        sampler, scheduler, combo_steps, combo_cfg, source = random.choice(KSAMPLER_COMBOS)
        steps = combo_steps if steps is None else steps
        cfg = combo_cfg if cfg is None else cfg
        print("  [工作流] workflow_api.json")
        print(f"  [采样组合] KSampler {sampler} + {scheduler}, {steps}步, "
              f"cfg{cfg}  ← {source}")
    elif workflow == "anima_flow":
        steps = st["steps"] if steps is None else steps
        cfg = st["cfg"] if cfg is None else cfg
        flow_settings = dict(ANIMA_FLOW_SETTINGS)
        print("  [工作流] workflow_anima_flow.json")
        print(f"  [采样组合] {flow_settings['flow_solver']} + "
              f"{flow_settings['flow_schedule']}, shift={flow_settings['flow_shift']}, "
              f"{flow_settings['cfg_mode']}, {steps}步, cfg{cfg}")

    print(f"  [模型] {unet_name or ckpt_name}")

    # 按作品注入画师串（Anima 系用 @ 前缀）
    if workflow in ARTIST_TAGS_WORKFLOWS:
        # 2026-10-11 用户规格：Anima 两条线的画师串**50% 触发**，且 CFG 与触发联动
        #   触发   → 画师串注入 + CFG 固定 3.7（画师串是强风格注入，需要更低 CFG 才不过火）
        #   不触发 → 不注入画师串 + CFG 随机 3.5~5.0（含两端）
        use_artist, cfg_from_artist = artist_roll()
        if use_artist:
            matched, combos = anima_artist_combos(_first_series(prompt_list))
            combo = random.choice(combos)
            if workflow not in ARTIST_TAGS_AT_PREFIX:
                combo = combo.replace("@", "")
            artist_combo = combo
            where = ("全局画师池（已解除作品限制）" if matched == "global"
                     else (f"作品分类「{matched}」" if matched
                           else "通用画师组（该作品无专属画师数据）"))
            cfg = cfg_from_artist
            print(f"  [画师串] 触发（50%）| {where}：{artist_combo}")
            print(f"  [CFG] 画师串已触发 → 固定 {cfg}")
        else:
            artist_combo = None
            cfg = cfg_from_artist
            print("  [画师串] 未触发（50%）→ 不注入画师串")
            print(f"  [CFG] 未触发画师串 → 随机取值 {cfg}（区间 3.5~5.0）")

    # 2026-10-11 用户规格：**在画师判定之后**，Anima 两条线再随机二选一权重
    #   （int8 / 原生 bf16）。切换走 config.set_active_unet()，同时更新
    #   ANIMA_UNET 与 WORKFLOW_SETTINGS → 构图、文件名标注（run_tag）都会跟着变。
    if workflow in ARTIST_TAGS_WORKFLOWS:
        variant = anima_model_roll()
        unet_name = set_active_unet(variant)     # ← 重新赋值，确保构图用新权重
        print(f"  [模型选择] 画师判定之后 → 随机选中 {variant}：{unet_name}")

    tag = run_tag(workflow, sampler=sampler, scheduler=scheduler)
    print(f"  [标注] 出图文件名前缀 = {tag}")

    all_cands = []          # 结构化候选（带 seed），供 GenResult 返回
    for i, item in enumerate(prompt_list):
        if isinstance(item, dict):
            positive = item["positive"]
            negative = item.get("negative", FALLBACK_NEGATIVE)
            identity = item.get("identity")
            theme = item.get("theme")
        else:
            positive = item
            negative = FALLBACK_NEGATIVE
            identity = None
            theme = None
        # 背景按主题清理（泳装 → 只留自然海滩）
        positive, removed_bg = sanitize_background(positive, theme)
        if removed_bg:
            print(f"  [背景清理] 主题「{theme}」删掉 {len(removed_bg)} 段不着调背景："
                  f"{removed_bg[0][:40]}…")

        # 2026-10-19 用户："nova 去掉眼睛相关的补强措施"
        #   → 瞳色去重 + 瞳色锁定只对 EYE_ENHANCE_WORKFLOWS 生效；
        #     其它线路（nova）完全交给 LLM 的瞳色描述，不加权、不加排色负面
        try:
            from config import EYE_ENHANCE_WORKFLOWS as _eye_wfs
        except Exception:
            _eye_wfs = ("animagine_xl",)
        if workflow in _eye_wfs:
            # 瞳色去重（删掉与 eye_colors 冲突的正文瞳色，避免自相矛盾）
            positive = normalize_eyes(positive, identity)
            # 瞳色锁定：官方瞳色锚定 + 负面排掉非官方色系
            positive, negative = eye_lock(positive, negative, identity,
                                          workflow=workflow)
        else:
            print(f"  [瞳色锁定] {workflow} 按用户要求关闭眼部补强（瞳色由提示词自由发挥）")

        # 按底模训练规范调整结构（Anima 官方前缀/画师串等）
        positive, negative = format_prompt(workflow, positive, negative,
                                           identity=identity, theme=theme,
                                           artist_combo=artist_combo)

        # 2026-10-23 用户：不要裁切，生成期就必须是正确景别。
        #   SDXL 两线在 72 词压缩前把景别加到最前，并压掉全身/腿脚。
        if workflow in ("animagine_xl", "nova_xl"):
            try:
                from config import (framing_theme_is_full as _fr_full,
                                    SDXL_FRAMING_POSITIVE as _fr_pos,
                                    SDXL_FRAMING_NEGATIVE as _fr_neg)
                if not _fr_full(theme):
                    positive = f"{_fr_pos}, {positive}"
                    negative = _dedup_csv(f"{negative}, {_fr_neg}")
                    print(f"  [景别强制] {workflow} 生成期景别：{_fr_pos}")
                else:
                    print(f"  [景别强制] {workflow} 全身主题，保留全身")
            except Exception as _fr_e:
                print(f"  [景别强制] 跳过（{type(_fr_e).__name__}）")

        print(f"  [候选生成 {i+1}/{len(prompt_list)}] 共 {candidates} 张……")
        candidate_paths = []
        for c in range(candidates):
            # seed 范围按工作流保守收敛（config.SEED_MAX，默认 2^31-1）
            seed = random.randint(1, seed_max_for(workflow))
            cand_path = os.path.join(output_dir, f"{tag}_cand_{i+1:02d}_{c+1}_seed{seed}.png")
            print(f"    候选 {c+1}: seed={seed}")
            try:
                path = _run_once(
                    workflow, positive, negative, seed, cand_path,
                    steps=steps, cfg=cfg,
                    sampler=sampler, scheduler=scheduler,
                    unet_name=unet_name, flow_settings=flow_settings,
                    tag=tag, ckpt_name=ckpt_name,
                )
                if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                    candidate_paths.append((path, seed))
            except Exception as e:
                print(f"    候选 {c+1} 失败：{e}")

        if not candidate_paths:
            print("  [出图失败] 所有候选都失败了")
            continue

        # === 打分选优 ===
        # kawaii 美学分本身是"二次元向"的打分器（实测纯写实图会被打到 1.5 分左右），
        # 现在 Z-Image 只保留二次元档，所以用它选优是合适的。
        print(f"  [评分] 对 {len(candidate_paths)} 张候选打分……")
        scored = []
        complex_eyes = _is_complex_eyes(identity) and EYE_VLM_CHECK
        if complex_eyes:
            print(f"  [眼睛复核] 检测到复杂瞳 → 将对候选做视觉复核（异常降权 {EYE_VLM_PENALTY}）")
        for path, seed in candidate_paths:
            s = _score_image(path)
            eye_bad, eye_why = (False, "")
            if complex_eyes:
                eye_bad, eye_why = _eye_abnormal(path)
                if eye_bad:
                    s = round(s - EYE_VLM_PENALTY, 3)
            pen = _top_edge_penalty(path)
            if pen:
                print(f"    [构图] 顶部疑似切到头发/头部 → 美学分扣 {pen:.2f}")
            s = round(s - pen, 3)
            scored.append((path, seed, s, eye_bad))
            eyemark = f"  [眼异常:{eye_why}]" if eye_bad else ""
            print(f"    {os.path.basename(path)} 美学分={s:.3f}{eyemark}")

        best_score = max(x[2] for x in scored)
        top_candidates = [x for x in scored if abs(x[2] - best_score) < 1e-6]
        chosen = random.choice(top_candidates)
        best_path, best_seed, best_score = chosen[0], chosen[1], chosen[2]
        # 记录本组所有候选（含 seed 与分数），供 GenResult 结构化返回
        for p_, sd_, sc_, eb_ in scored:
            all_cands.append({"path": p_, "seed": sd_, "score": sc_,
                              "prompt_index": i, "eye_abnormal": bool(eb_)})
        # 整批眼部全异常 → 额外追加候选（上限 EYE_VLM_MAX_EXTRA），择优后可覆盖
        if complex_eyes and scored and all(x[4] for x in scored):
            print(f"  [眼睛复核] 本批 {len(scored)} 张眼部全异常 → 追加 {EYE_VLM_MAX_EXTRA} 张重试")
            for _k in range(EYE_VLM_MAX_EXTRA):
                try:
                    seed_r = random.randint(1, seed_max_for(workflow))
                    path_r = os.path.join(output_dir,
                                          f"{tag}_cand_{i+1:02d}_retry{_k+1}_seed{seed_r}.png")
                    got = _run_once(workflow, positive, negative, seed_r, path_r,
                                    steps=steps, cfg=cfg, sampler=sampler,
                                    scheduler=scheduler, unet_name=unet_name,
                                    flow_settings=flow_settings, tag=tag,
                                    ckpt_name=ckpt_name)
                    if not (got and os.path.isfile(got)):
                        continue
                    s_r = _score_image(got)
                    bad_r, why_r = _eye_abnormal(got)
                    if bad_r:
                        s_r = round(s_r - EYE_VLM_PENALTY, 3)
                    scored.append((got, seed_r, s_r, bad_r))
                    print(f"    重试{_k+1}: seed={seed_r} 美学分={s_r:.3f} "
                          f"眼异常={bad_r}{(' ' + why_r) if why_r else ''}")
                    all_cands.append({"path": got, "seed": seed_r, "score": s_r,
                                      "prompt_index": i, "eye_abnormal": bool(bad_r)})
                except Exception as e:
                    print(f"    重试{_k+1} 失败：{type(e).__name__}")

        if len(top_candidates) > 1:
            print(f"  [选中] {os.path.basename(best_path)} seed={best_seed} "
                  f"美学分={best_score:.3f}（同分随机）")
        else:
            print(f"  [选中] {os.path.basename(best_path)} seed={best_seed} "
                  f"美学分={best_score:.3f}")

        selected_path = os.path.join(output_dir, f"{tag}_selected_{i+1:02d}.png")
        shutil.copy2(best_path, selected_path)
        selected_files.append(selected_path)

    # 兼容旧调用方：返回值本身仍是最终选中图路径列表；
    # 另携带 .selected / .candidates（带 seed 的真实候选图）结构化信息
    return GenResult(selected_files, candidates=all_cands)

# ---------------------------------------------------------------------------
# 2026-10-19 用户："不准截断，也不加兜底机制" → CLIP 分块兜底
#   SDXL CLIP 每块 77 tokens；长提示词必须切成多段 + ConditioningCombine 合并，
#   否则后半段（服装/场景/质量词）会被静默丢弃 ✗
# ---------------------------------------------------------------------------
CLIP_TOKEN_BUDGET_DEFAULT = 75


def ensure_clip_chunks(graph, node_id, clip_src, budget=None):
    """把 node_id 的正向提示词按预算切块；超预算时新增 CLIPTextEncode + ConditioningCombine。

    graph      : ComfyUI 图 dict
    node_id    : 正向 CLIPTextEncode 的节点 id（字符串）
    clip_src   : [<clip节点id>, 1]
    budget     : 每块词数预算（默认 75）
    返回：KSampler 的 positive 应指向的 [节点id, 0]
    """
    budget = int(budget or CLIP_TOKEN_BUDGET_DEFAULT)
    try:
        text = (graph[node_id].get("inputs") or {}).get("text") or ""
    except Exception:
        return [node_id, 0]
    parts = [x.strip() for x in text.split(",") if x.strip()]
    if not parts:
        return [node_id, 0]

    # 按词数累积切块（保持标签完整，不切半截）
    chunks, cur, cur_w = [], [], 0
    for tag in parts:
        w = len(tag.split())
        if cur and cur_w + w > budget:
            chunks.append(", ".join(cur))
            cur, cur_w = [], 0
        cur.append(tag)
        cur_w += w
    if cur:
        chunks.append(", ".join(cur))

    if len(chunks) == 1:
        return [node_id, 0]

    # 第 1 块放原节点，其余新增
    graph[node_id]["inputs"]["text"] = chunks[0]
    ids = [node_id]
    for i, ch in enumerate(chunks[1:], 1):
        nid = "%s_ck%d" % (node_id, i)
        graph[nid] = {"class_type": "CLIPTextEncode",
                      "inputs": {"text": ch, "clip": list(clip_src)},
                      "_meta": {"title": "positive_chunk_%d" % (i + 1)}}
        ids.append(nid)
    # ★ ConditioningCombine 只有 2 个输入 → 必须**链式两两合并**（4 块 = 3 个 combine）
    prev = [ids[0], 0]
    for i, nid in enumerate(ids[1:], 1):
        comb = "%s_comb%d" % (node_id, i)
        graph[comb] = {"class_type": "ConditioningCombine",
                       "inputs": {"conditioning_1": prev,
                                   "conditioning_2": [nid, 0]},
                       "_meta": {"title": "positive_combine_%d" % i}}
        prev = [comb, 0]
    print("  [CLIP 分块] 正向 %d 词超预算 %d → 切成 %d 块 + 链式 ConditioningCombine"
          % (len(text.split()), budget, len(chunks)))
    return prev


# ---------------------------------------------------------------------------
# 2026-10-19 兜底包装：建图完成后统一做 CLIP 分块
#   （不能在遍历 graph 的循环里加节点 → RuntimeError: dictionary changed size ✗）
# ---------------------------------------------------------------------------
_build_workflow_raw = _build_workflow


def _apply_clip_chunks(graph):
    """对图里所有 positive_prompt 节点做分块，并把 KSampler/anima_sampler 的重接好"""
    for nid, node in list(graph.items()):
        if (node.get("_meta") or {}).get("title") != "positive_prompt":
            continue
        clip_ref = (node.get("inputs") or {}).get("clip")
        if not clip_ref:
            continue
        try:
            ref = ensure_clip_chunks(graph, str(nid), list(clip_ref))
        except Exception as e:
            print("  [CLIP 分块] 跳过（%s）" % type(e).__name__)
            continue
        for n2 in graph.values():
            i2 = n2.get("inputs") or {}
            for key in ("positive",):
                v = i2.get(key)
                if isinstance(v, list) and str(v[0]) == str(nid):
                    i2[key] = ref


NO_COMPRESS = False  # 手工配方模式：绕过 SDXL 72 词压缩


def _build_workflow(*args, **kwargs):
    graph = _build_workflow_raw(*args, **kwargs)
    try:
        # ★ 方案 A：先压缩到单块，再分块兜底
        #   2026-10-19：**只对 SDXL 家族压缩**（CLIP 77 token 限制）
        #   Anima 用 Qwen 文本编码器（无 77 硬限制）→ 不压缩 ✗ 否则白砍词
        _wf_name = str(args[0]) if args else str(kwargs.get("workflow", ""))
        # 2026-10-23 用户：Nova 去掉 72 词压缩，与 Animagine 同步走长 prompt + CLIP 分块
        _need_compress = _wf_name in ("animagine_xl", "nova_xl")  # 2026-10-23 用户：SDXL 两线恢复压缩，人物优先
        for _nid, _nd in (list(graph.items()) if _need_compress else []):
            if (_nd.get("_meta") or {}).get("title") == "positive_prompt":
                _t = (_nd.get("inputs") or {}).get("text") or ""
                if len(_t.split()) > 72:
                    _nd["inputs"]["text"] = compress_prompt(_t, 72)
        # 2026-10-21 审计：分块只给**真有 77-token CLIP** 的 SDXL 两线。
        #   Anima 的 Qwen 编码器没有 77 硬限制，切块会把角色/服装拆进不同的
        #   conditioning（生产日志实测 208~252 词 → 3~4 块）→ 两条 Anima 线直接跳过。
        if _wf_name not in ("api", "anima_flow"):
            _apply_clip_chunks(graph)
    except Exception as e:
        print("  [CLIP 分块] 包装层异常（%s）" % type(e).__name__)
    return graph


# ---------------------------------------------------------------------------
# 2026-10-19 用户选 A：**压缩到单块 ≤75 词**（分块只是兜底）
#   策略：① 去掉 "with ..." 长描述从句 ② 去重 ③ 按优先级保留
#   优先级：构图 > 主体/角色 > 服装 > 眼/发 > 场景/光照 > 质量词 > 解剖/细节
# ---------------------------------------------------------------------------
_FRAME_WORDS = ("upper body", "three-quarter view", "close-up", "portrait", "cowboy shot",
                "full body", "shallow depth of field", "blurred background", "centered",
                "from side", "from below", "from above")
_PRIO = [
    # 2026-10-23 用户：人物优先（还原度/神态/动作），其次服装，最后才是质量/背景
    (80, ("furina", "raiden shogun", "hu tao", "hatsune miku", "genshin impact",
          "honkai", "vocaloid", "1girl", "solo", "upper body", "portrait",
          "cowboy shot", "full body", "looking at viewer", "smile", "blush",
          "expression", "half-closed", "gaze", "eyes", "eyebrow", "mouth",
          "standing", "sitting", "pose", "one hand", "hand", "arm", "holding",
          "tilt", "lean", "dynamic", "heterochromia", "twintails", "twin tails",
          "long hair", "aqua hair", "teal hair", "blue eyes", "red eyes",
          "purple eyes", "flower-shaped pupils", "hair ornament")),
    (70, ("mature female", "mature", "mature face", "adult", "adult proportions",
          "tall", "slender", "petite", "young woman", "teenager", "child",
          "curvy", "short", "wide hips", "thick thighs")),
    (65, ("sweater", "scarf", "beret", "bag", "headset", "shirt", "hat",
          "uniform", "kimono", "yukata", "gloves", "ribbon", "jacket")),
    (30, ("masterpiece", "best quality", "very aesthetic", "highres", "absurdres",
          "delicate skin", "detailed skin", "beautiful detailed eyes")),
    (20, ("ginkgo", "maple", "autumn", "park", "golden leaves", "orange leaves",
          "fallen leaves", "bench", "window", "snow", "sakura", "beach")),
]


def _tag_priority(tag):
    tl = tag.lower()
    for pr, keys in _PRIO:
        if any(k in tl for k in keys):
            return pr
    return 10


def compress_prompt(text, budget=72):
    """把提示词压到 budget 词内（保留高优先级标签、去重、去长从句）"""
    if not text:
        return text
    # ① 去掉 "... with ..." 长从句（保留主名词）
    import re as _re
    parts = [_re.sub(r"\s+with\s+.*$", "", x.strip()) for x in text.split(",")]
    # ② 去重（忽略大小写与权重括号影响）
    seen, uniq = set(), []
    for x in parts:
        if not x:
            continue
        k = _re.sub(r"[()]|:\d\.?\d*", "", x).strip().lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    if len(", ".join(uniq).split()) <= budget:
        return ", ".join(uniq)
    # ③ 分层保留（2026-10-20 用户要求）：
    #   第一层「必留」= 部分质量词 + 人物描述 + 基础背景(最多2个场景标签) + 衣物描述
    #   第二层「填充」= 其余（姿势/表情细节/光照/质量尾巴/解剖）按优先级补足
    _MUST_Q = ("masterpiece", "best quality", "very aesthetic", "highres", "absurdres",
               "amazing quality")
    _MUST_SUBJ = ("1girl", "solo", "1boy", "2girls")
    # 2026-10-21：角色/作品标签必须保下来（否则年龄锚点一挤，人物会变人）
    _MUST_CHAR = ("furina", "genshin impact", "hatsune miku", "vocaloid",
                  "raiden shogun", "hu tao", "march 7th", "honkai")
    # 2026-10-21：未来角色不一定在硬编码列表里 → 带转义括号的 danbooru 角色标签直接必留
    _MUST_ID = ("heterochromia",)
    # 2026-10-21 用户：体型/年龄锚点（成年/小体型/少女/儿童都按设定保留）→ 压缩必须保留
    _MUST_BODY = ("mature female", "mature", "mature face", "adult", "adult proportions",
                  "tall", "slender", "petite", "young woman", "teenager", "child",
                  "curvy", "short", "wide hips", "thick thighs")
    _MUST_EXPR = ("smile", "blush", "expression", "half-closed", "looking at viewer",
                  "gaze", "closed mouth", "open mouth", "eyebrow", "eyes", "mouth")
    _MUST_POSE = ("standing", "sitting", "pose", "one hand", "hand on", "holding",
                  "tilt", "lean", "action", "dynamic", "arm")
    # 半身构图时，会导致模型画到脚的服装词直接丢弃
    _OUTFIT_DROP_UPPER = ("boots", "feet", "shoes", "tights", "thighhighs", "kneehighs",
                          "skirt", "coat", "gown", "dress", "cape", "socks", "legs")
    _SCENE_KEYS = ("ginkgo", "maple", "autumn", "park", "street", "beach", "sea",
                   "bench", "snow", "sakura", "garden", "path", "lantern", "room",
                   "window", "trees", "leaves", "fairground", "church", "court")
    _OUTFIT_KEYS = ("sweater", "scarf", "skirt", "coat", "tights", "boots", "beret",
                    "bag", "shirt", "dress", "uniform", "kimono", "yukata", "hat",
                    "stockings", "gloves", "jacket", "hoodie", "vest", "ribbon")
    def _is_must(x, scene_count, upper=False):
        xl = x.lower()
        if upper and any(k in xl for k in _OUTFIT_DROP_UPPER):
            return False
        if "\\(" in x or "\\)" in x:      # 角色名转义标签（未来角色通用）
            return True
        if any(k in xl for k in _MUST_Q + _MUST_SUBJ + _MUST_CHAR + _MUST_ID
               + _MUST_BODY + _MUST_EXPR + _MUST_POSE + _OUTFIT_KEYS):
            return True
        if any(k in xl for k in _SCENE_KEYS):
            return scene_count[0] < 2      # 背景只留 2 个基础场景标签
        return False
    keep, used, scene_count = [], 0, [0]
    _upper = ("upper body" in text.lower()) or ("cowboy shot" in text.lower())
    # 第一层（先选必留，再按“人物 > 服装 > 质量/背景”排序）
    for i, x in enumerate(uniq):
        if used >= budget:
            break
        if not _is_must(x, scene_count, _upper):
            continue
        w = len(x.split())
        if used + w > budget:
            continue
        keep.append((i, x)); used += w
        if any(k in x.lower() for k in _SCENE_KEYS):
            scene_count[0] += 1
    # 第二层（剩余预算按优先级填充）
    kept_idx = {i for i, _ in keep}
    rest = [(_tag_priority(x), i, x) for i, x in enumerate(uniq) if i not in kept_idx]
    rest.sort(key=lambda t: (-t[0], t[1]))
    for pr, i, x in rest:
        # 半身时第二层也不再补回脚/裙/靴等会把景别拉全身的服装词
        if _upper and any(k in x.lower() for k in _OUTFIT_DROP_UPPER):
            continue
        # 背景最多 2 个标签，第二层也不再补
        if any(k in x.lower() for k in _SCENE_KEYS) and scene_count[0] >= 2:
            continue
        w = len(x.split())
        if used + w > budget:
            continue
        keep.append((i, x)); used += w
        if any(k in x.lower() for k in _SCENE_KEYS):
            scene_count[0] += 1
    keep.sort(key=lambda t: (-_tag_priority(t[1]), t[0]))
    out = ", ".join(x for _, x in keep)
    print("  [提示词压缩] %d 词 → %d 词（预算 %d）" % (len(text.split()), len(out.split()), budget))
    return out
