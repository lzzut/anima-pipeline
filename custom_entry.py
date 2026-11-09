"""Implementation details: see docs/ARCHITECTURE.md."""

import json
import os
import random
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import config as cfg
import comfy_runner as cr
import prompt_utils as am
from ensure_comfyui import ensure_comfyui

BASE = os.path.dirname(os.path.abspath(__file__))
ALL_MODELS = [
    ("api", "Anima-2.9B api", "KSampler：可选 4 组采样器组合"),
    ("anima_flow", "Anima-2.9B anima-flow", "AnimaFlowCorrectiveSampler 工作流"),
]
SYSTEM_MODELS = [
    m for m in ALL_MODELS if m[0] in tuple(getattr(cfg, "WORKFLOW_POOL", ("api", "anima_flow")))
]
THEME_MENU = list(cfg.LOCAL_THEMES)
ROUTES = [
    ("mixed", "随机（与自动本地出图一致：约 1/3 固定背景，2/3 DeepSeek 设计）"),
    ("deepseek", "DeepSeek 自己设计地点"),
    ("fixed", "固定背景清单里随机取一个"),
]
VARIANTS = [("random", "随机"), ("native", "原生 bf16"), ("int8", "int8 量化")]
ARTIST_NOTES = {
    "@yaner": "柔和厚涂、动画脸，适合芙宁娜/初音",
    "@ciloranko": "干净线稿、时尚构图，适合现代装",
    "@moonya": "柔和光影、赛璐璐，五官稳定",
    "@celtreny": "精细发丝、冷色调，适合长发角色",
    "@hwansang": "半厚涂、成熟脸，适合成年体型",
    "@okonon": "复古赛璐璐、老动画质感",
    "@neon-tetora": "荧光高对比、赛博感",
    "@makucrp": "锐利线稿、动态姿势",
    "@zero": "冷色平面、设计感强",
    "@hue oo": "明亮配色、可爱向",
    "@beni shake": "和风厚涂、红黑对比",
    "@sw haze": "淡色空气感、轻小说插画",
    "@dog-san": "圆润萌系、软线",
    "@sui.": "水彩透明感",
    "@saltnvalk": "赛博锐利、高饱和",
    "@uriah-oyu": "冷艳高对比（两套组合）",
    "@ruu": "东方清透、巫女系",
    "@samip": "粉彩软萌",
    "@soul": "暗色厚涂",
    "@gou haihaihaihai": "中国风、细线描",
    "@shirocha tei": "白毛冷色、清冷",
    "@eluthel": "奇幻柔光",
    "@mou": "轻小说可爱风",
    "@art": "厚涂写实",
    "@itaba atsushi": "复古硬朗",
}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def list_models():
    print("\n可选模型：")
    for i, (key, name, desc) in enumerate(SYSTEM_MODELS, 1):
        info = cfg.WORKFLOW_MODEL_INFO.get(key, {})
        print(f"  {i}. {name}  | 截止 {info.get('cutoff', '?')}  | {desc}")
    print("  9. 修改 ComfyUI 路径")
    print("  q. 退出")


def list_samplers():
    print("\n采样器组合（仅 api；anima-flow 用固定的 Flow 参数）：")
    for i, c in enumerate(cfg.KSAMPLER_COMBOS, 1):
        print(f"  {i}. {c[4]}  [{c[0]} + {c[1]} / {c[2]}步 / cfg{c[3]}]")


def list_artists():
    combos = list(dict.fromkeys(cfg.anima_artist_combos("__global__")[1]))
    print("\n画风组合：")
    for i, c in enumerate(combos, 1):
        primary = c.split(",")[0].strip()
        note = ARTIST_NOTES.get(primary, "综合风格")
        print(f"  {i:2d}. {c}   — {note}")
    return combos


def list_themes():
    print("\n主题：")
    for i, t in enumerate(THEME_MENU, 1):
        print(f"  {i:2d}. {t}")


def _pick(options, prompt, default=1):
    raw = input(prompt).strip() or str(default)
    try:
        n = int(raw)
        if 1 <= n <= len(options):
            return options[n - 1]
    except ValueError:
        pass
    print(f"编号无效，用 {default}")
    return options[default - 1]


def choose_model():
    list_models()
    raw = input("\n选择模型编号：").strip().lower()
    if raw == "q":
        return (None, None)
    if raw == "9":
        change_comfyui_path()
        return choose_model()
    try:
        n = int(raw)
    except ValueError:
        print("编号无效")
        return choose_model()
    if 1 <= n <= len(SYSTEM_MODELS):
        return (SYSTEM_MODELS[n - 1][0], SYSTEM_MODELS[n - 1][1])
    print("编号无效")
    return choose_model()


def choose_variant():
    print("\n权重：")
    for i, (_, label) in enumerate(VARIANTS, 1):
        print(f"  {i}. {label}")
    return _pick(VARIANTS, "选择权重编号（默认 1 随机）：")[0]


def choose_sampler(workflow):
    if workflow != "api":
        return None
    list_samplers()
    raw = input("\n选择采样器组合编号（0=随机，与自动本地出图一致；默认 0）：").strip() or "0"
    if raw == "0":
        return None
    try:
        if not 1 <= int(raw) <= len(cfg.KSAMPLER_COMBOS):
            raise ValueError
        return cfg.KSAMPLER_COMBOS[int(raw) - 1]
    except Exception:
        print("编号无效，用随机")
        return None


def choose_artist(workflow):
    combos = list_artists()
    raw = (
        input("\n选择画风组合编号（r=随机，与自动本地出图一致；0=不加画风；默认 r）：")
        .strip()
        .lower()
        or "r"
    )
    if raw == "r":
        return "random"
    if raw == "0":
        return None
    try:
        if not 1 <= int(raw) <= len(combos):
            raise ValueError
        return combos[int(raw) - 1]
    except Exception:
        print("编号无效，用随机")
        return "random"


def ask_character():
    print("\n自定义人物（英文标签建议直接写 danbooru tag）")
    name_cn = input("人物中文名：").strip()
    series_cn = input("作品中文名：").strip()
    name_en = input("人物英文标签（如 furina_(genshin_impact)）：").strip()
    series = input("作品英文标签（如 genshin_impact）：").strip()
    version = input("外观版本（默认 default appearance）：").strip() or "default appearance"
    return {
        "name_cn": name_cn or name_en,
        "series_cn": series_cn or series,
        "name_en": name_en,
        "series": series,
        "version": version,
    }


def choose_theme():
    list_themes()
    return _pick(THEME_MENU, "选择主题编号（默认 13 四季常装）：", default=13)


def choose_route():
    print("\n背景线路：")
    for i, (_, label) in enumerate(ROUTES, 1):
        print(f"  {i}. {label}")
    return _pick(ROUTES, "选择背景线路编号（默认 1）：")[0]


def choose_count():
    raw = (
        input("\n出图张数（5=同一提示词换 5 个 seed 后美学选 1；1=单张；默认 5）：").strip() or "5"
    )
    count = 1 if raw == "1" else 5
    raw_seed = input("起始 seed（留空随机；5 张时依次 +1）：").strip()
    if not raw_seed:
        return count, None
    try:
        seed = int(raw_seed)
        if not 0 <= seed <= cfg.seed_max_for("api") - count + 1:
            raise ValueError
    except ValueError:
        raise ValueError("seed 及连续候选必须落在 0..2147483647。")
    return count, [seed + k for k in range(count)]


def build_v2(char, workflow, route, *, audit_dir=None, prompt_session=None):
    """Use the same approved evidence session and writing chain as automatic generation."""
    pc = _pipeline()
    cfg.SCENE_CONTENT_SOURCE = route
    if prompt_session is None:
        prompt_session = pc._prepare_character_facts(
            {
                "name": char["name_cn"],
                "series": char["series_cn"],
                "name_en": char["name_en"],
                "series_en": char["series"],
                "appearance_version": char["version"],
            },
            audit_dir,
        )
    return pc._build_all_channel_prompts(
        cfg.active_prompt_channels(),
        name=char["name_cn"],
        series=char["series_cn"],
        name_en=char["name_en"],
        series_en=char["series"],
        theme=char["theme"],
        prompt_theme=char["theme"],
        framing="",
        workflow=workflow,
        appearance_version=char["version"],
        prompt_session=prompt_session,
        audit_dir=audit_dir,
    )


def generate(
    workflow,
    model_label,
    char,
    *,
    variant="random",
    sampler=None,
    artist="random",
    route="mixed",
    count=5,
    seeds=None,
    dry_run=False,
    output_dir=None,
    prompt_session=None,
):
    print(
        f"\n[生成] {model_label} | {char['name_cn']} | 主题 {char['theme']} | 线路 {route} | {count} 张"
    )
    print(
        f"       权重：{variant} | 画风：{artist or '无'} | 采样器：{(sampler[4] if sampler else '随机')}"
    )
    if dry_run:
        print("[dry-run] 不调用 DeepSeek、不出图")
        return None
    if (
        workflow not in cfg.WORKFLOW_POOL
        or variant not in ("random", "native", "int8")
        or route not in ("mixed", "deepseek", "fixed")
        or count not in (1, 5)
    ):
        raise ValueError("无效的本地出图选项。")
    if seeds is not None and (
        len(seeds) != count
        or any(
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or not 0 <= seed <= cfg.seed_max_for(workflow)
            for seed in seeds
        )
    ):
        raise ValueError("seed 数量或取值无效。")
    out_dir = output_dir or _pipeline().new_run_dir("custom", char["name_en"] + "_" + char["theme"])
    os.makedirs(out_dir, exist_ok=True)
    saved = {
        "variant": cr.anima_model_roll,
        "artist_roll": cr.artist_roll,
        "combos": cr.anima_artist_combos,
        "samplers": cr.KSAMPLER_COMBOS,
        "route": cfg.SCENE_CONTENT_SOURCE,
    }
    try:
        built = build_v2(
            char,
            workflow,
            route,
            audit_dir=os.path.join(out_dir, "数据", "提示词会话"),
            prompt_session=prompt_session,
        )
        prompt_list = [
            {
                "positive": b["positive"],
                "negative": b["negative"],
                "identity": {
                    "name_en": char["name_en"],
                    "series_en": char["series"],
                    "anima_prompt_contract": (b.get("structured") or {}).get(
                        "anima_prompt_contract"
                    ),
                    "eye_colors": str((b.get("structured") or {}).get("eye_colors", "")).strip(),
                },
                "theme": char["theme"],
                "candidate_prompts": (b.get("structured") or {}).get("candidate_prompts"),
                "channel": b["channel"],
                "prompt_session_audit": (b.get("structured") or {}).get("prompt_session_audit"),
            }
            for b in built
        ]
        ensure_comfyui()
        if variant != "random":
            cr.anima_model_roll = lambda: variant
        if artist is None:
            lo, hi = getattr(cfg, "ARTIST_CFG_OFF_RANGE", (3.5, 5.0))
            cr.artist_roll = lambda: (False, round(random.uniform(lo, hi), 2))
        elif artist != "random":
            cr.artist_roll = lambda: (True, getattr(cfg, "ARTIST_CFG_ON", 3.7))
            cr.anima_artist_combos = lambda series: ("custom", [artist])
        if sampler:
            cr.KSAMPLER_COMBOS = [sampler]
        os.makedirs(out_dir, exist_ok=True)
        result = cr.generate_images(
            prompt_list=prompt_list,
            output_dir=out_dir,
            candidates=count,
            workflow=workflow,
            seeds=seeds,
            run_retries=0,
            before_retry=ensure_comfyui,
        )
    finally:
        cr.anima_model_roll, cr.artist_roll = (saved["variant"], saved["artist_roll"])
        cr.anima_artist_combos, cr.KSAMPLER_COMBOS = (saved["combos"], saved["samplers"])
        cfg.SCENE_CONTENT_SOURCE = saved["route"]
    if not result:
        raise RuntimeError("出图失败：没有生成可用图片，请查看本次运行日志")
    print(f"\n[输出] {out_dir}")
    save_json(
        os.path.join(out_dir, "last_entry.json"),
        {
            "workflow": workflow,
            "model": model_label,
            "character": char,
            "variant": variant,
            "artist": artist,
            "sampler": sampler,
            "route": route,
            "count": count,
            "seeds": seeds,
            "result": str(result)[:2000],
        },
    )
    return result


def main():
    dry = "--dry-run" in sys.argv
    if "--list" in sys.argv:
        list_models()
        list_samplers()
        list_artists()
        list_themes()
        return
    print("=" * 70)
    print("Anima 本地自选出图：人物、主题、工作流和画风")
    print("=" * 70)
    workflow, label = choose_model()
    if not workflow:
        return
    variant = choose_variant()
    sampler = choose_sampler(workflow)
    artist = choose_artist(workflow)
    char = ask_character()
    if not char["name_en"] or not char["series"]:
        print("人物/作品英文标签不能为空")
        return
    char["theme"] = choose_theme()
    route = choose_route()
    count, seeds = choose_count()
    return generate(
        workflow,
        label,
        char,
        variant=variant,
        sampler=sampler,
        artist=artist,
        route=route,
        count=count,
        seeds=seeds,
        dry_run=dry,
    )


def _pipeline():
    import pipeline_character as pc

    pc.configure_client()
    return pc


def change_comfyui_path():
    import ensure_comfyui as ec

    print("本次会话使用的 ComfyUI 路径；下次启动请用环境变量配置。")
    directory = input("ComfyUI 目录（留空保持）：").strip()
    python = input("ComfyUI Python 路径（留空保持）：").strip()
    if directory:
        cfg.COMFY_DIR = ec.COMFY_DIR = directory
    if python:
        cfg.COMFY_PYTHON = ec.COMFY_PYTHON = python
    enabled = bool(cfg.COMFY_DIR and cfg.COMFY_PYTHON)
    cfg.COMFY_AUTOSTART = ec.COMFY_AUTOSTART = enabled
    print("本进程配置已更新；未写入长期设置。")


if __name__ == "__main__":
    main()
