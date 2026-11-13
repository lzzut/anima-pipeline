import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import json, random, re, shutil
from comfyui_xy import ComfyUiClient
from anima_pipeline.config import (
    COMFY_URL,
    FALLBACK_NEGATIVE,
    WORKFLOW_SETTINGS,
    KSAMPLER_COMBOS,
    ANIMA_FLOW_SETTINGS,
    CLIP_SKIP,
    EXTRA_NEGATIVE,
    EYE_NEGATIVE,
    theme_scene_rule,
    ANIMA_PREFIX,
    ANIMA_NEGATIVE,
    anima_artist_combos,
    SANE_PLACEMENT_NEGATIVE,
    CLOTHING_CLARITY_NEGATIVE,
    SANE_PLACEMENT_WORKFLOWS,
    ANIMA_EXTRA_POSITIVE,
    EYE_LOCK,
    EYE_LOCK_WEIGHT,
    EYE_WRONG_COLORS,
    HIRES_FIX,
    HIRES_WORKFLOWS,
    HIRES_SCALE,
    HIRES_DENOISE,
    HIRES_STEPS,
    HIRES_CFG,
    ARTIST_TAGS_WORKFLOWS,
    ARTIST_TAGS_AT_PREFIX,
    seed_max_for,
    artist_roll,
    anima_model_roll,
    set_active_unet,
    EYE_TAG_MODE_WORKFLOWS,
    EYE_VLM_CHECK,
    EYE_VLM_PENALTY,
    EYE_VLM_TIMEOUT,
    EYE_VLM_MAX_EXTRA,
    IDENTITY_JUDGE_MAX_TOKENS,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
)
from anima_pipeline.prompting.prompt_style import style_directive

client = ComfyUiClient(url=COMFY_URL)
CANDIDATE_COUNT = 5


class GenResult(list):
    """Locally selected image paths plus all candidates, seeds and aesthetic scores."""

    def __init__(self, selected_paths, candidates=None):
        super().__init__(selected_paths or [])
        self.selected = list(selected_paths or [])
        self.candidates = list(candidates or [])

    def by_seed(self, seed):
        return next((c for c in self.candidates if c.get("seed") == seed), None)

    def candidate_paths(self):
        return [c["path"] for c in self.candidates]


WORKFLOW_TRACKS = {"anima": ("api", "anima_flow")}


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
        "animagine_xl": "workflow_animagine_xl.json (Animagine XL 4.0 / SDXL)",
        "nova_xl": "workflow_nova_xl.json (Nova Anime XL / Illustrious)",
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


_scorer = None


def _get_scorer():
    global _scorer
    if _scorer is None:
        from transformers import pipeline

        _scorer = pipeline(
            "image-classification", model="kawaimasa/kawai-aesthetic-scorer-convnextv2"
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


def identity_judge(image_path, name_en, verbose=True):
    """
    让视觉模型对照该角色**真实二创挖到的高频特征**客观核对出图。

    返回 dict：is_target_character / confidence / identity_score / visible_features /
              missing_features / expression / composition（失败返回 {}）。
    """
    try:
        import base64, io, httpx
        from PIL import Image
        from anima_pipeline.research.booru_client import appearance_tags

        _feat = [t.replace("_", " ") for t in appearance_tags(name_en, sample=40) or []][:12]
        canon = f"{name_en} 的官方/二创高频特征：{', '.join(_feat)}" if _feat else name_en
        im = Image.open(image_path).convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        q = f'目标角色：{canon}\n请客观核对图中可见特征，只输出 JSON：{{"is_target_character": true/false, "confidence": 0-100, "visible_features": [...], "missing_features": [...], "identity_score": 1-5, "expression": "...", "composition": "..."}}'
        r = httpx.post(
            (DEEPSEEK_BASE_URL or "").rstrip("/") + "/chat/completions",
            headers={
                "Authorization": "Bearer " + DEEPSEEK_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "max_tokens": IDENTITY_JUDGE_MAX_TOKENS,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": q},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + b64},
                            },
                        ],
                    }
                ],
            },
            timeout=180,
        )
        if r.status_code != 200:
            return {}
        txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.search("\\{.*\\}", txt, re.S)
        if not m:
            return {}
        d = json.loads(m.group(0))
        if verbose:
            print(
                f"  [视觉核对] 是否本人={d.get('is_target_character')}({d.get('confidence')}%) 身份分={d.get('identity_score')}/5 缺失={str(d.get('missing_features'))[:60]}"
            )
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
    if re.search("(left|right)\\s+eye", ec):
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
        from anima_pipeline.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        crop = img.crop((int(w * 0.15), int(h * 0.02), int(w * 0.85), int(h * 0.47)))
        crop.thumbnail((512, 512))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        prompt = '这是一张动漫角色插画的脸部特写。请判断：角色的眼睛有没有出现「虹膜/瞳孔缺失、整只眼糊成一块纯色、只剩一个高光点」这种异常？只回答 JSON：{"abnormal": true/false, "reason": "不超过20字"}'
        body = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                    ],
                }
            ],
            "max_tokens": 120,
        }
        r = httpx.post(
            (DEEPSEEK_BASE_URL or "").rstrip("/") + "/chat/completions",
            headers={
                "Authorization": "Bearer " + DEEPSEEK_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=EYE_VLM_TIMEOUT,
        )
        if r.status_code != 200:
            return (False, "")
        txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        m = re.search("\\{.*\\}", txt, re.S)
        if not m:
            return ("abnormal" in txt.lower() and "true" in txt.lower(), "")
        data = _json.loads(m.group(0))
        return (bool(data.get("abnormal")), str(data.get("reason") or "")[:40])
    except Exception:
        return (False, "")


def _score_image(image_path):
    try:
        from PIL import Image
    except ImportError:
        return random.random()
    try:
        scorer = _get_scorer()
        img = Image.open(image_path).convert("RGB")
        results = scorer(img)
        label_map = {"SS_tier": 5, "S_tier": 4, "A_tier": 3, "B_tier": 2, "C_tier": 1}
        total = 0.0
        for item in results:
            total += label_map.get(item["label"], 0) * item["score"]
        return total
    except Exception as e:
        print(f"    评分失败：{e}")
        return 0.0


EYE_COLOR_WORDS = (
    "blue",
    "sapphire",
    "azure",
    "aqua",
    "cyan",
    "teal",
    "purple",
    "violet",
    "green",
    "emerald",
    "amber",
    "golden",
    "crimson",
    "red",
    "pink",
    "yellow",
    "brown",
    "grey",
    "gray",
    "silver",
    "orange",
)
MAKEUP_WORDS = ("eyeliner", "eyeshadow", "eyelash", "eyebrow", "makeup", "eye shadow")


def sanitize_background(positive, theme):
    """
    按主题清理背景：泳装/沙滩就只留自然海滩元素，删掉建筑/城市/室内/人造粒子。

    问题来源：指令要求"场景三层都填满"，模型就把角色世界观搬进背景
    （芙宁娜 → 枫丹 → 城堡塔楼天际线 + 漂浮泡泡），泳装图完全不着调。
    命中禁止词时，用一句干净的海滩背景替换，避免删完背景变空、模型乱编。
    """
    rule_name, rule = theme_scene_rule(theme)
    if not rule:
        return (positive, [])
    kept, removed = ([], [])
    for frag in (positive or "").split(","):
        low = frag.lower()
        if any((re.search(pat, low) for pat in rule["forbid"])):
            removed.append(frag.strip())
            continue
        kept.append(frag.strip())
    body = ", ".join((k for k in kept if k))
    if removed:
        body = f"{body}, {rule['keep']}"
    return (body, removed)


def eye_lock(positive, negative, identity, workflow=None):
    """
    瞳色锁定：把官方瞳色写成带权重的标签（正向锚定），
    并把非官方色系从负面排掉（但排除角色本身就用那个色的情况）。

    为什么需要：底模自由发挥时紫/粉瞳色会盖过提示词，
    而"只压紫眼"会漂成绿眼 —— 所以要正向锚定蓝系 + 负向排掉其它色系。
    返回 (positive, negative)
    """
    if not EYE_LOCK:
        return (positive, negative)
    eye_colors = ((identity or {}).get("eye_colors") or "").strip()
    if not eye_colors:
        return (positive, negative)
    positive = positive.replace(eye_colors, "").strip(" ,")
    positive = re.sub(",\\s*,+", ", ", positive)
    parts = [p.strip() for p in eye_colors.split(",") if p.strip()]
    canon = eye_colors.lower()
    if "purple" in canon:
        canon += " violet"
    if "violet" in canon:
        canon += " purple"
    if workflow in EYE_TAG_MODE_WORKFLOWS:
        tags, colors = ([], [])
        for p in parts:
            if p.startswith("(") and p.endswith(")"):
                tags.append(p)
                continue
            m = re.search("(?:left|right)\\s+eye\\s+(.+)$", p, re.I)
            if m:
                color = m.group(1).strip()
                colors.append(color if color.lower().endswith("eyes") else f"{color} eyes")
            else:
                tags.append(p)
        tags.extend(colors)
        if tags and (not any((t.lower() == "detailed eyes" for t in tags))):
            tags.append("detailed eyes")
        if tags:
            positive = f"{positive}, {', '.join(tags)}"
        wrong = [w for w in EYE_WRONG_COLORS if w.split()[0] not in canon]
        if wrong:
            negative = _dedup_csv(f"{negative}, {', '.join(wrong)}")
        return (positive, negative)
    weighted = []
    for p in parts:
        if p.startswith("(") and p.endswith(")"):
            weighted.append(p)
        elif re.search("(left|right)\\s+eye", p, re.I):
            weighted.append(f"({p}:{EYE_LOCK_WEIGHT})")
        else:
            weighted.append(p)
    positive = f"{positive}, {', '.join(weighted)}"
    wrong = [w for w in EYE_WRONG_COLORS if w.split()[0] not in canon]
    if wrong:
        negative = _dedup_csv(f"{negative}, {', '.join(wrong)}")
    return (positive, negative)


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
        has_color = any((c in low for c in EYE_COLOR_WORDS))
        mentions_eye = any((k in low for k in ("eye", "iris", "pupil", "heterochrom")))
        is_makeup = any((m in low for m in MAKEUP_WORDS))
        if mentions_eye and has_color and (not is_makeup):
            continue
        kept.append(frag.strip())
    body = ", ".join((k for k in kept if k))
    if weight:
        parts = [p.strip() for p in eye_colors.split(",") if p.strip()]
        eye_colors = ", ".join(
            (p if p.startswith("(") and p.endswith(")") else f"({p}:{weight})" for p in parts)
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


_SUBJECT_RE = re.compile("(1girl|1boy|1other|2girls|multiple girls)", re.I)


def _dedup_csv(text):
    seen, out = (set(), [])
    for p in (text or "").split(","):
        k = p.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(p.strip())
    return ", ".join(out)


def _norm_tag(frag):
    """归一化一个标签片段用于比较：去掉转义符/括号，小写，下划线转空格"""
    return re.sub("[\\\\()\\[\\]]", "", frag or "").strip().lower().replace("_", " ")


def _first_series(prompt_list):
    """取第一条提示词的角色作品标签（同一角色的多套提示词共用一个画风串）"""
    for item in prompt_list or []:
        if isinstance(item, dict):
            s = (item.get("identity") or {}).get("series_en")
            if s:
                return s
    return None


def _insert_after_series(positive, inject, identity):
    """
    把画风串插到「作品名」标签之后（danbooru 惯例的标签顺序）。

    注意：必须按**逗号分段**匹配整段标签，不能用子串查找 ——
    否则 "genshin impact" 会先命中角色标签 `furina \\(genshin impact\\)` 内部，
    画风串就会被塞进角色名括号里（实测踩过这个坑）。
    """
    series = _norm_tag((identity or {}).get("series_en") or "")
    frags = [f.strip() for f in (positive or "").split(",")]
    if series:
        for i, frag in enumerate(frags):
            if _norm_tag(frag) == series:
                frags.insert(i + 1, inject)
                return re.sub("\\s{2,}", " ", ", ".join(frags))
    m = _SUBJECT_RE.search(positive or "")
    if m:
        comma = positive.find(",", m.end())
        if comma > 0:
            return f"{positive[:comma]}, {inject}{positive[comma:]}"
    return f"{inject}, {positive}"


def format_prompt(workflow, positive, negative, identity=None, theme=None, artist_combo=None):
    """
    按底模的训练规范调整提示词结构（不同底模规范不一样，别一套打天下）：

    · animagine_xl（Animagine XL 4.0，官方卡）：
        结构 = 1girl → 角色 → 作品 → rating → 其它 → **质量/分数标签放最后**
        质量要用 score 类：masterpiece, high score, great score, absurdres
        负面要含 low score / bad score / average score
    · 其他工作流：保持原样（Illustrious 系与 Anima/Z-Image 都是质量词前置）
    """
    if workflow in ("api", "anima_flow") and (identity or {}).get("anima_prompt_contract"):
        from anima_pipeline.prompting.anima_prompt_pipeline import finalize_render

        return finalize_render(positive, negative, identity, artist_combo)
    st = WORKFLOW_SETTINGS.get(workflow, {})
    if workflow in ("api", "anima_flow"):
        m = _SUBJECT_RE.search(positive or "")
        if m:
            body = positive[m.start() :].strip(" ,")
            positive = f"{ANIMA_PREFIX}, {body}"
        elif positive:
            positive = f"{ANIMA_PREFIX}, {positive}"
        if artist_combo:
            positive = _insert_after_series(positive, artist_combo, identity)
        negative = _dedup_csv(f"{ANIMA_NEGATIVE}, {negative}")
        if ANIMA_EXTRA_POSITIVE:
            positive = f"{positive}, {ANIMA_EXTRA_POSITIVE}"
    try:
        from anima_pipeline.config import FRAMING_NEGATIVE_WORKFLOWS as _fpw, NOVA_FRAMING_NEGATIVE as _nfn
    except Exception:
        _fpw, _nfn = ((), "")
    if workflow in _fpw and _nfn:
        negative = _dedup_csv(f"{negative}, {_nfn}")
    if workflow in SANE_PLACEMENT_WORKFLOWS:
        negative = _dedup_csv(f"{negative}, {SANE_PLACEMENT_NEGATIVE}, {CLOTHING_CLARITY_NEGATIVE}")
    if st.get("quality_at_end"):
        m = _SUBJECT_RE.search(positive or "")
        if m:
            rest = positive[m.start() :].strip(" ,")
            positive = f"{rest}, {st.get('quality_tags', '')}".strip(" ,")
        elif st.get("quality_tags"):
            positive = f"{positive}, {st.get('quality_tags')}"
    if st.get("negative"):
        negative = _dedup_csv(f"{st['negative']}, {negative}")
    try:
        from anima_pipeline.config import LIMB_POSE_NEGATIVE as _lpn, LIMB_POSE_WORKFLOWS as _lpw
    except Exception:
        _lpn, _lpw = ("", ())
    if _lpn and workflow in _lpw:
        negative = _dedup_csv(f"{negative}, {_lpn}")
    if workflow == "animagine_xl":
        try:
            from anima_pipeline.config import ANIMAGINE_FRAMING_NEGATIVE as _afn
        except Exception:
            _afn = ""
        if _afn:
            negative = _dedup_csv(f"{negative}, {_afn}")
    if EXTRA_NEGATIVE:
        negative = _dedup_csv(f"{negative}, {EXTRA_NEGATIVE}")
    try:
        from anima_pipeline.config import BANNED_THEME_NEGATIVE as _btn

        if _btn:
            negative = _dedup_csv(f"{negative}, {_btn}")
    except Exception:
        pass
    try:
        from anima_pipeline.config import LINE_EXTRA_NEGATIVES as _line_neg

        _extra_neg = (_line_neg or {}).get(workflow, "")
        if _extra_neg:
            negative = _dedup_csv(f"{negative}, {_extra_neg}")
    except Exception:
        pass
    eye_neg = "" if workflow in ("api", "anima_flow") else eye_negative(identity)
    if eye_neg:
        negative = _dedup_csv(f"{negative}, {eye_neg}")
    rule_name, rule = theme_scene_rule(theme)
    if rule and rule.get("negative"):
        negative = _dedup_csv(f"{negative}, {rule['negative']}")
    if workflow in ("api", "anima_flow"):
        close_shots = {"close-up", "portrait"}
        near_markers = set(close_shots)
        from anima_pipeline.config import ANIMA_COMPLETE_HEAD_PRIORITY

        if ANIMA_COMPLETE_HEAD_PRIORITY:
            near_markers.update(("collarbone-up", "chest-up"))
        if any((part.strip().lower() in near_markers for part in positive.split(","))):
            negative = ", ".join(
                (
                    part.strip()
                    for part in negative.split(",")
                    if part.strip() and part.strip().lower() not in close_shots
                )
            )
    return (positive, negative)


def _build_workflow(
    workflow,
    positive,
    negative,
    seed,
    steps,
    cfg,
    sampler=None,
    scheduler=None,
    unet_name=None,
    flow_settings=None,
    tag=None,
    ckpt_name=None,
):
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
            node["inputs"].update(
                {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                }
            )
        elif title == "anima_sampler":
            node["inputs"].update({"seed": seed, "steps": steps, "cfg": cfg})
            if flow_settings:
                node["inputs"].update(flow_settings)
        elif class_type == "UNETLoader" and unet_name:
            node["inputs"]["unet_name"] = unet_name
        elif class_type == "CheckpointLoaderSimple" and ckpt_name:
            node["inputs"]["ckpt_name"] = ckpt_name
        elif class_type == "CLIPSetLastLayer":
            node["inputs"]["stop_at_clip_layer"] = CLIP_SKIP
        elif class_type == "SaveImage" and tag:
            node["inputs"]["filename_prefix"] = tag
    hires_on = (
        HIRES_FIX
        and workflow in HIRES_WORKFLOWS
        and any((n.get("_meta", {}).get("title") == "hires_sampler" for n in graph.values()))
    )
    for node in graph.values():
        title = node.get("_meta", {}).get("title", "")
        if title == "hires_sampler":
            node["inputs"].update(
                {
                    "steps": HIRES_STEPS,
                    "cfg": HIRES_CFG,
                    "denoise": HIRES_DENOISE,
                    "seed": (seed + 1) % 2**32,
                }
            )
            if sampler:
                node["inputs"]["sampler_name"] = sampler
            if scheduler:
                node["inputs"]["scheduler"] = scheduler
        elif title == "latent_upscale":
            base = next(
                (n for n in graph.values() if n.get("class_type") == "EmptyLatentImage"), None
            )
            if base:
                w = int(base["inputs"].get("width", 896) * HIRES_SCALE)
                h = int(base["inputs"].get("height", 1152) * HIRES_SCALE)
                node["inputs"].update({"width": w // 8 * 8, "height": h // 8 * 8})
    if any((n.get("_meta", {}).get("title") == "hires_sampler" for n in graph.values())) and (
        not hires_on
    ):
        for node in graph.values():
            if node.get("class_type") == "SaveImage":
                node["inputs"]["images"] = ["7", 0]
    return graph


def _run_once(
    workflow,
    positive,
    negative,
    seed,
    output_path,
    steps=30,
    cfg=5.0,
    sampler=None,
    scheduler=None,
    unet_name=None,
    flow_settings=None,
    tag=None,
    ckpt_name=None,
    audit_dir=None,
):
    graph = _build_workflow(
        workflow,
        positive,
        negative,
        seed,
        steps,
        cfg,
        sampler,
        scheduler,
        unet_name,
        flow_settings,
        tag,
        ckpt_name,
    )
    if audit_dir:
        from anima_pipeline.prompting.anima_prompt_pipeline import immutable_json, sha

        immutable_json(
            audit_dir,
            "submitted_graph",
            {
                "graph": graph,
                "graph_sha256": sha(graph),
                "output_path": output_path,
                "positive": positive,
                "negative": negative,
                "pair_sha256": sha([positive, negative]),
                "seed": seed,
            },
        )
    results = client.process_workflow(graph)
    for result in results:
        if result.file_type == "image":
            result.save(output_path)
            return output_path
    return None


def generate_images(
    prompt_list,
    output_dir,
    workflow=None,
    steps=None,
    cfg=None,
    candidates=CANDIDATE_COUNT,
    seeds=None,
    run_retries=0,
    before_retry=None,
):
    """
    出图并自动打分选优。

    workflow: "api" / "anima_flow" / "animagine_xl" / "nova_xl"，传 None 则四选一随机。
              - api          : KSampler，采样器组合从 KSAMPLER_COMBOS 随机抽（每套自带步数/CFG）
              - anima_flow   : AnimaFlowCorrectiveSampler（cfg5/50步，项目统一）
              - animagine_xl : Animagine XL 4.0（官方卡：28步/cfg5/euler_a，质量词放末尾）
              - nova_xl      : Nova Anime XL（Illustrious 系：28步/cfg5/euler_a）
    steps/cfg: 显式传入则覆盖该工作流的默认值。
    seeds: 可选 seed 列表（2026-10-27 双通道）：给了就让每条提示词的第 c 张候选都用 seeds[c]；
           不给 = 原来的每张随机。画风/CFG/权重/采样组合本来就是每次调用摇一次、各条共用。
    run_retries: 单张候选失败时，用同一 seed、同一参数原样重试的次数（默认 0 = 原行为）。
    before_retry: 每次重试前调用（如 ensure_comfyui）；它自己出错不影响重试。
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
        print(f"  [采样组合] KSampler {sampler} + {scheduler}, {steps}步, cfg{cfg}  ← {source}")
    elif workflow == "anima_flow":
        steps = st["steps"] if steps is None else steps
        cfg = st["cfg"] if cfg is None else cfg
        flow_settings = dict(ANIMA_FLOW_SETTINGS)
        print("  [工作流] workflow_anima_flow.json")
        print(
            f"  [采样组合] {flow_settings['flow_solver']} + {flow_settings['flow_schedule']}, shift={flow_settings['flow_shift']}, {flow_settings['cfg_mode']}, {steps}步, cfg{cfg}"
        )
    if workflow in ("animagine_xl", "nova_xl"):
        steps = st["steps"] if steps is None else steps
        cfg = st["cfg"] if cfg is None else cfg
        sampler, scheduler = (st["sampler"], st["scheduler"])
        print(f"  [工作流] {describe_workflow(workflow)}")
        print(
            f"  [采样组合] {sampler} + {scheduler}, {steps}步, cfg{cfg}, CLIP skip={CLIP_SKIP}, 896x1152"
        )
        print("  [提示词] 直出 Danbooru 标签（该底模认识角色标签，负面提示词正常生效）")
    print(f"  [模型] {unet_name or ckpt_name}")
    if workflow in ARTIST_TAGS_WORKFLOWS:
        use_artist, cfg_from_artist = artist_roll()
        if use_artist:
            matched, combos = anima_artist_combos(_first_series(prompt_list))
            combo = random.choice(combos)
            if workflow not in ARTIST_TAGS_AT_PREFIX:
                combo = combo.replace("@", "")
            artist_combo = combo
            where = (
                "全局画风池（已解除作品限制）"
                if matched == "global"
                else f"作品分类「{matched}」" if matched else "通用画风组（该作品无专属画风数据）"
            )
            cfg = cfg_from_artist
            print(f"  [画风串] 触发（50%）| {where}：{artist_combo}")
            print(f"  [CFG] 画风串已触发 → 固定 {cfg}")
        else:
            artist_combo = None
            cfg = cfg_from_artist
            print("  [画风串] 未触发（50%）→ 不注入画风串")
            print(f"  [CFG] 未触发画风串 → 随机取值 {cfg}（区间 3.5~5.0）")
    if workflow in ARTIST_TAGS_WORKFLOWS:
        variant = anima_model_roll()
        unet_name = set_active_unet(variant)
        print(f"  [模型选择] 画风判定之后 → 随机选中 {variant}：{unet_name}")
    tag = run_tag(workflow, sampler=sampler, scheduler=scheduler)
    print(f"  [标注] 出图文件名前缀 = {tag}")
    all_cands = []
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
        _v2 = bool((identity or {}).get("anima_prompt_contract")) and workflow in (
            "api",
            "anima_flow",
        )
        _prompt_records = {}
        positive, removed_bg = (positive, []) if _v2 else sanitize_background(positive, theme)
        if removed_bg:
            print(
                f"  [背景清理] 主题「{theme}」删掉 {len(removed_bg)} 段不着调背景：{removed_bg[0][:40]}…"
            )
        try:
            from anima_pipeline.config import EYE_ENHANCE_WORKFLOWS as _eye_wfs
        except Exception:
            _eye_wfs = ("animagine_xl",)
        if workflow in _eye_wfs:
            positive = normalize_eyes(positive, identity)
            positive, negative = eye_lock(positive, negative, identity, workflow=workflow)
        else:
            print(f"  [瞳色] {workflow} 使用经核验的事实及最终提示词")
        positive, negative = format_prompt(
            workflow, positive, negative, identity=identity, theme=theme, artist_combo=artist_combo
        )
        if workflow in ("animagine_xl", "nova_xl"):
            try:
                from anima_pipeline.config import (
                    framing_theme_is_full as _fr_full,
                    SDXL_FRAMING_POSITIVE as _fr_pos,
                    SDXL_FRAMING_NEGATIVE as _fr_neg,
                )

                if not _fr_full(theme):
                    positive = f"{_fr_pos}, {positive}"
                    negative = _dedup_csv(f"{negative}, {_fr_neg}")
                    print(f"  [景别强制] {workflow} 生成期景别：{_fr_pos}")
                else:
                    print(f"  [景别强制] {workflow} 全身主题，保留全身")
            except Exception as _fr_e:
                print(f"  [景别强制] 跳过（{type(_fr_e).__name__}）")
        print(f"  [候选生成 {i + 1}/{len(prompt_list)}] 共 {candidates} 张……")
        prepared_variants = []
        if (
            isinstance(item, dict)
            and item.get("candidate_prompts")
            and (workflow in ("api", "anima_flow"))
        ):
            for variant_prompt in item["candidate_prompts"]:
                variant_positive = variant_prompt["positive"]
                if not _v2:
                    variant_positive, _ = sanitize_background(variant_positive, theme)
                variant_negative = variant_prompt.get(
                    "negative", item.get("negative", FALLBACK_NEGATIVE)
                )
                if workflow in _eye_wfs:
                    variant_positive = normalize_eyes(variant_positive, identity)
                    variant_positive, variant_negative = eye_lock(
                        variant_positive, variant_negative, identity, workflow=workflow
                    )
                variant_positive, variant_negative = format_prompt(
                    workflow,
                    variant_positive,
                    variant_negative,
                    identity=identity,
                    theme=theme,
                    artist_combo=artist_combo,
                )
                prepared_variants.append((variant_positive, variant_negative))
            from anima_pipeline import config as _same_cfg

            if getattr(_same_cfg, "ANIMA_SAME_PROMPT_SEEDS", False):
                prepared_variants = prepared_variants[:1]
        candidate_paths = []
        for c in range(candidates):
            candidate_positive, candidate_negative = (
                prepared_variants[c % len(prepared_variants)]
                if prepared_variants
                else (positive, negative)
            )
            seed = (
                int(seeds[c])
                if seeds and c < len(seeds)
                else random.randint(1, seed_max_for(workflow))
            )
            _image_dir = output_dir
            if _v2:
                from anima_pipeline.prompting.anima_prompt_pipeline import immutable_json, sha, token_diagnostics

                _image_dir = os.path.join(
                    output_dir, "图片", "全部候选图", item.get("channel", str(i + 1))
                )
                os.makedirs(_image_dir, exist_ok=True)
            cand_path = os.path.join(_image_dir, f"{tag}_cand_{i + 1:02d}_{c + 1}_seed{seed}.png")
            if _v2:
                from anima_pipeline.config import ANIMA_TOKENIZER_ROOT

                _prompt_records[cand_path] = immutable_json(
                    os.path.join(output_dir, "数据", "候选记录"),
                    "candidate",
                    {
                        "channel": item.get("channel"),
                        "theme": theme,
                        "candidate_index": c,
                        "seed": seed,
                        "output_path": cand_path,
                        "positive": candidate_positive,
                        "negative": candidate_negative,
                        "pair_sha256": sha([candidate_positive, candidate_negative]),
                        "prompt_session_audit": item.get("prompt_session_audit"),
                        "token_diagnostics": token_diagnostics(
                            candidate_positive, candidate_negative, ANIMA_TOKENIZER_ROOT
                        ),
                    },
                )
            print(f"    候选 {c + 1}: seed={seed}")
            for _attempt in range(1 + max(0, int(run_retries or 0))):
                if _attempt:
                    print(f"    候选 {c + 1} 重试 {_attempt}/{run_retries}（同 seed、同参数）")
                    if before_retry:
                        try:
                            before_retry()
                        except Exception as _e_br:
                            print(f"    重试前检查失败：{type(_e_br).__name__}")
                try:
                    path = _run_once(
                        workflow,
                        candidate_positive,
                        candidate_negative,
                        seed,
                        cand_path,
                        steps=steps,
                        cfg=cfg,
                        sampler=sampler,
                        scheduler=scheduler,
                        unet_name=unet_name,
                        flow_settings=flow_settings,
                        tag=tag,
                        ckpt_name=ckpt_name,
                        **(
                            {"audit_dir": os.path.join(output_dir, "数据", "实际工作流")}
                            if _v2
                            else {}
                        ),
                    )
                    if path and os.path.isfile(path) and (os.path.getsize(path) > 0):
                        candidate_paths.append((path, seed))
                        break
                except Exception as e:
                    print(f"    候选 {c + 1} 失败：{e}")
        if not candidate_paths:
            print("  [出图失败] 所有候选都失败了")
            continue
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
        best_score = max((x[2] for x in scored))
        top_candidates = [x for x in scored if abs(x[2] - best_score) < 1e-06]
        chosen = random.choice(top_candidates)
        best_path, best_seed, best_score = (chosen[0], chosen[1], chosen[2])
        for p_, sd_, sc_, eb_ in scored:
            all_cands.append(
                {
                    "path": p_,
                    "seed": sd_,
                    "score": sc_,
                    "prompt_index": i,
                    "eye_abnormal": bool(eb_),
                    **(
                        {"channel": item.get("channel"), "prompt_audit": _prompt_records.get(p_)}
                        if _v2
                        else {}
                    ),
                }
            )
        if complex_eyes and scored and all((x[3] for x in scored)):
            print(f"  [眼睛复核] 本批 {len(scored)} 张眼部全异常 → 追加 {EYE_VLM_MAX_EXTRA} 张重试")
            for _k in range(EYE_VLM_MAX_EXTRA):
                try:
                    seed_r = random.randint(1, seed_max_for(workflow))
                    path_r = os.path.join(
                        output_dir, f"{tag}_cand_{i + 1:02d}_retry{_k + 1}_seed{seed_r}.png"
                    )
                    got = _run_once(
                        workflow,
                        positive,
                        negative,
                        seed_r,
                        path_r,
                        steps=steps,
                        cfg=cfg,
                        sampler=sampler,
                        scheduler=scheduler,
                        unet_name=unet_name,
                        flow_settings=flow_settings,
                        tag=tag,
                        ckpt_name=ckpt_name,
                    )
                    if not (got and os.path.isfile(got)):
                        continue
                    s_r = _score_image(got)
                    bad_r, why_r = _eye_abnormal(got)
                    if bad_r:
                        s_r = round(s_r - EYE_VLM_PENALTY, 3)
                    scored.append((got, seed_r, s_r, bad_r))
                    print(
                        f"    重试{_k + 1}: seed={seed_r} 美学分={s_r:.3f} 眼异常={bad_r}{(' ' + why_r if why_r else '')}"
                    )
                    all_cands.append(
                        {
                            "path": got,
                            "seed": seed_r,
                            "score": s_r,
                            "prompt_index": i,
                            "eye_abnormal": bool(bad_r),
                        }
                    )
                except Exception as e:
                    print(f"    重试{_k + 1} 失败：{type(e).__name__}")
        if complex_eyes:
            best_score = max(x[2] for x in scored)
            top_candidates = [x for x in scored if abs(x[2] - best_score) < 1e-6]
            chosen = random.choice(top_candidates)
            best_path, best_seed, best_score = chosen[:3]
        if len(top_candidates) > 1:
            print(
                f"  [选中] {os.path.basename(best_path)} seed={best_seed} 美学分={best_score:.3f}（同分随机）"
            )
        else:
            print(
                f"  [选中] {os.path.basename(best_path)} seed={best_seed} 美学分={best_score:.3f}"
            )
        _selected_dir = os.path.join(output_dir, "图片", "程序选中图") if _v2 else output_dir
        os.makedirs(_selected_dir, exist_ok=True)
        selected_path = os.path.join(_selected_dir, f"{tag}_selected_{i + 1:02d}.png")
        shutil.copy2(best_path, selected_path)
        selected_files.append(selected_path)
    from anima_pipeline.prompting.anima_prompt_pipeline import immutable_json

    immutable_json(
        os.path.join(output_dir, "数据"),
        "aesthetic_selection",
        {
            "scorer": "kawaimasa/kawai-aesthetic-scorer-convnextv2",
            "candidates": all_cands,
            "selected": selected_files,
        },
    )
    if any(
        (
            (p.get("identity") or {}).get("anima_prompt_contract")
            for p in prompt_list
            if isinstance(p, dict)
        )
    ):
        from anima_pipeline.rendering.anima_prompt_storage import write_gallery

        write_gallery(output_dir, all_cands, selected_files)
    return GenResult(selected_files, candidates=all_cands)
