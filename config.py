# config.py
import json
import os
import re
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
WORKFLOW_PATH = os.path.join(BASE, "workflow_api.json")
WORKFLOW_ANIMA_FLOW_PATH = os.path.join(BASE, "workflow_anima_flow.json")

# CLIP skip（SDXL 动漫模型惯例 -2）；写在两条新工作流的 CLIPSetLastLayer 上
CLIP_SKIP = -2

# ---------------------------------------------------------------------------
# 工作流池：每次跑图随机选一条
# 工作流池：每次跑图随机选一条（workflow == None 时）
#   "api"          → workflow_api.json            Anima-2.9B（KSampler，采样组合再随机）
#   "anima_flow"   → workflow_anima_flow.json     Anima-2.9B（AnimaFlow 采样器）
# 2026-10-24 用户：只留 Anima-2.9B 两条线路。
WORKFLOW_POOL = ["api", "anima_flow"]


# int8 版 Anima 比 bf16 快 31%，画质肉眼无差（实测 78.7s vs 114.6s）
# ---------------------------------------------------------------------------
# 模型权重文件名：**唯一来源**（2026-10-11 收技术债）
#
# 踩过的坑：以前只写 `ANIMA_UNET = "..."`，而它是在**导入期**被读进 WORKFLOW_SETTINGS 的，
# 所以运行期改 `config.ANIMA_UNET` 根本不生效 —— 看着像开关，实际是死值。
# 现在统一为：常量在下，WORKFLOW_SETTINGS 引用常量，切换只走 `set_active_unet()`。
# ---------------------------------------------------------------------------
ANIMA_UNET_INT8 = "Anima-2.9B-preview-v1_int8_convrot.safetensors"   # 2.87 GB，快 1.6×
ANIMA_UNET_NATIVE = "Anima-2.9B-preview-v1.safetensors"              # 5.44 GB，原生 bf16

ANIMA_UNET = ANIMA_UNET_INT8        # 当前激活值（兼容别名；生效以 WORKFLOW_SETTINGS 为准）

WORKFLOW_SETTINGS = {
    "api": {
        "path": WORKFLOW_PATH,
        "unet": ANIMA_UNET,
        "steps": 30,
        "cfg": 5.0,
    },
    "anima_flow": {
        "path": WORKFLOW_ANIMA_FLOW_PATH,
        "unet": ANIMA_UNET,
        "steps": 30,
        "cfg": 5.0,
    },
}

# ---------------------------------------------------------------------------
# 提示词"减法"清单（2026-10-10 复盘修正：只删真正有害的，别删角色气质词）
#
#   第一版我删太狠了 —— 连 `delicate elegant features`（优雅感）都删了，
#   结果芙宁娜被拉成"通用可爱脸"，反而不像。芙宁娜是优雅成熟型角色，
#   气质词要留。真正有害的是这些把人往"通用萌妹"拉的词。
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 提示词干预总开关（2026-10-10 二次复盘：全部回滚为"最小干预"）
#
#   走过的弯路：先删通用美颜词 → 角色变通用脸；再加瞳色权重 → 眼睛漂紫；
#   再加紫眼负面 → 眼睛又漂绿。**越加约束越跑偏**，就是"用力过猛"。
#   结论：除了下面这两条真正站得住的，其余干预全部关闭。
# ---------------------------------------------------------------------------
GENERIC_FACE_TAGS = ()          # 关闭：删了"优雅感"反而让芙宁娜变通用萌妹

# 构图防裁切（cfg>1 的工作流才生效）
EXTRA_NEGATIVE = (
    "cropped head, cut off headwear, out of frame, close-up, "
    # 2026-10-12 按用户手跑标杆补齐负面（标杆负面约 688 字符，我们原约 416）
    "bad anatomy, bad proportions, extra fingers, missing fingers, fused fingers, "
    "mutated hands, missing limbs, malformed limbs, extra digits, fewer digits, "
    "watermark, signature, text, jpeg artifacts, lowres, worst quality, low quality, "
    "blurry, artist name"
)


# 眼部负面（治"左眼涂抹感 / 发丝压眼糊成一片"）；2026-10-21 合并掉旧的空定义，
# 全项目只保留这一处（此前 line ~340 还有一份同名覆盖，容易误读）。
EYE_NEGATIVE = ("smudged eye, blurry eye, asymmetrical eyes, hair covering eye, "
                "eye covered by hair, one eye hidden")

# ---------------------------------------------------------------------------
# 瞳色锁定（2026-10-10 二次修复）
#
# 问题复现：底模自由发挥的瞳色盖过了提示词，紫/粉眼又回来了。
# 之前"只压紫眼"会导致漂成绿眼，所以这次改成**正向锚定 + 负向只排非官方色**：
#   · 正向：官方瞳色写成**带权重的 danbooru 式标签**（SDXL 吃权重）
#           heterochromia, blue eyes, (left eye dark blue:1.25), (right eye light blue:1.25)
#   · 负向：把非官方色系排掉（紫/粉/品红/红/绿/黄/橙），
#           但会自动排除"角色本身就是那个颜色"的情况
# 关掉：EYE_LOCK = False
# ---------------------------------------------------------------------------
EYE_LOCK = True   # 2026-10-23 用户：Nova 眼睛也要修 → 重新开启，并覆盖 Nova
EYE_LOCK_WEIGHT = 1.25
EYE_WRONG_COLORS = (
    "purple eyes", "violet eyes", "pink eyes", "magenta eyes", "red eyes",
    "green eyes", "yellow eyes", "orange eyes", "amber eyes",
)

# ---------------------------------------------------------------------------
# 主题 → 背景规则（2026-10-10）
#   问题：指令要求"场景三层都填满具体元素"，模型就把角色世界观搬进背景
#   （芙宁娜 → 枫丹 → 城堡塔楼天际线 + 漂浮泡泡），泳装图完全不着调。
#   规则：泳装/沙滩主题只允许自然海滩元素，禁止建筑/城市/室内/人造粒子。
# ---------------------------------------------------------------------------
THEME_SCENE_RULES = {
    "beach": {
        "keywords": ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "度假"),
        # 命中禁止词后，用这句简单背景替换（自然、干净）
        "keep": ("simple beach background, calm blue sea, sandy shore, "
                 "blue sky with a few soft clouds"),
        "forbid": (
            # 建筑/城市（用词边界，避免 towering→tower、headroom→room 这类误伤）
            r"\bcity\b", r"\bskyline\b", r"\bcastles?\b", r"\bcathedral\b",
            r"\bchurch\b", r"\bspires?\b", r"\btowers?\b", r"\bbuildings?\b",
            r"\barchitecture\b", r"\bmetropolis\b", r"\burban\b", r"\bdowntown\b",
            r"\bneon\b", r"\brooftop\b", r"\bindoors?\b", r"\binterior\b",
            r"\bstudio\b", r"\bchateau\b", r"\bpalace\b",
            # 泳池
            r"swimming pool", r"pool deck", r"poolside",
            # 人造粒子（只匹配成短语，避免误删 pearl earrings 这类配饰）
            r"floating bubbles?", r"floating pearls?", r"bubbles? catching the light",
            r"(?:sparkling|glowing|floating|scattered) particles?",
            r"floating orbs?", r"glowing orbs?", r"soap bubbles?",
        ),
        # 背景禁止项同时进负面（cfg>1 的工作流生效）
        "negative": ("city, castle, buildings, architecture, urban, indoor, "
                     "swimming pool, floating bubbles, particles"),
    },
}


def theme_scene_rule(theme):
    t = (theme or "").lower()
    for name, rule in THEME_SCENE_RULES.items():
        if any(k in t for k in rule["keywords"]):
            return name, rule
    return None, None


# ---------------------------------------------------------------------------
# 四季常装（2026-10-11 用户规格；2026-10-14 用户要求：**扩大到全部四条线路**）
#   需求：主题里加"春夏秋冬四季的常装"（参考图为秋季常装：米色针织衫+酒红围巾+
#         格裙+黑丝袜+棕色短靴+贝雷帽+斜挎包，秋叶公园场景）。
#         选中该主题时，**按当天日期判断季节**，出对应季节的日常服装与场景。
#   判季：3-5 春 / 6-8 夏 / 9-11 秋 / 12-2 冬
# ---------------------------------------------------------------------------
SEASONAL_THEME_KEYWORDS = ("四季", "常装", "日常装", "季节装")
# ---------------------------------------------------------------------------
# 用户参考图配方（2026-10-17）：近景/特写景别（来源：用户手跑 animagine/nova 的原文）
#   适用：**复杂双眼角色**（异色瞳/渐变瞳/瞳纹/特殊瞳孔）→ 画面价值在脸，就要近景
#   非复杂双眼角色 → **跳过景别判定**（用户要求：不复杂就不锁景别）
# ---------------------------------------------------------------------------
# 2026-10-17 再调（用户：仍太紧、第二张像证件照）：
#   去掉 `centered`（证件照感来源）+ 去掉 `portrait/upper body`（太紧）
#   改为单一景别 `cowboy shot`（七分身，到膝盖上方）+ `three-quarter view`（三分侧，避免正面证件照）
SHORT_CROP_FRAMING = ("cowboy shot, three-quarter view, "
                      "shallow depth of field, blurred background")
COMPLEX_EYE_TAGS = ("heterochromia", "two-tone eyes", "gradient eyes", "ringed eyes",
                    "symbol-shaped pupils", "flower-shaped pupils", "heart-shaped pupils",
                    "colored eyelashes", "eye gradient", "multicolored eyes",
                    "uneven eyes", "heterochromia iridum")
COMPLEX_EYE_FRAMING_WORKFLOWS = ("animagine_xl", "nova_xl")   # 仅这两条 SDXL 线启用
SHORT_PROMPT_WORKFLOWS = ("animagine_xl", "nova_xl")   # 短提示词模式（用户参考图配方）
SHORT_PROMPT_ACTIVE = False     # 由 pipeline 在选定工作流后设置（免改函数签名）
# 中档参数（2026-10-17 用户："别限制这么死，放开一点"）—— 以后只调这几个数字
SHORT_PROMPT_FIELD_MAX = {"face_priority": 8, "outfit": 10, "eye_colors": 6,
                          "core_features": 8, "appearance": 8}
SHORT_PROMPT_LIGHTING_MAX = 3   # 光照最多几个短语
SHORT_PROMPT_SCENE_MAX = 2      # 允许几个场景锚点（0=完全不写场景）
SHORT_PROMPT_MAX_TAGS = 74      # 总标签上限（2026-10-18 上调：要装下质量尾巴+解剖词，否则被截断）
SHORT_PROMPT_OUTFIT_WEIGHT = 1.35   # 服装权重（对抗底模把角色拉回官方服装）

# 2026-10-19 用户：成图出现游戏 LOGO / 文字 / 整片泛黄 / 眼睛涂抹 → 全局负面兜底
# 2026-10-19 用户：**不能一起改**（怕影响其他模型）→ 改成**按线路**负面表
#   症状来源：LOGO/泛黄/涂抹眼/game logo 都出现在 SDXL 家族（animagine/nova）
#   Anima 两条线保持原样（不加任何额外负面）
LINE_EXTRA_NEGATIVES = {
    "animagine_xl": (
        "logo, game logo, title, english text, chinese text, watermark, signature, text, "
        "yellow tint, sepia, color cast, oversaturated yellow, golden color cast, orange filter, "
        "asymmetrical eyes, eye out of socket, mismatched eye shape, deformed eyes, "
        "stiff pose, mannequin pose, flat background, fake background"
    ),
    "nova_xl": (
        "logo, game logo, title, english text, chinese text, watermark, signature, text, "
        "yellow tint, sepia, color cast, oversaturated yellow, golden color cast, orange filter, "
        "asymmetrical eyes, eye out of socket, deformed eyes, "
        "sitting, sitting on bench, full body, legs visible"
    ),
}

OUTFIT_SWAP_THEME_KEYWORDS = ("四季", "常装", "日常装", "季节装", "和服", "汉服",
                              "制服", "水手服", "JK", "校服", "婚纱", "礼裙", "旗袍")
# 2026-10-17 用户定案：**照抄泳装的"剥离官方服装"机制**
#   → 换装主题时，从**角色特征字段**里删掉这些"官方服装"标签（头饰/发型/瞳色**保留**）
# 2026-10-19 用户：只该影响初音 → **按角色**剥离官方服装词（只对列出的角色生效）
#   初音：官方服装与四季换装冲突 → 只删她的服装件，保留耳机/麦克风/双马尾
# 2026-10-19 用户：芙宁娜眼睛画不好 → 手工禁用
CHAR_BAN_LIST = ()   # 2026-10-19 恢复眼部写法后解除芙宁娜禁用
CHAR_OUTFIT_STRIP = {
    "hatsune_miku": ("detached sleeves", "teal necktie", "necktie",
                     "teal hairband", "hairband", "square hair ornament"),
}
OUTFIT_STRIP_CLOTHING = ("long sleeves", "bridal gauntlets", "white gloves", "black gloves",
                         "gloves", "neck ribbon", "bowtie", "jewelry", "collared shirt",
                         "kneehighs", "thighhighs", "black skirt", "hair ribbon",
                         "puff sleeves", "frilled sleeves", "cape", "sash", "tassel")

# 2026-10-23 用户：只换背景、保留原装。
#   SCENE_ONLY_THEMES 命中时，outfit 强制为 CHAR_OFFICIAL_OUTFIT，不让 LLM 换装。
SCENE_ONLY_THEMES = ("秋景", "春景", "夏景", "冬景", "背景", "外景")
CHAR_OFFICIAL_OUTFIT = {
    "furina_(genshin_impact)": (
        "navy blue beret with gold crown-shaped ornament, blue and white coat, "
        "blue and white dress, white gloves, blue gemstone pendant, "
        "black tights, blue and white boots"),
    "raiden_shogun": (
        "purple kimono, haori, purple obi bow, gold trim, "
        "purple flower hair ornament, gold hairpin, purple tassel earring"),
}

# ---------------------------------------------------------------------------
# 角色瞳色锚定（2026-10-18 用户方案 A）
#   LLM 有时把异色瞳写成单色（"blue eyes"），导致眼睛出错 ✗
#   → 命中下表时**强制覆盖** eye_colors，并剔除单色眼标签
#   （可用 character_eyes.json 覆盖，无需改代码）
# ---------------------------------------------------------------------------
CHAR_EYE_ANCHORS = {
    "furina_(genshin_impact)": "heterochromia, left eye light blue, right eye dark blue, detailed eyes",
    "raiden_shogun": "purple eyes, detailed eyes",
    "hatsune_miku": "aqua eyes, teal eyes, detailed eyes",
    "hu_tao_(genshin_impact)": "red eyes, flower-shaped pupils, detailed eyes",
    "march_7th_(honkai:_star_rail)": "blue eyes, pink eyes, heterochromia, detailed eyes",
}


def char_eye_anchor(name_en, simple=None):
    """返回该角色的瞳色锚定文本（优先 character_eyes.json，其次内置表）

    simple=True  → 去掉 left/right eye 细节（animagine 用这套更稳）
    simple=False → 保留完整左右明文（**nova 必须用这套**，否则异色瞳画不出来）
    """
    import json as _json
    import os as _os
    if simple is None:
        simple = CHAR_EYE_SIMPLE
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "character_eyes.json")
    v = None
    if _os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = _json.load(f) or {}
            v = d.get(str(name_en))
        except Exception:
            v = None
    if not v:
        v = CHAR_EYE_ANCHORS.get(str(name_en))
    if v and simple:
        _parts = [x.strip() for x in str(v).split(",") if x.strip()]
        _kept = [x for x in _parts
                 if not x.lower().startswith(("left eye", "right eye"))]
        return ", ".join(_kept) or str(v)
    return v


# nova 眼部负面（2026-10-18：nova 眼睛画坏 → 明确压制同色/对称眼）
# 2026-10-19 用户："去掉眼睛相关的补强措施"
#   → 眼部锚定/眼部负面只对列出的线路生效
EYE_ENHANCE_WORKFLOWS = ()
# 2026-10-23 用户：回退，四季常装恢复强制换装
SEASONAL_OUTFIT_FORCE = True
NOVA_EYE_NEGATIVE = "same color eyes, symmetrical eyes, weird eyes, mismatched pupils"
NOVA_EYE_WEIGHT = 1.2


# 2026-10-18 修（用户：nova 画得像小女孩 / 眼睛仍不对）
#   ① 体型锚定：短模式砍掉 REF_DIGNITY(mature/elegant) 后，模型把成年角色画幼 ✗
#      → 对"成年角色"补一个年龄/体型锚点（未成年/小体型角色不补）
#   ② 眼睛：`left eye X / right eye Y` 这种左右写法模型常画坏 ✗
#      → 锚定值简化为 `heterochromia` + 眼型，左右色差交给 heterochromia 本身
CHAR_BODY_ANCHOR = "mature female, adult, tall, slender, long legs"
# 2026-10-21 用户：animagine 芙宁娜过于幼态 → 角色级成年锚点（只对命中角色）
#   只留 5 个词：上一版加了 defined jawline / adult facial proportions 后压缩把
#   "furina / white hair / heterochromia" 挤掉，人物直接变人 → 这里只给温和的年龄锚。
CHAR_BODY_ANCHOR_BY_CHAR = {
    "furina_(genshin_impact)": "mature female, adult, tall, slender, mature face",
    # 初音设定 16 岁，不套成年锚点（避免被抬成成女）；空串表示显式跳过
    "hatsune_miku": "",
}
# 2026-10-21 用户：animagine 防幼负面（温和加权；与 SDXL_BODY_NEGATIVE 一起追加）
SDXL_AGE_NEGATIVE = ("(childlike proportions:1.2), (oversized head:1.15), "
                     "(baby face:1.15), (round face:1.1), (youthful face:1.1), "
                     "(small facial features:1.1), (flat face:1.1)")
CHAR_BODY_ADULT_ONLY = True     # 只给成年角色补（小体型角色由体型 ban 处理）

# 2026-10-21 用户：animagine 后续角色体型必须按官方设定，不能一律"成女/tall"
#   LLM 输出 body_type → (正向锚点, 负面类型)；per-char 可覆盖（Furina / Miku）
ANIMAGINE_BODY_PROFILES = {
    "adult_mature": ("mature female, adult, tall, slender, mature face", "adult"),
    "adult_slim": ("adult woman, slender, mature face", "adult"),
    "adult_petite": ("petite adult woman, slender, young adult", "adult_petite"),
    "teen": ("teenager, young woman, slender", "teen"),
    "child": ("child, petite, small", "child"),
    "nonhuman": ("", "none"),
}
# per-char 负面类型（角色锚点已有单独配置时，也钉死负面档位）
CHAR_BODY_NEG_BY_CHAR = {
    "furina_(genshin_impact)": "adult",   # 已验证：完整防幼负面
    "hatsune_miku": "teen",               # 16 岁设定：不压 petite、不补成女
}
# 成年小体型：保留 petite/small/short（这是设定，不是幼态）
SDXL_BODY_NEGATIVE_PETITE = ("child, loli, chibi, childlike proportions, oversized head")
SDXL_AGE_NEGATIVE_PETITE = "(baby face:1.1), (childlike face:1.1)"
# 少女：压儿童，但不压 petite；不补成年锚点
SDXL_TEEN_NEGATIVE = ("child, loli, chibi, toddler, childlike proportions, oversized head")
# 儿童：反向压成女/成熟，避免被画老
SDXL_CHILD_NEGATIVE = ("mature female, adult, tall, curvy, wide hips, large breasts")


def animagine_body_profile(body_type="", name_en="", body_text=""):
    """返回 (正向体型锚点, 负面类型, 归一化 body_type)。

    2026-10-21：body_type 由 LLM 按官方设定输出；缺失时从 body 文本兜底。
    per-char 覆盖优先（Furina=已验证的 5 词成年锚，Miku=空=不补成年）。
    """
    bt = str(body_type or "").strip().lower()
    if bt not in ANIMAGINE_BODY_PROFILES:
        _b = str(body_text or "").lower()
        if any(k in _b for k in ("child", "loli", "toddler", "kodomo")):
            bt = "child"
        elif any(k in _b for k in ("teen", "teenager", "adolescent")):
            bt = "teen"
        elif any(k in _b for k in ("petite", "small body", "small frame",
                                   "short stature", "short height")):
            bt = "adult_petite"
        elif "mature" in _b or "tall" in _b:
            bt = "adult_mature"
        else:
            bt = "adult_slim"
    if str(name_en) in (CHAR_BODY_ANCHOR_BY_CHAR or {}):
        anchor = CHAR_BODY_ANCHOR_BY_CHAR[str(name_en)] or ""
    else:
        anchor = ANIMAGINE_BODY_PROFILES[bt][0]
    neg = (CHAR_BODY_NEG_BY_CHAR or {}).get(str(name_en)) or ANIMAGINE_BODY_PROFILES[bt][1]
    return anchor, neg, bt
CHAR_EYE_SIMPLE = True          # True=锚定值去掉 left/right eye 细节（更稳）

# 三分侧避免证件照；不再用 cowboy shot（太松）、也不用 close-up/portrait（太紧）
SDXL_CROP_FRAMING = ("(upper body:1.35), three-quarter view, "
                     "shallow depth of field, blurred background")
# 2026-10-18 用户："先把 nova 的构图缩紧"
#   nova 对 `upper body` 服从度差（实测会画成全身）→ 改**更紧一档** portrait，
#   即使模型放松一档，也只会落到 upper body（目标区间）✓
NOVA_CROP_FRAMING = ("(upper body:1.35), portrait, three-quarter view, "
                     "shallow depth of field, blurred background")
# 2026-10-23 用户："不要裁切，要一开始就是正确景别"
#   生成期强制景别：正向加权 + 反向压制全身/腿脚
SDXL_FRAMING_POSITIVE = ("(upper body:1.35), (portrait:1.2), three-quarter view, "
                         "face focus, head and shoulders")
SDXL_FRAMING_NEGATIVE = ("full body, full-length, wide shot, legs visible, feet visible, "
                         "standing legs, distant view, zoomed out, full body shot")
# 2026-10-18 用户："服装没变化，只多了一条围巾" —— 泳装能换是因为它有**强制剥离**机制。
#   → nova 在**换装主题**下恢复"剥离官方服装 + 服装加权"（其余保持手跑配方不变）
NOVA_OUTFIT_SWAP_STRIP = True
OUTFIT_SWAP_WEIGHT = 1.35
# 眼部负面已上移到"提示词干预"段（2026-10-21：全项目只保留一处定义）。
THEME_CTX = ""      # 由 pipeline 在出图前写入当前主题（供 comfy_runner 判断是否换装主题）
# 2026-10-18 最后一招（服装是绑在角色概念上的，只能"负面排除官方服装"）：
#   换装主题下把"官方服装/默认装束"写进负面 —— 泳装能成立正是靠与官方服装互斥
OUTFIT_SWAP_NEGATIVE = ("official costume, character's default outfit, signature outfit, "
                        "white gloves, gold trim coat, blue coat, frilled collar, "
                        "theatrical costume, uniform coat")
# 2026-10-18 用户选 B：**物理互斥**写法（泳装式思路的反向）——
#   用厚重外套把官方服装"盖住"，让模型不可能同时画出官方蓝礼服
# 2026-10-21：padded → wool（否则与 OUTFIT_DRIFT_NEGATIVE 的 "puffer/down" 自相矛盾）
OUTFIT_SWAP_COVER = ("oversized wool coat closed to the neck, "
                     "thick knit scarf wrapped around neck covering the chest, "
                     "long sleeves covering arms, fully clothed, layered winter outfit")
OUTFIT_SWAP_WEIGHT_HARD = 1.5    # 物理互斥写法用更高权重


def is_outfit_swap_theme(theme):
    t = str(theme or "")
    return any(k in t for k in OUTFIT_SWAP_THEME_KEYWORDS)
SEASONAL_WORKFLOWS = ("api", "anima_flow", "animagine_xl", "nova_xl")   # ★ 四条线全部启用
SEASONAL_OVERRIDE = None        # 实验用：临时强制季节（"春"/"夏"/"秋"/"冬"）；None=按日期判季

# 2026-10-19 用户：**四季配置四条线共用**，要按线路微调必须走这一层（默认空 = 无影响）
#   用法：{"animagine_xl": {"lighting": "...", "pose": "..."}}
# 2026-10-20 用户：所有主题都要真实背景 → 主题级场景细节词库（最终拼装前追加）
SCENE_DETAILS = {
    "四季": "layered foreground foliage, path with stone paving, distant buildings and lamp posts, bokeh depth of field, natural perspective",
    "常装": "city street with storefronts and railings, soft bokeh, natural perspective",
    "泳装": "shallow water reflecting sunlight, distant shoreline, sand with footprints, bright sky with clouds, bokeh",
    "浴衣": "festival stalls with paper lanterns in the background, night sky, warm lantern glow, shallow depth of field",
    "和服": "traditional garden with stone lantern and wooden fence, soft daylight, layered foliage, bokeh",
    "制服": "classroom or school corridor with windows and desks, natural light, shallow depth of field",
    "女仆": "cafe interior with warm lamps and wooden furniture, soft bokeh, natural perspective",
    "圣诞": "festive street with string lights, decorated trees, warm glow, bokeh",
    "婚纱": "church or garden venue with floral arch and soft light, bokeh, natural perspective",
    "旗袍": "old town street with hanging lanterns, wooden railings, soft daylight, bokeh",
    "礼服": "ballroom with chandeliers and soft reflections, warm light, bokeh",
    "运动": "outdoor court or track with fence and distant trees, bright daylight, natural perspective",
}
SEASONAL_OVERRIDE_BY_LINE = {
    # 只对 SDXL 两条线生效；四季共用配置(SEASONAL_OUTFIT)保持不变
    # 2026-10-21：pose 会进给 LLM 的 prompt_theme（最终姿势仍由上半身强制块覆盖）；
    #   lighting 已在强制块里按本线覆盖；scene 会替换 scene_background。
    "animagine_xl": {
        "scene": [
            "autumn park path with golden ginkgo and orange maple trees, fallen leaves on stone paving, distant benches and lamp posts, soft bokeh background",
            "tree-lined avenue in autumn, warm sunlight through yellow leaves, scattered maple leaves on the ground, shallow depth of field",
            "riverside promenade in autumn, orange and gold foliage, calm water reflection, fallen leaves drifting",
            "quiet garden corner in autumn, wooden bench and stone lantern, maple leaves floating, soft diffused light",
        ],
        "pose": [
            "standing with a slight turn, one hand touching hair",
            "walking along the path, mid-stride, scarf swaying",
            "leaning against a wooden bench, arms loosely crossed",
            "sitting on the bench edge, one leg crossed over the other, hands on lap",
            "reaching up to catch a falling leaf, looking upward",
        ],
        "lighting": "soft afternoon sunlight with gentle rim light, natural skin tone",
        # 2026-10-20 用户：围巾被画成"大红绳/红筒" → 改成自然垂挂 + 明确针织物
        "outfit": "cream cable-knit sweater, red knit scarf loosely draped on shoulders, "
                  "brown plaid pleated skirt, black tights, brown lace-up boots, beige beret, "
                  "tan leather shoulder bag",
    },
    "nova_xl": {
        "scene": [
            "autumn park with golden ginkgo trees, fallen leaves on the ground, soft bokeh background",
            "tree-lined street in autumn, warm sunlight through yellow leaves, shallow depth of field",
            "autumn garden with stone paving, scattered maple leaves, distant buildings",
        ],
        "pose": [
            "standing with a slight turn, one hand on hip",
            "walking forward, looking at viewer, scarf flowing",
            "sitting sideways on a bench, hands together on lap",
        ],
        "lighting": "soft afternoon sunlight, natural skin tone",
    },
}
SEASONAL_OUTFIT = {
    "春": {"outfit": "layered light cardigan over a long-sleeve blouse, pleated skirt, "
                     "ankle socks, loafers, small woven shoulder bag, delicate ribbon detail",
           "scene": "spring park with cherry blossoms, soft pink petals falling, "
                    "gentle sunlight, fresh green grass",
           "weighted": "(cherry blossom petals:1.2), (soft pink petals:1.15), (fresh green grass:1.1)",
           "pose": "sitting sideways on a park bench, knees together, both feet resting on "
                   "the ground, ankles slightly crossed, one hand touching hair, "
                   "three-quarter view",
           "negative": "autumn leaves, snow, bare trees, swimsuit, swimwear"},
    "夏": {"outfit": "short-sleeve cotton shirt, light pleated skirt, straw hat, "
                     "sandals, thin tote bag, rolled-up sleeves, fresh light fabric",
           "scene": "bright summer street, dappled shade under green trees, "
                    "clear blue sky, cicada ambience",
           "weighted": "(strong summer sunlight:1.15), (dappled leaf shadows:1.15), (clear blue sky:1.1)",
           "pose": "walking forward with a light step, three-quarter view, "
                   "one hand holding a cold drink, hair swaying in a breeze",
           "negative": "autumn leaves, snow, wool coat, swimsuit, swimwear"},
    "秋": {"outfit": "cream chunky cable-knit sweater with visible knit texture, dark red wool "
                     "scarf, plaid skirt, black tights, brown leather lace-up boots, beret, "
                     "leather shoulder bag",
           "scene": "autumn park with golden ginkgo and orange maple trees, fallen yellow leaves "
                    "on the path, wooden bench, warm golden afternoon light",
           "weighted": "(golden ginkgo trees:1.25), (orange red maple leaves:1.25), "
                       "(fallen yellow leaves on the ground:1.2), (warm golden afternoon light:1.15)",
           "pose": "sitting sideways on a wooden bench, knees together, both feet resting on "
                   "the ground, ankles slightly crossed, slight lean forward, "
                   "one hand holding a paper coffee cup, the other hand resting on the bench, "
                   "three-quarter view",
           "negative": "green leaves, cherry blossoms, spring, green grass, blue flowers, "
                       "hydrangea, blue hydrangea, morning glory, sunflower, lotus, "
                       "swimsuit, swimwear"},
    "冬": {"outfit": "layered wool coat over turtleneck sweater, knit scarf, thick black tights, "
                     "winter boots, earmuffs, gloves, textured wool fabric",
           "scene": "winter street with bare trees, soft falling snow, "
                    "cold pale blue sky, warm visible breath",
           "weighted": "(soft falling snow:1.25), (bare winter trees:1.15), (cold pale blue sky:1.1)",
           "pose": "standing with hands in coat pockets, slight three-quarter turn, "
                   "shoulders drawn together against the cold, visible breath",
           "negative": "green leaves, cherry blossoms, autumn leaves, swimsuit, swimwear"},
}

# 四季常装共用的"设计感/材质/构图"要求（治"服装平庸 + 构图呆板"）
SEASONAL_DESIGN_RULES = (
    "layered outfit, visible fabric texture, knit or wool material, scarf, bag, "
    "coordinate accessories, colour-coordinated palette, "
    # 2026-10-17 修：**删掉 "small mini top hat worn on the head"**
    #   实测（初音未来不戴礼帽也出现了该词）→ 这是我们模板强加的配饰 ✗
    #   它让不戴帽子的角色也被戴上礼帽/帽子，用户误判为"没换装/残留默认服装"
    "bag carried on the shoulder, "
    "accessories worn properly, both hands naturally occupied"
)
SEASONAL_POSE_NEGATIVE = ("plain outfit, flat colour, school uniform, standing straight, "
              "stiff pose, front view, symmetrical composition, "
              "blank expression, empty background, "
              "oversized hat, floating hat, hat held above the head, object merged with hand, "
              # 坐姿腿部崩坏专用负面（2026-10-12：实测"腿糊成一团/膝盖消失"）
              "fused legs, merged legs, missing knee, distorted knees, "
              "twisted legs, malformed ankles, bad leg proportions, "
              "extra legs, missing legs, conjoined legs")


# ---------------------------------------------------------------------------
# 提示词丰富度强制（2026-10-12）
#   实测：Anima 线的正向只有 944~1937 字符，而用户认可的基准图是 3198 字符；
#         质量差距主要来自**信息密度**（光影/景深/材质/构图细节）。
#   做法：对**与主题无关的中性字段**做确定性补厚 —— 缺关键词或长度不足就补上，
#         已经写足的字段不动（不覆盖 LLM 的产出，只补空缺）。
#   格式：(字段名, 缺失判定关键词, 最小长度, 补充内容)
# ---------------------------------------------------------------------------
PROMPT_RICHNESS = (
    # (字段, 已具体描述过的**具体**关键词, 补充内容, 字段长度上限)
    # 判定改用"具体词"：之前用 `light` 太泛，导致"写得长但写得虚"的字段被误判为已写足。
    ("lighting", ("rim light", "key light", "bounce light", "backlit"), 370,
     "lighting direction consistent with the scene, soft ambient bounce light, "
     "rim light from the main light source, contact shadows grounding the character"),
    ("depth", ("depth of field", "bokeh", "background blur"), 260,
     "shallow depth of field, crisp focus on the face and upper body, gentle graduated "
     "background blur, soft sparkling bokeh highlights"),
    ("body", (), 260,
     "natural body proportions consistent with the official character design, "
     "correct anatomy, soft skin shading, graceful posture"),
    ("expression", (), 200,
     "lively expressive eyes, gentle natural smile, subtle blush, relaxed brows"),
    ("outfit", ("fabric texture", "knit", "wool", "stitching", "trim"), 380,
     "visible fabric texture, layered clothing details, neat stitching and trim"),
    ("composition", ("rule-of-thirds", "rule of thirds", "negative space"), 320,
     "rule-of-thirds placement, balanced negative space, headroom preserved, steady eye-level angle"),
    ("appearance", ("detailed eyes", "detailed face", "long eyelashes", "gradient hair"), 420,
     "delicately rendered facial features, detailed eyes, soft skin shading, "
     "distinct hair strands with subtle highlights"),
)


# ---------------------------------------------------------------------------
# 强辨识锚点（2026-10-12）
#   实测雷电将军：mole_under_eye（眼下的痣）在 40 张二创里出现 24 次，
#   是"像不像本人"的关键锚点 —— 之前既没挖掘、也没强制写入 → 出图不像本人。
#   规则：挖掘结果里命中此清单的标签，**由代码强制补进正向 appearance**（不靠 LLM）。
# ---------------------------------------------------------------------------
IDENTITY_ANCHOR_TAGS = ("mole under eye", "mole", "scar", "freckles", "fang",
                        "eyepatch", "bandage", "heterochromia", "streaked hair",
                        "two-tone hair", "single horn", "halo")


# ---------------------------------------------------------------------------
# 主题"训练量门槛"（2026-10-12 用户规格）
#   问题：主题不随模型的训练量走 —— 实测雷电将军：kimono 2520 张(44%)、japanese_clothes 3492(61%)，
#         而 swimsuit 仅 70 张(1.2%)、cheongsam 0 张 → 低量主题必然画崩（不像本人/五官崩）。
#   规则：选定主题后查"角色×主题"共现图量，**同时**满足 两个门槛才放行：
#           ① 绝对量 ≥ THEME_GATE_MIN_POSTS
#           ② 占该角色总量比例 ≥ THEME_GATE_MIN_RATIO
#         不达标 → 回退到候选里量最大的主题（仍不达标则保留原主题，fail-open 不阻塞出图）。
# ---------------------------------------------------------------------------
THEME_GATE_MIN_POSTS = 150
THEME_GATE_MIN_RATIO = 0.03
# ⚠️ 2026-10-12 用户纠正：这个"按二创图量换主题"的闸门**方向是错的**——
#    实测雷电将军：泳装仅 70 张却画得好，和服 2520 张反而画崩；
#    根因是"二创图量 ≠ 底模训练覆盖"（swimsuit 是通用高频概念，kimono 结构复杂易崩）。
#    → 默认**只记录不换主题**（THEME_GATE_SWAP=False），绝不再屏蔽可用主题。
THEME_GATE_SWAP = False
THEME_TAG_MAP = {
    "泳装": "swimsuit", "泳衣": "swimsuit", "比基尼": "bikini",
    "和服": "kimono", "浴衣": "yukata", "女仆": "maid", "圣诞": "christmas",
    "婚纱": "wedding dress", "护士": "nurse", "制服": "school uniform",
    # 2026-10-18 用户："兔女郎全角色禁用" → 已从主题表移除（并有负面兜底，见下）
    "运动": "sportswear", "旗袍": "cheongsam",
    "礼服": "evening dress", "常装": "casual", "四季常装": "casual",
}
# 兔女郎全局禁用（主题已移除；再加负面兜底，即使提示词里出现也不会画）
BANNED_THEMES = ("兔女郎", "bunny girl")
BANNED_THEME_NEGATIVE = "bunny girl, bunny suit, playboy bunny, bunny ears, leotard"
THEME_CANDIDATES = ("japanese clothes", "kimono", "swimsuit", "school uniform",
                    "maid", "christmas", "wedding dress", "yukata", "casual")


# ---------------------------------------------------------------------------
# 自动质量闸门：出图后让视觉模型对照【真实二创挖到的官方特征】客观核对（2026-10-12）
#   与"美学分"不同，它直接回答你最在意的三件事：是否本人 / 表情是否合性格 / 构图如何。
#   结果按 (工作流 × 主题) 累积；同一组合**连续低分**则自动标记为降级组合（下次跳过）。
# ---------------------------------------------------------------------------
# ⚠️ 2026-10-12 用户反馈："四组完全不符合预期" —— 而该判据给了 4~5/5 且全部放行。
#    → 判据与用户标准**不一致**，在重新校准前**必须关闭**，否则会：
#      ① 放行用户认为不合格的图 ② 对真正差的主题不降权（比没有闸门更糟）。
#    关闭后行为 = 回到"美学分择优、无条件输出"（即接入前的状态）。
IDENTITY_JUDGE = False
IDENTITY_JUDGE_MIN_SCORE = 3        # 身份分 < 此值算不合格（1~5）→ **不输出** + 降权
IDENTITY_JUDGE_BAD_LIMIT = 2        # 同一 (模型×主题) 累计几次不合格 → 视为已降级
IDENTITY_JUDGE_WEIGHT_FLOOR = 0.15  # 权重低于此值的主题：该模型下**优先避开**
IDENTITY_JUDGE_MAX_CANDIDATES = 7    # 逐候选核对的上限（默认 7 张；每张约 1.5k token）
IDENTITY_JUDGE_BAD_OF = 3            # 本次生成中不达标 ≥ 此张数 → 本次算失败（不输出+降权）
IDENTITY_JUDGE_RERUNS = 2            # 失败后自动重跑的轮数上限（当天没发图 → 重跑）
IDENTITY_JUDGE_MAX_TOKENS = 2500

# 账本 key 到"**模型**"这一层（2026-10-12 用户纠正）：
#   决定"某主题能不能画好"的是**模型**，不是流水线配置；而 api 与 anima_flow 用的是**同一个**
#   Anima-2.9B —— 按工作流分会把同一模型的证据拆成两半、稀释掉。
#   （Anima 的 int8/原生 两个权重实测肉眼等价，故归并为同一模型）
MODEL_KEY = {
    "api": "Anima-2.9B",
    "anima_flow": "Anima-2.9B",
    "animagine_xl": "AnimagineXL4",
    "nova_xl": "NovaAnimeXL",
}


def model_key(workflow):
    return MODEL_KEY.get(workflow, workflow)


# ---------------------------------------------------------------------------
# 标杆模板（2026-10-12）—— 依据用户手跑好图 ComfyUI_00254/00255 的**原文提示词**拆解
#   关键差异（实测）：
#     · 标杆**完全平铺、无权重**（只有画师串带权重）→ 我们之前加的一堆 (xxx:1.15) 是错的
#     · 标杆含**解剖强调**：perfect anatomy / detailed hands / five fingers …（治手崩的正解）
#     · 标杆含**气质词**：dignified expression / elegant / mature / expressionless / piercing gaze
#       （"不笑≠呆板"就是靠这些词，而不是靠负面）
#     · 标杆画师串 3 条并带权重；质量前缀 10 词；负面约 688 字符
#   结构：质量前缀 → 1girl → 角色+作品 → 画师串 → 角色真特征(平铺) → 服装 →
#         解剖强调 → 气质词 → 姿势 → 场景三层 → 氛围/光影/景深/细节尾串
# ---------------------------------------------------------------------------
REF_TEMPLATE = True
REF_QUALITY = ("masterpiece, best quality, highres, absurdres, year 2026, newest, "
               "very aesthetic, extremely detailed, intricate details")
REF_ARTISTS = "@ciloranko, (@mika pikazo:0.7), (@wlop:0.5)"
REF_ANATOMY = ("perfect anatomy, correct anatomy, detailed hands, five fingers, "
               "realistic arm structure")
REF_DIGNITY = ("dignified expression, elegant, mature, expressionless, half-closed eyes, "
               "piercing gaze")
# 2026-10-21 用户：构图呆板/背景假/表情木讷 → Anima 后处理与负面
ANIMA_DYNAMIC_NEGATIVE = ("centered composition, symmetrical composition, steady eye-level, "
                          "front view, passport photo, stiff pose, mannequin pose, "
                          "static pose, flat background, fake background, pasted background, "
                          "no contact shadows, floating background")
# 2026-10-21 用户：芙宁娜"像贴上去" → 人物与场景的接缝/光照/投影/透视
ANIMA_INTEGRATION_NEGATIVE = ("pasted character, cutout, sticker, floating character, "
                              "mismatched lighting, inconsistent shadows, no cast shadow, "
                              "composited, green screen, disconnected from background, "
                              "wrong perspective scale")
REF_TAIL = ("cinematic composition, dynamic angle, soft lighting, lens flare, "
            "detailed background, depth of field, water droplets on skin, wet hair, "
            "sunlight through hair")
# 2026-10-17 修（用户：SDXL 两线"主要体现氛围和必要场景描述"）：
#   REF_TAIL 里的 cinematic composition / dynamic angle / lens flare / detailed background
#   是**固定模板词**（LLM 写的清不掉 ✗），它们等于在要"远景+环境" → 近景守不住
#   四季常装主题下改用精简版：只留光照质感与虚化，去掉环境/远景导向
# 2026-10-18 修（用户：短提示词后画面质量一直下降）
#   短模式丢了"质量助推词" → 精细度/皮肤质感下降 ✗
#   中短版：**保留**质量尾巴 + 解剖词（只砍抢构图/堆场景的词）
REF_TAIL_LITE = ("delicate skin, detailed skin, beautiful detailed eyes, "
                 "intricate details, sharp focus, best quality, "
                 "soft lighting, depth of field")
REF_ANATOMY_LITE = "perfect anatomy, correct anatomy, detailed hands, five fingers"
# 2026-10-18 修（用户：质量不如手跑参考图 / 脸发黄 / 体型还是小孩）
#   · 参考图的质量前缀只有 3 个词 → 我们那串 year 2026/newest/absurdres/extremely detailed
#     在 SDXL 上会出"塑料+锯齿感"✗ → SDXL 短模式改用精简质量前缀
REF_QUALITY_SDXL = "masterpiece, best quality, very aesthetic"
#   · 防黄：负面压制暖色偏 + 正面改中性光（原来 "warm/golden sunlight" 会把皮肤染黄 ✗）
SDXL_SKIN_NEGATIVE = ("yellow skin, orange skin tone, warm color cast, jaundice, "
                      "oversaturated skin, plastic skin")
SDXL_NEUTRAL_LIGHT = "soft natural lighting, natural skin tone"
SDXL_BODY_NEGATIVE = ("child, loli, chibi, petite, small body, short stature, "
                      "childlike proportions, oversized head")
REF_NEGATIVE_EXTRA = ("bad anatomy, bad proportions, extra fingers, missing fingers, "
                      "fused fingers, mutated hands, missing limbs, malformed limbs, "
                      "extra digits, fewer digits, watermark, signature, text, "
                      "jpeg artifacts, lowres, worst quality, low quality, blurry, "
                      "artist name, cropped head, cut off headwear, out of frame")


def build_reference_prompt(structured, name_en, series_en, theme=None, framing=None,
                           compact=False, extra_fields=()):
    """按标杆结构拼正向：平铺标签、无权重、含解剖强调与气质词（槽位替换式）

    framing：景别（2026-10-13 起**显式注入**，不再只靠 LLM 自觉 —— 模板早退会丢掉它）。
    compact：**短提示词模式**（2026-10-17，用户参考图配方）——
             只留 质量/主体/角色/景别/五官瞳色/服装/少量外观/光照，
             砍掉：外观挖掘18个、REF_ANATOMY、REF_DIGNITY、姿势、场景、皮肤/湿身词。
             目的：把标签压到 25~35 个，让景别词有真实话语权（SDXL 两线专用）
    """
    st = structured or {}
    # 2026-10-17：短提示词模式（由 pipeline 按工作流置位；Anima 两线恒为 False → 完全不受影响）
    compact = bool(compact or SHORT_PROMPT_ACTIVE)
    esc = (name_en or "").replace("_", " ").replace("(", r"\(").replace(")", r"\)")
    plain = (name_en or "").replace("_", " ")
    parts = [REF_QUALITY, "1girl, solo"]
    ch = ", ".join(x for x in (esc, plain, (series_en or "")) if x)
    if ch:
        parts.append(ch)
    # 景别词紧跟主体之后（compact 与非 compact 都前移 —— 2026-10-17 修 II）
    if framing:
        parts.insert(2, str(framing))
    if compact:
        # 2026-10-18 回滚：质量前缀**保持你手跑那串**（masterpiece…intricate details）
        # （你贴的 00050/00078/00079 元数据里就是这一串，删掉它反而变差 ✗）
        pass
        # 2026-10-17 用户："别限制这么死，放开一点" → 改为**中档**：
        #   每字段 6~10 个（原来 3~6 太狠），允许少量场景/光照，总量上限 60（可调）
        _order = ("face_priority", "expression_priority", "expression", "outfit",
                  "eye_colors", "core_features", "appearance")
        for k in _order:
            v = str(st.get(k) or "").strip()
            if not v:
                continue
            _ls = [x.strip() for x in v.split(",") if x.strip()]
            _txt = ", ".join(_ls[:SHORT_PROMPT_FIELD_MAX.get(k, 8)])
            # 2026-10-17 修（用户：衣服还是原装）：服装**加权**，对抗底模的原装拉力
            if k == "outfit" and _txt:
                _txt = f"wearing ({_txt}:{SHORT_PROMPT_OUTFIT_WEIGHT})"
            parts.append(_txt)
        lt = str(st.get("lighting") or "").strip()
        if lt:
            parts.append(", ".join([x.strip() for x in lt.split(",") if x.strip()]
                                   [:SHORT_PROMPT_LIGHTING_MAX]))
        # 允许 1 个场景锚点（避免画面太"棚拍"）
        sc = " ".join(str(st.get(k) or "") for k in ("scene_background", "scene_midground"))
        if sc.strip() and SHORT_PROMPT_SCENE_MAX > 0:
            _sc = [x.strip() for x in sc.split(",") if x.strip()][:SHORT_PROMPT_SCENE_MAX]
            if _sc:
                parts.append(", ".join(_sc))
        parts.append(REF_ANATOMY_LITE)      # 解剖质量词（短模式原本误删）
        parts.append(REF_TAIL_LITE)
        # 2026-10-17 修（用户：眼睛又出问题）：异色瞳与单色眼标签打架 →
        #   若 eye_colors 含 heterochromia，剔除其它"单色眼"标签（blue eyes / aqua eyes …）
        _joined = ", ".join(p for p in parts if p)
        if "heterochromia" in _joined.lower():
            _eye_re = re.compile(r"(?i)^(light |dark |pale |deep |bright )?"
                                 r"(red|blue|green|purple|violet|aqua|teal|yellow|orange|"
                                 r"pink|gold|amber|grey|gray|brown|heterochromia) eyes?$")
            _out = []
            for _x in _joined.split(","):
                _t2 = _x.strip()
                if not _t2:
                    continue
                if _eye_re.match(_t2) and "heterochromia" not in _t2.lower():
                    continue      # 单色眼 → 丢弃（保留 heterochromia / left|right eye …）
                _out.append(_t2)
            _joined = ", ".join(_out)
        # 去重（保持顺序）
        _seen, _uniq = set(), []
        for _x in _joined.split(","):
            _k = _x.strip().lower()
            if _k and _k not in _seen:
                _seen.add(_k)
                _uniq.append(_x.strip())
        return ", ".join(_uniq[:SHORT_PROMPT_MAX_TAGS])
    # ---- 常规（长模板）模式 ----
    # 画师串**不再由模板强制注入**（2026-10-12 用户纠正）：
    #   画师交回原有的"50% 触发"机制 —— 触发时由 comfy_runner 注入并 CFG 固定 3.7；
    #   不触发则**不注入**、CFG 3.5~5.0 随机。REF_ARTISTS 仅作"可选的画师串候选池"保留。
    try:
        from booru_client import appearance_tags
        feats = [t.replace("_", " ") for t in (appearance_tags(name_en, sample=40) or [])][:18]
        if feats:
            parts.append(", ".join(feats))
    except Exception:
        pass
    for k in ("face_priority", "appearance"):
        v = str(st.get(k) or "").strip()
        if v:
            parts.append(v)
    # 2026-10-21 用户：SDXL（animagine/nova）也必须读 body —— 之前长模板直接丢弃，
    #   再叠加 PROMPT_RICHNESS 的 "petite slender figure" → 成年角色被画幼。
    #   Anima 已通过 extra_fields 补 body，这里跳过避免重复。
    if "body" not in (extra_fields or ()):
        _bv = str(st.get("body") or "").strip()
        if _bv:
            parts.append(_bv)
    for k in ("outfit",):
        v = str(st.get(k) or "").strip()
        if v:
            parts.append(v)
    # 2026-10-21：长模板原本不读的字段（Anima 传 eye_colors/body/composition/depth 补回）
    for k in (extra_fields or ()):
        v = str(st.get(k) or "").strip()
        if not v:
            continue
        if k == "composition" and framing:
            # composition 里的景别词与已注入的 framing 打架 → 只留不冲突的（如 looking at viewer）
            _f0 = str(framing).split(",")[0].strip().lower()
            _keep = []
            for _x in v.split(","):
                _xl = _x.strip().lower()
                if (_xl in ("cowboy shot", "full body", "upper body",
                            "close-up", "portrait") and _xl != _f0):
                    continue
                if _xl:
                    _keep.append(_x.strip())
            v = ", ".join(_keep)
        if v:
            parts.append(v)
    parts.append(REF_ANATOMY)
    parts.append(str(st.get("expression") or "").strip() or REF_DIGNITY)
    parts.append(REF_DIGNITY if REF_DIGNITY.split(",")[0] not in parts[-1] else "")
    for k in ("pose", "scene_foreground", "scene_midground", "scene_background", "lighting"):
        v = str(st.get(k) or "").strip()
        if v:
            parts.append(v)
    # 2026-10-17：四季常装（SDXL 两线）用**精简尾巴**，去掉"环境/远景导向"的模板词
    parts.append(REF_TAIL_LITE if "四季" in str(theme or "") else REF_TAIL)
    # （景别词已在函数开头注入到第 3 位，这里不再重复追加）
    # ===== ①②③④ 主题冲突处理（2026-10-12，根因修复）=====
    # 根因：泳装主题 + 角色**默认服装配件**（护手/长袖/手套/颈饰…）同时出现 → 模型把两者缝起来
    #       → 怪袖/怪披挂 + 手臂体态崩 + 面部细节被挤占（实测雷神三张图全部如此）。
    _theme = str(theme or "")
    _is_swim = any(k in _theme for k in ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "度假"))
    _conflict = ("bridal gauntlets", "long sleeves", "gloves", "neck ribbon", "hair ribbon",
                 "jewelry", "bow", "kimono", "japanese clothes", "hakama", "obi",
                 "frilled sleeves", "boots", "thighhighs", "sleeves", "armor", "pauldron")
    _skin = "delicate skin, detailed skin, beautiful detailed eyes"
    _body = "bare shoulders, midriff, navel, collarbone"

    def _clean(text):
        # ④ 平铺：去掉**非画师**权重；**含 @ 的画师段原样保留**（含其权重，如 (@mika pikazo:0.7)）
        #   2026-10-12 修：原正则把画师权重也拍平了 → 主/辅画师变等权，风格配比被改变。
        _segs = []
        for _seg in str(text or "").split(","):
            _segs.append(_seg if "@" in _seg
                         else re.sub(r"\(([^()]*?):[\d.]+\)", r"\1", _seg))
        t = ",".join(_segs)
        if _is_swim:
            for _w in _conflict:                                     # ① 屏蔽默认服装类标签
                t = re.sub(r"(?i)(^|,\s*)" + re.escape(_w) + r"(?=\s*(,|$))", "", t)
        return re.sub(r",\s*,+", ",", t).strip(", ")

    parts = [p for p in (_clean(p) for p in parts) if p]
    parts.append(_skin)                                              # ③ 皮肤/五官质感
    if _is_swim:
        parts.append(_body)                                          # ② 泳装匹配的身体标签
    # ⑤ 姿势守卫已撤销（2026-10-13 用户判定：脚没有问题，不该改姿势）
    # 去重（2026-10-12）：实测出现 `raiden shogun, raiden shogun`、`expressionless` 重复
    # → 按小写精确去重，保留首次出现顺序
    seen, out = set(), []
    for t in ", ".join(p for p in parts if p).split(","):
        s = t.strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return ", ".join(out)


def current_season(today=None):
    """按当天日期判季节：3-5 春 / 6-8 夏 / 9-11 秋 / 12-2 冬"""
    import datetime as _dt
    m = ((today or _dt.date.today()).month)
    if m in (3, 4, 5):
        return "春"
    if m in (6, 7, 8):
        return "夏"
    if m in (9, 10, 11):
        return "秋"
    return "冬"


def seasonal_guide(theme, workflow=None, today=None):
    """
    四季常装主题 → (季节, {outfit, scene}, 展示用主题名)。
    非该主题、或工作流不在 Anima 两条线时返回 None（其他工作流完全不受影响）。
    """
    t = theme or ""
    if not any(k in t for k in SEASONAL_THEME_KEYWORDS):
        return None
    if workflow and workflow not in SEASONAL_WORKFLOWS:
        return None
    # SEASONAL_OVERRIDE（2026-10-14）：临时解除"按当天日期判季"的锁定，强制指定季节
    #   仅实验用；跑完必须复位为 None（否则全年都出同一个季节）
    s = SEASONAL_OVERRIDE if SEASONAL_OVERRIDE in SEASONAL_OUTFIT else current_season(today)
    return s, SEASONAL_OUTFIT[s], f"{t}·{s}"


# ---------------------------------------------------------------------------
# Anima-2.9B 出图质量对齐（2026-10-10，依据官方模型卡）
#
# 官方卡明确写了三条我们之前没遵守的：
#   ① 正向前缀："masterpiece, best quality, score_7, safe"
#      —— score_7 是 Anima 专属质量标签，比通用质量词有效得多
#   ② 负面："worst quality, low quality, score_1, score_2, score_3,
#            artist name, blurry, jpeg artifacts, chromatic aberration"
#   ③ 提示词权重需要比 SDXL 更高（官方示例 (chibi:2)）；标签用小写+空格
# ---------------------------------------------------------------------------
# 2026-10-21 测试用：强制景别档位（None=随机；"full"/"cowboy"/"half"）
ANIMA_FRAMING_TIER = None

# 2026-10-22 用户景别策略：
#   默认 cowboy shot + upper body 为主；full body 只给"全身本身就是卖点"的主题。
FRAMING_POLICY_DEFAULT = (("cowboy shot", 0.60), ("upper body", 0.40))
FRAMING_POLICY_FULL = (("full body", 1.0), ("cowboy shot", 1.0), ("upper body", 1.0))
FRAMING_FULL_THEME_KEYWORDS = (
    "泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "度假",
    "礼服", "婚纱", "舞会", "晚礼服", "旗袍", "长裙",
    "动作", "战斗", "动态", "运动", "跑", "跳", "武",
)


def framing_theme_is_full(theme):
    """该主题是否允许全身（泳装/礼服/动作等）。"""
    return any(k in str(theme or "") for k in FRAMING_FULL_THEME_KEYWORDS)


def choose_framing(theme, workflow=""):
    """按主题选择景别：默认不出全身；泳装/礼服/动作类才允许全身。"""
    if FRAMING_OVERRIDE:
        return FRAMING_OVERRIDE
    t = str(theme or "")
    full = any(k in t for k in FRAMING_FULL_THEME_KEYWORDS)
    pool = FRAMING_POLICY_FULL if full else FRAMING_POLICY_DEFAULT
    import random as _r
    return _r.choices([p[0] for p in pool], weights=[p[1] for p in pool], k=1)[0]

# 2026-10-21 身份锚定表：角色标志物（用于 Anima 提示词提前，治人物不像）
CHAR_SIGNATURE = {
    "hu tao": "black wide-brimmed hat, paper talisman on hat, plum blossom hair ornament, flower-shaped pupils, red eyes, twin tails",
    "furina": "gold crown mini top hat, heterochromia, white hair with blue streaks, droplet ornament",
    "hatsune miku": "aqua hair, very long twin tails, headset, aqua eyes",
    "raiden shogun": ("purple hair, long braid, hair ornament, purple eyes, "
                      "sharp eyebrows, narrow sharp eyes, mature female face, "
                      "mole under eye, straight bangs"),
    "march 7th": "pink hair, blue ribbon, flower hair ornament, heterochromia",
}
# 服装跑偏负面（治秋冬装变成羽绒服/毛领大衣）
# 2026-10-21：去掉 "overcoat"（与下面的羊毛大衣 cover 冲突），补 "fur trim"
OUTFIT_DRIFT_NEGATIVE = "puffer jacket, down jacket, fur collar, fur trim, duffle coat"
# 2026-10-21 用户：REF 长模板原来只读 face_priority/appearance/outfit/... →
#   eye_colors/body/composition/depth 全丢。两条 Anima 线把这几层补回正向。
#   注意：eye_colors 是 **LLM 自己写的瞳色**（不是强制锚定）；Anima 的眼部负面仍关闭。
ANIMA_EXTRA_TEMPLATE_FIELDS = ("eye_colors", "body", "composition", "depth")
# 2026-10-21 审计：补 `year 2025`（Anima 训练截止 2025-09）。
#   原来 pipeline 里的 "[Anima 年份]" 补丁在 structured 赋值前执行，是
#   UnboundLocalError（被 except 吞掉），且写进 quality 字段也不被模板读取 → 从未生效。
# 2026-10-21 用户：year 标签**放在最前**，不要放末尾。
ANIMA_PREFIX = "year 2025, masterpiece, best quality, score_7, safe"
ANIMA_NEGATIVE = ("worst quality, low quality, score_1, score_2, score_3, artist name, "
                  "blurry, jpeg artifacts, chromatic aberration")

# ---------------------------------------------------------------------------
# Anima 画师串（2026-10-10 第二版：按作品分类 + 通用兜底）
#
# 规则（按你的要求）：
#   ① 只作用于 Anima-2.9B 的两条工作流（api / anima_flow），其他工作流不动
#   ② **按作品分类**：优先用该作品的高频画师（数据来自 safebooru 每个作品 500 张
#      样本里画师标签的出现次数，见 scan_series_artists.py 可复现）
#   ③ 作品分类里找不到 → 用**通用画师组**兜底
#   ④ **在精不在多**（2026-10-21 用户）：每串默认**最多 2 位**（1 主 + 1 辅）；
#      唯一例外：用户标杆 3 人组 `@ciloranko + @mika pikazo + @wlop`（wlop 末位 0.5）；
#      每个作品默认 2 组；2026-10-21 按用户好图追加后
#      （genshin 3 组 / wuthering 3 组 / 通用池 3 组；hiki、dongho 已删）
#   ⑤ 同族搭配（画风 = 顺序 + 权重，混族会互相打架）
#   ⑥ 官方卡要求：小写 + 空格（下划线换成空格），权重按 Anima 习惯给
#   ⑦ wlop 只保留在标杆 3 人组末位、权重 0.5；不作主画师、不进入其它组合
#   ⑧ 辅画师权重运行时由 SECONDARY_ARTIST_WEIGHT_MAX（默认 0.65）截断；主画师保持 1.0
# ---------------------------------------------------------------------------
ANIMA_ARTIST_BY_SERIES = {
    "genshin_impact": [
        "@yaner, (@chinikuniku:0.8)",
        # 2026-10-12 标杆图（雷神泳装）验证过的组合；2026-10-21 "在精不在多"去掉末位 wlop
        "@ciloranko, (@mika pikazo:0.7)",
        # 2026-10-21 用户确认保留的标杆 3 人组（ComfyUI_00254 / weightfix_00008）：
        #   wlop 仅末位、权重 0.5；mika pikazo 运行时被 cap 到 0.65
        "@ciloranko, (@mika pikazo:0.7), (@wlop:0.5)",
    ],
    "honkai:_star_rail": [
        "@moonya, (@calendulamew:0.8)",
        "@celtreny, (@jiuchuansi:0.8)",
    ],
    "blue_archive": [
        "@hwansang, (@doremi (doremi4704):0.8)",
    ],
    "fate_(series)": [
        "@okonon (kado colda), (@miwa shirow:0.8)",
        "@neon-tetora, (@wagu neru:0.8)",
    ],
    "vocaloid": [
        "@makucrp, (@pinocchio-p:0.8)",
        "@zero (jckz2334), (@kaesmedubu:0.8)",
    ],
    "zenless_zone_zero": [
        "@hue oo, (@zeroartwo:0.8)",
        "@beni shake, (@sho yai:0.8)",
    ],
    "wuthering_waves": [
        "@sw haze, (@jvn:0.8)",
        "@dog-san, (@shigureszku:0.8)",
        # 2026-10-21 用户好图追加：Jinhsi 泳装（ComfyUI_00245/00235/00234）
        "@ciloranko, (@mika pikazo:0.7)",
    ],
    "hololive": [
        "@sui. (suikun), (@advarcher:0.8)",
        "@saltnvalk, (@nekojira:0.8)",
    ],
    "touhou": [
        "@uriah-oyu, (@mokoiscat:0.8)",
        "@ruu (tksymkw), (@moni monico:0.8)",
    ],
    "azur_lane": [
        "@samip, (@hori (hori no su):0.8)",
        "@soul (dp11), (@dedorudy:0.8)",
    ],
    "arknights": [
        "@gou haihaihaihai, (@fan mu zhang:0.8)",
        "@shirocha tei, (@norizc:0.8)",
    ],
    "idolmaster": [
        "@eluthel, (@nogreen:0.8)",
        "@mou (piooooon), (@binsen:0.8)",
    ],
    "umamusume": [
        "@art (rtrunl), (@moffumoto:0.8)",
        "@itaba atsushi, (@uwazumi:0.8)",
    ],
}

# 通用兜底组：跨作品总榜 + 你验证过的组合（2026-10-21 "在精不在多"：5 → 3；
# 2026-10-22 删除 dongho、hiki（跨作品脸崩/男相）→ 3 组）
ANIMA_ARTIST_GENERIC = [
    "@ciloranko, (@mika pikazo:0.7)",
    "@uriah-oyu, (@sw haze:0.8)",
    "@ciloranko, (@mika pikazo:0.7), (@wlop:0.5)",
]

# 画师组合以 data/artist_combos.json 为准；文件缺失或损坏时使用上面的同值兜底。
try:
    with open(os.path.join(DATA_DIR, "artist_combos.json"), "r", encoding="utf-8") as _f:
        _artist_data = json.load(_f) or {}
    if _artist_data.get("by_series"):
        ANIMA_ARTIST_BY_SERIES = _artist_data["by_series"]
    if _artist_data.get("generic"):
        ANIMA_ARTIST_GENERIC = _artist_data["generic"]
except Exception:
    pass


# 2026-10-21 用户：**辅画师权重别太高**。
#   主画师保持 1.0（不带权重）；第 2 位起的画师在**选串时**统一截断到这个上限。
#   表里写的 0.8 / 0.7 是统计原始值，运行时不会超过 cap；改这一个数即可全局生效。
SECONDARY_ARTIST_WEIGHT_MAX = 0.65

# 2026-10-22 用户：解除画师的作品限制 → 所有作品画师合并成一个全局池。
#   True=所有角色都从合并池随机；False=恢复按 ANIMA_ARTIST_BY_SERIES 查表。
ARTIST_GLOBAL_POOL = True


def _all_artist_combos():
    seen, out = set(), []
    for combos in ANIMA_ARTIST_BY_SERIES.values():
        for c in combos:
            if c not in seen:
                seen.add(c)
                out.append(c)
    for c in ANIMA_ARTIST_GENERIC:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


ANIMA_ARTIST_ALL = _all_artist_combos()


def _cap_secondary_artist_weights(combo, cap=None):
    """把一行画师串里第 2 位起的 (名字:权重) 截断到 cap；主画师（第 1 位）不动。"""
    cap = float(SECONDARY_ARTIST_WEIGHT_MAX if cap is None else cap)
    parts = [p.strip() for p in str(combo or "").split(",") if p.strip()]
    out = []
    for i, p in enumerate(parts):
        if i > 0:
            m = re.match(r"^\((.+):([\d.]+)\)$", p)
            if m:
                w = min(float(m.group(2)), cap)
                p = f"({m.group(1)}:{w:g})"
        out.append(p)
    return ", ".join(out)


def _alnum(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def anima_artist_combos(series):
    """
    2026-10-22：默认全局池（解除作品限制）→ 返回 ("global", 全部去重画师组合)。
    ARTIST_GLOBAL_POOL=False 时恢复按作品查表。
    """
    if ARTIST_GLOBAL_POOL:
        return "global", [_cap_secondary_artist_weights(c) for c in ANIMA_ARTIST_ALL]
    key = _alnum(series)
    if key:
        for tag, combos in ANIMA_ARTIST_BY_SERIES.items():
            if _alnum(tag) == key:
                return tag, [_cap_secondary_artist_weights(c) for c in combos]
    return None, [_cap_secondary_artist_weights(c) for c in ANIMA_ARTIST_GENERIC]


# ---------------------------------------------------------------------------
# 通用防错位 / 防糊块（2026-10-10 看图反馈的第二版）
#
# 反馈原话：「注意通用性，就是防止元素出现在不合理的地方」
# 所以这里不写死"遮阳伞不能在海里"这种单例，而是立**通用规则**：
#   · 物理错位：物体浮空、家具浮在水面、道具站在水面上、物体穿模进身体、漂浮杂物
#   · 服饰糊块：衣服与袖套/腿环/裤袜糊成一片、边界不清
# 任何场景（海滩/室内/雪地…）都适用。
#
# 作用域：SANE_PLACEMENT_WORKFLOWS。按你要求先只给 Anima-2.9B 两条；
# 想让全部工作流都生效，把四条名字都填进去即可。
# ---------------------------------------------------------------------------
SANE_PLACEMENT_NEGATIVE = (
    "objects floating in midair, furniture floating on water, "
    "objects standing on the water surface, props on the sea surface, "
    "levitating objects, floating debris, misplaced objects, "
    "objects clipping through the character, props intersecting the body, "
    "items embedded in the body, unnatural object placement"
)
CLOTHING_CLARITY_NEGATIVE = (
    "merged clothing, swimsuit fused with stockings, sleeves blended into swimsuit, "
    "unclear clothing boundaries, clothing merging into skin"
)
SANE_PLACEMENT_WORKFLOWS = ("api", "anima_flow")

# ---------------------------------------------------------------------------
# 工作流 → 模型档案（2026-10-10）
#
# 每条工作流对应哪个模型、什么家族、训练数据来源、知识截止，全部标注清楚；
# character_gate.py 用它判断"这个模型认不认识这个角色"。
#
# cutoff_year：该模型训练数据的大致截止年份（用于卡"新角色"）
# danbooru_based：是否是 danbooru/标签系（是 → 认识 danbooru 角色标签）
# ---------------------------------------------------------------------------
WORKFLOW_MODEL_INFO = {
    "api": {
        "label": "Anima-2.9B-preview-v1 (int8)",
        "family": "Anima / Cosmos-Predict2-2B 系（danbooru 标签训练）",
        "source": "danbooru + 非动漫艺术图（数百万张）",
        "cutoff": "2025-09",
        "cutoff_year": 2025,
        "cutoff_date": "2025-09",       # 官方卡原文：anime 训练数据 knowledge cutoff = September 2025
        "cutoff_precision": "month",
        "danbooru_based": True,
    },
    "anima_flow": {
        "label": "Anima-2.9B-preview-v1 (int8)",
        "family": "Anima / Cosmos-Predict2-2B 系（danbooru 标签训练）",
        "source": "danbooru + 非动漫艺术图（数百万张）",
        "cutoff": "2025-09",
        "cutoff_year": 2025,
        "cutoff_date": "2025-09",       # 官方卡原文：anime 训练数据 knowledge cutoff = September 2025
        "cutoff_precision": "month",
        "danbooru_based": True,
    },
    "animagine_xl": {
        "label": "Animagine XL 4.0 Opt (SDXL)",
        "family": "Animagine XL / SDXL（danbooru 标签训练，tag-ordering）",
        "source": "840 万张动漫图（官方卡）",
        "cutoff": "2025-01-07",       # 官方模型卡写明
        "cutoff_year": 2025,
        "cutoff_date": "2025-01-07",
        "cutoff_precision": "day",
        "danbooru_based": True,
    },
    "nova_xl": {
        "label": "Nova Anime XL ilV190 (Illustrious 系)",
        "family": "Illustrious-XL / SDXL（danbooru 标签训练）",
        "source": "danbooru 动漫图（Illustrious v1.9 血统）",
        "cutoff": "约 2024",          # 按 Illustrious v1.9 血统推断，无官方卡
        "cutoff_year": 2024,
        "cutoff_date": "2024",        # 只有年；没有官方月/日
        "cutoff_precision": "year",
        "danbooru_based": True,
    },
}

# 人物选择范围门控开关与阈值
CHARACTER_GATE_ENABLED = True
# 门控打回后最多重选几次（还不行就换工作流 / 舍弃此人物）
CHARACTER_GATE_ATTEMPTS = 3
# 换工作流上限（当场换一条认识该角色的继续，不浪费整轮）
MAX_WORKFLOW_SWAPS = 2

# ---- 人物范围判定：联网优先，本地兜底 ----
# 先联网查"角色出道年份 / 作品"，再退到本地 danbooru 标签表与作品年份表
CHARACTER_GATE_WEB = True                  # 联网查角色信息（失败自动退本地，不阻塞）
GATE_WEB_MAX_RESULTS = 6                   # 每次联网取几条结果
SERIES_MIN_POSTS = 500                     # 作品标签的 danbooru 投稿数下限（作品限制）

# A+C 眼睛方案（正向不加权、改写规范标签；负面排色保留）的作用域
# 用户 2026-10-11 要求：**先只给 animagine_xl**；其他工作流仍用原来的"逐眼加权"写法。
EYE_TAG_MODE_WORKFLOWS = ("animagine_xl", "nova_xl")

# ---------------------------------------------------------------------------
# 复杂瞳"眼部异常"视觉复核 —— **已停用（2026-10-11 用户决定）**
#   停用原因：判据未做准（实测漏判你指出的坏样本），且**没有标注样本**可校准
#             （历史失败样本已清理）。留着开着只是每条复杂瞳流水线白花 N 次视觉调用。
#   代码保留为休眠状态（EYE_VLM_CHECK=False 时**一次 API 都不会调用**，零开销），
#   等以后攒够 10~20 张好/坏标注样本，按"左右对比 + 逐眼裁图 + 一致性投票"改准后再启用。
#   复杂瞳角色（如芙宁娜）**仍按原来的加强双眼策略**：
#     eye_lock 的 A+C 分支（逐眼颜色标签化 + detailed eyes）+ 负面排色
#     + EYE_RENDER_WORKFLOWS 的提示词规则（颜色必须带 eyes、禁自然语言写瞳孔）
# ---------------------------------------------------------------------------
EYE_VLM_CHECK = False            # ← 已停用
EYE_VLM_PENALTY = 0.5
EYE_VLM_TIMEOUT = 90
EYE_VLM_MAX_EXTRA = 1

# ---------------------------------------------------------------------------
# 二段高清修复（hires fix）——2026-10-10 为对齐参考图完成度而加
#
# 参考图（1024x1536）的细节密度明显高于单段 896x1152 出图，所以给 SDXL 系工作流
# 加"潜空间放大 + 低去噪二次采样"：
#   第 1 段 896x1152 @28步 → LatentUpscale ×1.5 → 第 2 段 1344x1728 @14步 denoise0.45
# 代价：单张耗时约 +50%。关掉：HIRES_FIX = False（工作流会自动只走第一段）
# ---------------------------------------------------------------------------
HIRES_FIX = True
# 2026-10-11：按用户要求**去掉 animagine_xl 的放大流程**
#   → 作用域清空；工作流 JSON 里的 LatentUpscale + 二段 KSampler 节点也已删除，
#     现在是干净的 8 节点单段出图（896x1152，28步/cfg5/euler_a/CLIP skip-2）。
#   代码里的高清链支持仍保留：将来想给某条工作流加回来，把它的名字填进这个元组并
#   在对应工作流 JSON 里补上 hires_sampler / latent_upscale / vae_decode_hires 节点即可。
HIRES_WORKFLOWS = ()
HIRES_SCALE = 1.5
HIRES_DENOISE = 0.45
HIRES_STEPS = 14
HIRES_CFG = 5.0

# 画师标签（画师串）：2026-10-10 实测结论 —— **只对 Anima 系有效**
#   Anima：加了明显提升（按作品分类的 @画师串）
#   Animagine XL：加了反而更差（用户实测），已移除
#   Nova：与 Animagine 同族，同样不加
ARTIST_TAGS_WORKFLOWS = ("api", "anima_flow")
ARTIST_TAGS_AT_PREFIX = ("api", "anima_flow")   # 只有 Anima 系用 @ 前缀
# danbooru 投稿数下限：低于这个数，模型大概率没学过这个角色（会给通用脸）
# 2026-10-20 用户：老角色要**高人气**，新角色有人气即可（过滤模型不熟/样本不足）
CHAR_POP_OLD_YEAR = 2020      # 出道年 <= 此值算老角色
CHAR_POP_OLD_MIN  = 5000      # 老角色要求：danbooru 投稿 >= 5000
CHAR_POP_NEW_MIN  = 800       # 新角色要求：danbooru 投稿 >= 800
CHARACTER_MIN_POSTS = 200

# 作品出道年份（卡"模型知识截止之后才出的新角色"）——门控的**骨干数据**
# 联网只采信百科/WIKI 域名的摘要（实测本机引擎回的多是官网/论坛，年份不可信），
# 所以年份的可靠性主要靠这张表；遇到新作品往这里补一行即可。
SERIES_DEBUT_YEAR = {
    # ---- 经典/长篇 ----
    "gundam": 1979,
    "mario_(series)": 1985,
    "zelda": 1986,
    "final_fantasy": 1987,
    "street_fighter": 1987,
    "dragon_ball": 1984,
    "jojo_no_kimyou_na_bouken": 1987,
    "sailor_moon": 1991,
    "sonic_the_hedgehog": 1991,
    "tekken": 1994,
    "neon_genesis_evangelion": 1995,
    "touhou": 1996,
    "pokemon": 1996,
    "cardcaptor_sakura": 1996,
    "one_piece": 1997,
    "digimon": 1997,
    "naruto": 1999,
    "bleach": 2001,
    "toaru_majutsu_no_index": 2004,
    "fate_(series)": 2004,
    "pretty_cure": 2004,
    "idolmaster": 2005,
    "vocaloid": 2007,
    "league_of_legends": 2009,
    "sword_art_online": 2009,
    "love_live": 2010,
    "date_a_live": 2011,
    "puella_magi_madoka_magica": 2011,
    "infinite_stratos": 2011,
    "houkai_gakuen": 2012,
    "made_in_abyss": 2012,
    "kantai_collection": 2013,
    "kobayashi-san_chi_no_maid_dragon": 2013,
    "granblue_fantasy": 2014,
    "dungeon_meshi": 2014,
    "fate/grand_order": 2015,
    "bang_dream!": 2015,
    "ensemble_stars": 2015,
    "undertale": 2015,
    "re:zero": 2016,
    "kono_subarashii": 2016,
    "kimetsu_no_yaiba": 2016,
    "overwatch": 2016,
    "girls'_frontline": 2016,
    "umamusume": 2016,
    "honkai_impact_3rd": 2016,
    "rurouni_kenshin": 1994,
    # ---- 二游/近年 ----
    "azur_lane": 2017,
    "nier:automata": 2017,
    "hypnosis_mic": 2017,
    "hololive": 2018,
    "nijisanji": 2018,
    "chainsaw_man": 2018,
    "jujutsu_kaisen": 2018,
    "deltarune": 2018,
    "princess_connect": 2018,
    "arknights": 2019,
    "apex_legends": 2019,
    "spy_x_family": 2019,
    "bocchi_the_rock!": 2019,
    "d4dj": 2019,
    "genshin_impact": 2020,
    "project_sekai": 2020,
    "valorant": 2020,
    "oshi_no_ko": 2020,
    "blue_archive": 2021,
    "punishment:gray_raven": 2021,
    "tower_of_fantasy": 2021,
    "nikke": 2022,
    "elden_ring": 2022,
    "lycoris_recoil": 2022,
    "path_to_nowhere": 2022,
    "aether_gazer": 2022,
    "honkai:_star_rail": 2023,
    "reverse:1999": 2023,
    "snowbreak": 2023,
    "girls'_frontline_2": 2023,
    "girls_band_cry": 2023,
    "zenless_zone_zero": 2024,
    "wuthering_waves": 2024,
}


def series_debut_year(series_en):
    """按作品标签查出道年份（归一化后匹配，查不到返回 None）"""
    key = _alnum(series_en)
    if not key:
        return None
    for tag, year in SERIES_DEBUT_YEAR.items():
        if _alnum(tag) == key:
            return year
    return None


# ---------------------------------------------------------------------------
# 采样 seed 取值范围（2026-10-11 查证后保守缩减）
#
# 事实：
#   · ComfyUI 的 KSampler seed 节点定义为 64 位整数（上限 2^64-1）
#   · 但 A1111 / SDXL 生态惯例是 **32 位无符号**（0..4294967295）：
#     PNG 元数据、绝大多数前端与本机工具按 32 位解析
#   · 部分节点包/前端按 **有符号 32 位** 处理，超过 2^31-1 会被显示成负数或截断
#   · Cosmos(Anima) 与 Z-Image 虽为 ComfyUI 原生（可 64 位），但为兼容工具链同样保守处理
# 结论：统一收敛到**有符号 32 位正区间 1..2147483647**，每个工作流可单独覆盖。
#
# 注意：seed 只影响构图随机性，**不直接导致"莫名其妙的裁切"** ——
# 裁切是构图/景别的随机波动，靠 framing 与防裁切负面压制，不靠缩 seed 解决。
# ---------------------------------------------------------------------------
SEED_MAX_DEFAULT = 2147483647          # 2^31-1（有符号 32 位上限）
SEED_MAX = {
    "api": 2147483647,          # Anima-2.9B（Cosmos 系）：保守取有符号 32 位
    "anima_flow": 2147483647,   # Anima-2.9B（Flow）：同上
    "animagine_xl": 2147483647,  # SDXL 系：A1111 惯例 32 位，取其有符号上限
    "nova_xl": 2147483647,      # Illustrious/SDXL：同上
}


def set_active_unet(variant="int8"):
    """
    切换 Anima 权重：**唯一入口**（同时更新 ANIMA_UNET 与 WORKFLOW_SETTINGS，
    因此运行期调用立即生效，不再是导入期快照）。

    variant: "int8"（默认，2.87GB，快）/ "native"（原生 bf16，5.44GB）/ 也可直接传文件名。
    返回实际生效的文件名。
    """
    global ANIMA_UNET
    v = str(variant).lower()
    if v.endswith(".safetensors"):
        fname = variant
    elif v in ("native", "bf16", "fp16", "full"):
        fname = ANIMA_UNET_NATIVE
    else:
        fname = ANIMA_UNET_INT8
    ANIMA_UNET = fname
    for w in ("api", "anima_flow"):
        if w in WORKFLOW_SETTINGS:
            WORKFLOW_SETTINGS[w]["unet"] = fname
    return fname


# ---------------------------------------------------------------------------
# Anima-2.9B 画师标签 / CFG 联动（2026-10-11 用户规格）
#   选中 Anima 相关工作流（api / anima_flow）时，画师标签**不再固定注入**：
#     50% 触发画师串 → CFG **固定 3.7**
#     50% 不触发     → CFG **随机 3.5 ~ 5.0（含两端）**
#   理由：画师串是强风格注入，需要更低的 CFG 才不"过火"；不注入时给模型更大自由度。
# ---------------------------------------------------------------------------
ARTIST_TAG_PROB = 0.5                       # 触发画师串的概率
ARTIST_CFG_ON = 3.7                         # 触发时固定 CFG
ARTIST_CFG_OFF_RANGE = (3.5, 5.0)           # 未触发时 CFG 随机区间（含两端）


# 2026-10-13 用户规则：Anima 线按**角色出道年**分两档（不能用作品年，否则
# 同属《原神》的雷电将军 2021 与芙宁娜 2023 无法区分）
#   ≤ FORCE_ARTIST_MAX_YEAR（2022）→ 老角色，**强制**加画师（优先保证画面好看）
#   ≥ 2023                        → 新角色，走原 50% 随机方案
# 运行时由 pipeline_character 按选角结果写入 FORCE_ARTIST_OVERRIDE：
#   True = 强制加画师 ｜ None / False = 走 50% 随机
FORCE_ARTIST_MAX_YEAR = 2021      # 2026-10-14 用户收窄：**≤2021 才强制加画师**（原 2022）
FORCE_ARTIST_OVERRIDE = None
NO_ARTIST_MIN_YEAR = 2022         # 2026-10-14 用户要求：**≥2022 一律不加画师**（连 50% 随机也不摇）
NO_ARTIST_OVERRIDE = None         # 由 pipeline_character 按选角年份设置

# ---------------------------------------------------------------------------
# 萝莉/儿童体型人物黑名单（2026-10-14 用户要求：**ban 掉萝莉体型人物**）
#   判定方式：用 booru 高频标签（booru_client.appearance_tags）检查是否命中下表
# ---------------------------------------------------------------------------
# 方案 B（2026-10-14 用户改）：儿童/萝莉体型**不禁角色**，只禁"体型 × 暴露主题"组合
#   → 非暴露主题（冬日/和服/校园日常…）下小体型角色正常出图；
#     一旦主题属泳装/暴露类，则对"小体型角色"直接舍弃（换人换主题）
CHILD_BODY_BANNED_THEMES = ("泳装", "水着", "swimsuit", "bikini", "比基尼", "内衣",
                            "lingerie", "兔女郎", "bunny", "湿身", "沙滩", "泳池")


def is_revealing_theme(theme):
    t = str(theme or "").lower()
    return any(str(k).lower() in t for k in CHILD_BODY_BANNED_THEMES)
# 共现占比阈值：实测（safebooru 2026-10-14）
#   儿童体型：klee child 5.4% ｜ bailu 6.3% ｜ sigewinne 2.1% ｜ arima_kana 0.7%
#   正常角色：raiden 0.8% ｜ hu_tao 0.7% ｜ furina 0.3%
#   ⇒ 取 3% 可拦下 klee/bailu；**sigewinne(2.1%)/arima(0.7%) 会漏**（共现比区分度不足）
#   更可靠方案（待用户确认后实施）：用 booru `loli`/`child` 投稿的**角色标签频次**挖出
#   一份角色级黑名单 JSON（缓存），门控只查名单 —— 比比例判定准得多。
BANNED_BODY_TAGS = ("child", "loli", "toddler", "kodomo")   # 兜底判据用的体型标签
BANNED_BODY_RATIO = 0.03

# --- Nova 构图（2026-10-13 用户要求，**只改 Nova**）---------------------------
#   背景：nova_xl 原本"跳过景别"→ 不给任何构图词 → 模型默认跑到全身/远景（用户：不好看）
#   规则：从**紧凑构图池**随机抽（保多样性），全身/远景由负面压制
#   测试开关 FRAMING_OVERRIDE：实验时强制指定构图，用来隔离单个修饰词的影响
NOVA_FRAMING_POOL = ["upper body", "portrait", "close-up", "bust"]
NOVA_FRAMING_EXTRA = "centered, shallow depth of field"     # 固定修饰（可关：设为 ""）
# from below（仰视）：控制变量实测**平均最差**（2.675 vs B 2.756），但个别角色最佳
# （三月七 3.021）且三臂差距很小 → 按用户决定：**低频随机保留**，不全局固定
NOVA_FRAMING_FROM_BELOW_PROB = 0.2
NOVA_FRAMING_NEGATIVE = ("full body, full-length, wide shot, legs visible, feet visible, "
                         "standing legs, distant view, zoomed out, from above")
# 2026-10-13 用户指定：**Animagine 用他们手跑三张（00010/00011/00063）的构图**
#   实测三张提示词里的构图段完全一致 →
#   close-up, upper body, portrait, centered, shallow depth of field, blurred background
# 2026-10-14 修（用户反馈"头又丢了一部分"）：
#   ① `head fully in frame` 是**自然语言** → danbooru 系模型（Animagine）不认 ✗ 已删
#      （代码注释早有教训：头顶留白无法靠自然语言化解）
#   ② 裁切变紧的真因：我把 `upper body` 删了 —— **参考图的头顶留白正是靠它提供**
#   ⇒ 单一裁切词改为 **upper body**（保证头顶留白，仍是半身），并用负面压掉过紧裁切
# ============================================================================
# ★ 定稿（2026-10-14，用户确认）：Animagine 景别 = 下面这一版
#   实测三版对照（雷电将军 × 同 seed × 只改景别，output\_animagine_framing_ab / _tight）：
#     旧 portrait + head fully in frame   平均 4.213  ← 头被切 ✗
#     **upper body + 裁切负面（定稿）**    平均 4.048  ← 头顶完整 ✓ 用户确认
#     收紧版 upper body, portrait          平均 3.957  ← 更紧但用户选择回调 ✗
# ============================================================================
ANIMAGINE_FRAMING = ("(upper body:1.35), centered, shallow depth of field, blurred background")
# 过紧裁切负面（仅 Animagine 用；这些词会与正向的 upper body 形成"别裁太紧"的对抗）
ANIMAGINE_FRAMING_NEGATIVE = ("close-up, extreme close-up, head out of frame, "
                              "top of head cut off, cut off headwear, cropped head, "
                              "full body, full-length, wide shot, legs visible, feet visible, "
                              "distant view, zoomed out")
# 池子随机只给 Nova；Animagine 用上面的固定构图
FRAMING_POOL_WORKFLOWS = ("nova_xl",)
# 构图负面两条 SDXL 线都加（压制全身/远景）
FRAMING_NEGATIVE_WORKFLOWS = ("nova_xl", "animagine_xl")

# ---------------------------------------------------------------------------
# 四肢质检门（2026-10-13 方案①+②）——"筛掉一张就补一张，保持 5 选 1"
#   背景：B/C/C+ 共 13 次"事后修"全部无效（0 改善）⇒ 手脚崩坏只能**事前筛**
#   A 步已验证：VLM 四肢质检在已知问题图上 4/4 判准
#   注意：单次 VLM 判定有 ±1 档漂移 → 每张判 LIMB_JUDGE_VOTES 次取多数
# ---------------------------------------------------------------------------
LIMB_JUDGE = False             # 2026-10-14 用户要求：**关闭四肢检测**
                               #   （实测三项全合格率仅 13%：腿 53%/臂 67% 不合格 →
                               #    凑够 7 张合格期望需 ~54 次生成，代价不可接受）
                               #   模块与接入点保留，改回 True 即可恢复
LIMB_JUDGE_TARGET = 5          # 最终要凑够的**合格**候选数（2026-10-21：= 5 选 1）
LIMB_JUDGE_VOTES = 2           # 每张判定次数（取多数），消除大部分漂移
LIMB_JUDGE_MAX_TOTAL = 10      # 生成总数上限（防无限补图）：10 = 最多补 5 张
LIMB_JUDGE_MAX_TOKENS = 4500   # 该端点先花 reasoning 预算，给小了 content 会空
# 2026-10-13 用户要求：**只有 Anima-2.9B 两条线接入**四肢质检门
#   （SDXL 两线已有紧构图规避手脚，保持原样不动）
LIMB_JUDGE_WORKFLOWS = ("api", "anima_flow")

# ② 姿势规避负面 —— **已全部撤除**（2026-10-14 用户要求，基于实测）
#   实测（同角色同 5 seed、每姿势 5 张、VLM 四肢质检）：
#     基线·正常站姿  全合格 0%｜臂 100% 崩｜平均严重度 4.0   ← 最差
#     坐在地上       腿 100% 崩
#     跪姿 20%｜蹲姿 20%｜双手持物 20%（均优于基线）
#   ⇒ 这些负面**不防崩**，只是无谓限制姿势多样性 → 全撤
LIMB_POSE_NEGATIVE = ""        # 留空 = 不注入任何姿势规避词（机制保留，填回即恢复）
LIMB_POSE_WORKFLOWS = ("api", "anima_flow")

FRAMING_OVERRIDE = None


# --- 角色级出道年缓存（2026-10-13 方案 A）-----------------------------------
#   来源：选角时由 LLM 联网确认后写入；门控与画师分档都以它为准。
#   查不到 → 门控打回换人（不再用"作品级年份"糊弄，因为同作品新老角色无法区分）。
def _char_debut_year_path():
    return os.path.join(DATA_DIR, "character_debut_years.json")


def char_debut_year(name_en):
    """本地角色出道年（查不到返回 None）"""
    import json
    try:
        with open(_char_debut_year_path(), "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        return (d.get((name_en or "").strip()) or {}).get("year") or None
    except Exception:
        return None


def _norm_debut_date(value):
    """把 2025-09-15 / 2025-09 / 2025 / 2025年9月15日 归一成 YYYY[-MM[-DD]]；非法返回 None"""
    import re
    s = str(value or "").strip()
    m = re.match(r"^(\d{4})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?$", s)
    if not m:
        m = re.match(r"^(\d{4})年(?:(\d{1,2})月)?(?:(\d{1,2})日)?$", s)
    if not m:
        return None
    try:
        y = int(m.group(1))
        mo = int(m.group(2)) if m.group(2) else None
        day = int(m.group(3)) if m.group(3) else None
    except Exception:
        return None
    if not (1970 <= y <= 2070):
        return None
    if mo is not None and not (1 <= mo <= 12):
        mo = None
    if day is not None and not (1 <= day <= 31):
        day = None
    if mo is None:
        return f"{y:04d}"
    if day is None:
        return f"{y:04d}-{mo:02d}"
    return f"{y:04d}-{mo:02d}-{day:02d}"


def char_debut_date(name_en):
    """本地角色出道日期（YYYY[-MM[-DD]]）；老条目只有 year 时回退成 'YYYY'"""
    import json
    try:
        with open(_char_debut_year_path(), "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        rec = d.get((name_en or "").strip()) or {}
        if rec.get("date"):
            return _norm_debut_date(rec.get("date")) or str(rec.get("date"))
        y = rec.get("year")
        return str(y) if y else None
    except Exception:
        return None


def set_char_debut_year(name_en, year, source="llm", date=None):
    """写入角色出道年/日期缓存；year 非法则忽略。date 可选（YYYY[-MM[-DD]]）。"""
    import json
    key = (name_en or "").strip()
    if not key:
        return None
    if year is None and date:
        _d = _norm_debut_date(date)
        if _d:
            year = int(_d[:4])
    try:
        year = int(year)
    except Exception:
        return None
    if not (1970 <= year <= 2026):
        return None
    p = _char_debut_year_path()
    import os
    d = {}
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f) or {}
    except Exception:
        # 读不到旧文件（存在但损坏/被占用）→ **放弃写入**，绝不整体覆盖把别人的条目冲掉
        return None
    rec = {"year": year, "source": source}
    _d = _norm_debut_date(date) if date else None
    if _d:
        rec["date"] = _d
    d[key] = rec
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        with open(p, "r", encoding="utf-8") as f:          # 写回校验
            if not (json.load(f) or {}).get(key):
                return None
    except Exception:
        return None
    return year


def artist_roll():
    """返回 (是否触发画师串, 本次 CFG)

    2026-10-14 用户规则：**只把"强制加画师"的年份线从 2022 缩到 2021**，其余逻辑保持原样。
      · 角色出道年 ≤ FORCE_ARTIST_MAX_YEAR(2021) → 强制加画师 + CFG 固定 3.7
      · 其它（≥2022 / 年份未知）→ **保持原有的 50% 随机**（ARTIST_TAG_PROB），未被改动
    ★ 我先前擅自把 ≥2022 与"未知年份"改成"一律不加画师"，属越权修改，已还原。
    """
    import random as _r
    if FORCE_ARTIST_OVERRIDE is True:
        return True, ARTIST_CFG_ON
    if _r.random() < ARTIST_TAG_PROB:
        return True, ARTIST_CFG_ON
    lo, hi = ARTIST_CFG_OFF_RANGE
    return False, round(_r.uniform(lo, hi), 2)


# ---------------------------------------------------------------------------
# Anima-2.9B 权重二选一（2026-10-11 用户规格）
#   在**画师判定之后**再随机决定本次用哪个权重：
#     "int8"   → Anima-2.9B-preview-v1_int8_convrot.safetensors（2.87GB，快 ~1.5×）
#     "native" → Anima-2.9B-preview-v1.safetensors（5.44GB，原生 bf16）
#   实测（4 组同 seed，anima_flow）两者肉眼等价 → 随机二选一不影响质量，
#   只是让两条权重都被真实用到（也顺带持续验证两者一致性）。
# ---------------------------------------------------------------------------
ANIMA_MODEL_CHOICES = ("int8", "native")


def anima_model_roll():
    import random as _r
    return _r.choice(ANIMA_MODEL_CHOICES)


def seed_max_for(workflow):
    """该工作流的 seed 上限"""
    return SEED_MAX.get(workflow, SEED_MAX_DEFAULT)


# 已废弃的单例写法（保留名字以免旧代码引用报错，内容为空）
ANIMA_EXTRA_POSITIVE = ""      # 正向补充开关（默认关闭）



# ---------------------------------------------------------------------------
# workflow_api.json 的 KSampler 随机组合：(sampler, scheduler, 步数, CFG, 来源)
#   每套带自己的推荐步数/CFG —— 组合取自你自己的 A/B 工作流
#   （ComfyUI\user\default\workflows 下同名文件）与 ComfyUI 官方 Anima 模板。
# ---------------------------------------------------------------------------
KSAMPLER_COMBOS = [
    ("euler", "sgm_uniform", 30, 5.0,
     "你的 A/B：Euler + sgm-uniform"),
    ("er_sde", "beta57", 30, 5.0,
     "你的 A/B：er_sde + beta57"),
    ("res_multistep", "linear_quadratic", 30, 5.0,
     "你的 A/B：Res Multistep + linear-quadratic"),
    ("uni_pc", "ddim_uniform", 35, 5.0,
     "你的 A/B：uni_pc + ddim_uniform（原 55 步，实测 35 步足够）"),
    ("euler", "simple", 30, 4.0,
     "ComfyUI 官方模板 Anima Base v1"),
    ("er_sde", "simple", 30, 4.0,
     "ComfyUI 官方模板 Anima Preview"),
    # 2026-10-12 新增：**精确对齐用户手跑标杆**（ComfyUI_00254/00255 实测参数：
    # euler + sgm_uniform / 50 步 / cfg 3.7 / 1024x1536 / Anima-2.9B / 无画师串）
    ("euler", "sgm_uniform", 50, 3.7,
     "对齐用户手跑标杆：Euler + sgm-uniform / 50步 / cfg3.7"),
]

# 2026-10-20 用户：**保留采样组合多样性，但淘汰低质量档**；api 的 CFG 统一 3.7
#   保留（全部在官方推荐范围内，步数 40~50，CFG 3.7）：
#     euler + sgm_uniform      （作者个人最爱）
#     res_multistep + linear_quadratic（官方：构图最佳）
#     er_sde + beta57          （官方采样器/调度器）
#     uni_pc + ddim_uniform    （多样性补充）
#   淘汰：euler+simple / er_sde+simple（30 步快档，质量明显低）
QUALITY_FIRST_MODE = True
KSAMPLER_COMBOS = [
    ("euler", "sgm_uniform", 50, 3.7, "作者最爱：euler + sgm-uniform / 50步 / cfg3.7"),
    ("res_multistep", "linear_quadratic", 50, 3.7, "官方：构图最佳 / 50步 / cfg3.7"),
    ("er_sde", "beta57", 50, 3.7, "官方采样器：er_sde + beta57 / 50步 / cfg3.7"),
    ("uni_pc", "ddim_uniform", 50, 3.7, "多样补充：uni_pc + ddim_uniform / 50步 / cfg3.7"),
]

# ---------------------------------------------------------------------------
# anima_flow 工作流的采样器参数（官方默认档）
#   原配置 pc3_damped + rf_linear_shift + shift3 + cfg3.7 + 50步 实测 355.8s/张；
#   换成官方默认 flow_euler + diffusers_linear_shift + shift3 + cfg5 + 30步 → 116.3s/张，
#   画质肉眼相当（见 output\_bench\second 对照图）。
# ---------------------------------------------------------------------------
ANIMA_FLOW_SETTINGS = {
    "cfg_mode": "const",
    "flow_solver": "flow_euler",
    "flow_schedule": "flow_diffusers_linear_shift",
    "flow_shift": 3.0,
}

# ---------------------------------------------------------------------------
# ComfyUI 自动拉起（ensure_comfyui.py 用）
#   注意：不要加 --lowvram —— 它会把文本编码器甩到 CPU，
#   实测单张从 115s 退化到 372s（慢 3 倍）。
# ---------------------------------------------------------------------------
COMFY_DIR = os.environ.get("COMFY_DIR", "")
COMFY_PYTHON = os.environ.get("COMFY_PYTHON", "")
COMFY_START_ARGS = ["main.py", "--bf16-text-enc", "--listen", "127.0.0.1", "--port", "8188"]
COMFY_BOOT_TIMEOUT = 300      # 等待启动就绪的最长秒数
COMFY_AUTOSTART = bool(COMFY_DIR and COMFY_PYTHON)   # 未配置路径时不自动拉起

FALLBACK_NEGATIVE = (
    "worst quality, low quality, lowres, score_1, score_2, score_3, blurry, jpeg artifacts, bad anatomy, missing fingers, watermark, artist name"
)

# DanbooruSearch
DANBOORU_RELATED_URL = "https://sakizuki-danboorusearch.hf.space/api/related"
DANBOORU_TIMEOUT = 20