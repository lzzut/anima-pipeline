# -*- coding: utf-8 -*-
"""
custom_entry.py — 自定义人物 / 模型 / 画师入口（新增功能，不改动原自动化流程）

运行：
    python custom_entry.py            # 交互菜单
    python custom_entry.py --list     # 只列出模型/采样器/画师
    python custom_entry.py --dry-run  # 走完菜单但不真的出图

菜单编号：
    工作流：动态列出 config.WORKFLOW_SETTINGS 中已注册的 key
            （包括用户自己注册并加入 WORKFLOW_POOL 的工作流）
            9=修改 ComfyUI 路径
    选中工作流后：再选采样器组合、画师组合（有多个选项时才需要选）
"""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as cfg
import comfy_runner as cr
import pipeline_character as pc
import artist_matrix_test as am
from ensure_comfyui import ensure_comfyui

BASE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE, "user_settings.json")
OUT_ROOT = os.path.join(BASE, "output", "_custom_entry")

def model_entries():
    """所有已注册工作流；WORKFLOW_POOL 内的排前面。"""
    keys = []
    for k in list(cfg.WORKFLOW_POOL) + list(cfg.WORKFLOW_SETTINGS):
        if k in cfg.WORKFLOW_SETTINGS and k not in keys:
            keys.append(k)
    out = []
    for k in keys:
        info = cfg.WORKFLOW_MODEL_INFO.get(k, {})
        label = info.get("label") or k
        desc = info.get("family") or (
            "自定义工作流" if k not in ("api", "anima_flow") else "")
        if k not in cfg.WORKFLOW_POOL:
            desc = (desc + "（未加入自动池）").strip()
        out.append((k, label, desc))
    return out

# 画师组合简要说明（按主画师）
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


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_settings():
    s = load_json(SETTINGS_PATH, {})
    if s.get("comfyui_dir"):
        cfg.COMFY_DIR = s["comfyui_dir"]
    if s.get("comfyui_python"):
        cfg.COMFY_PYTHON = s["comfyui_python"]
    try:
        import ensure_comfyui as ec
        ec.COMFY_DIR = cfg.COMFY_DIR
        ec.COMFY_PYTHON = cfg.COMFY_PYTHON
    except Exception:
        pass
    return s


def save_settings(s):
    save_json(SETTINGS_PATH, s)


def list_models():
    print("\n可选工作流：")
    for i, (key, name, desc) in enumerate(model_entries(), 1):
        info = cfg.WORKFLOW_MODEL_INFO.get(key, {})
        print(f"  {i}. {name}  [{key}]  | 截止 {info.get('cutoff', '?')}  | {desc}")
    print("  9. 修改 ComfyUI 路径")
    print("  q. 退出")


def sampler_entries(workflow="api"):
    """当前工作流可选的采样器组合；只有一项时自动使用。"""
    st = cfg.WORKFLOW_SETTINGS.get(workflow, {})
    if workflow == "api":
        return list(cfg.KSAMPLER_COMBOS)
    if workflow == "anima_flow":
        return [(None, None, int(st.get("steps", 50)),
                 float(st.get("cfg", 5.0)), "AnimaFlow 固定采样器")]
    combos = st.get("sampler_combos") or []
    if combos:
        return [tuple(c) for c in combos if isinstance(c, (list, tuple)) and len(c) >= 5]
    if st.get("sampler") or st.get("scheduler") or st.get("steps"):
        return [(st.get("sampler"), st.get("scheduler"),
                 int(st.get("steps", 30)), float(st.get("cfg", 5.0)),
                 "工作流默认")]
    return []


def list_samplers(workflow="api"):
    entries = sampler_entries(workflow)
    print(f"\n采样器组合（{workflow}）：")
    if not entries:
        print("  工作流 JSON 内置采样器，无额外选项")
        return entries
    for i, c in enumerate(entries, 1):
        print(f"  {i}. {c[4]}  [{c[0] or '默认'} + {c[1] or '默认'} / "
              f"{c[2]}步 / cfg{c[3]}]")
    return entries


def list_artists():
    combos = list(dict.fromkeys(cfg.anima_artist_combos("__global__")[1]))
    print("\n画师组合（Anima @ 权重语法）：")
    for i, c in enumerate(combos, 1):
        primary = c.split(",")[0].strip()
        note = ARTIST_NOTES.get(primary, "综合风格")
        print(f"  {i:2d}. {c}   — {note}")
    return combos


def choose_model():
    models = model_entries()
    list_models()
    raw = input("\n选择工作流编号：").strip().lower()
    if raw == "q":
        return None, None
    if raw == "9":
        change_comfyui_path()
        return choose_model()
    try:
        n = int(raw)
    except ValueError:
        print("编号无效")
        return choose_model()
    if 1 <= n <= len(models):
        return models[n - 1][0], models[n - 1][1]
    print("编号无效")
    return choose_model()


def choose_sampler(workflow):
    entries = list_samplers(workflow)
    if not entries:
        return None
    if len(entries) == 1:
        print(f"只有一种采样器组合，自动使用：{entries[0][4]}")
        return entries[0]
    raw = input("\n选择采样器组合编号（默认 1）：").strip() or "1"
    try:
        return entries[int(raw) - 1]
    except Exception:
        print("编号无效，用 1")
        return entries[0]


def choose_artist(workflow):
    if workflow not in ("api", "anima_flow"):
        print("注意：自定义模型未必支持 Anima 的 @ 画师串/权重语法；"
              "仍可注入，效果需自测。")
    combos = list_artists()
    raw = input("\n选择画师组合编号（0=不加画师，默认 0）：").strip() or "0"
    if raw == "0":
        return None
    try:
        return combos[int(raw) - 1]
    except Exception:
        print("编号无效，用不加画师")
        return None


def ask_character():
    print("\n自定义人物（英文标签建议直接写 danbooru tag）")
    name_cn = input("人物中文名：").strip()
    series_cn = input("作品中文名：").strip()
    name_en = input("人物英文标签（如 furina_(genshin_impact)）：").strip()
    series = input("作品英文标签（如 genshin_impact）：").strip()
    theme = input("主题（默认 四季常装）：").strip() or "四季常装"
    framing = input("景别（默认 cowboy shot）：").strip() or "cowboy shot"
    seed = input("seed（默认 20261022）：").strip() or "20261022"
    return {
        "name_cn": name_cn or name_en,
        "series_cn": series_cn or series,
        "name_en": name_en,
        "series": series,
        "theme": theme,
        "framing": framing,
        "seed": int(seed) if seed.isdigit() else 20261022,
    }


def build_prompt(char, workflow):
    st = pc.ask_ai_prompt(char["name_cn"], char["series_cn"], char["name_en"],
                          char["series"], char["theme"],
                          framing=char["framing"], workflow=workflow)
    pos = pc.assemble_positive_prompt(
        st, char["name_en"], char["series"], char["framing"],
        extra_fields=tuple(getattr(cfg, "ANIMA_EXTRA_TEMPLATE_FIELDS", ()) or ()))
    if workflow in ("api", "anima_flow"):
        pos = pc._fix_anima_prompt(pos, char["name_en"], char["series"])
    neg = pc.build_negative(st.get("negative") or st.get("negatives", ""))
    pos, neg = cr.format_prompt(workflow, pos, neg, identity=st, theme=char["theme"])
    if workflow in ("api", "anima_flow"):
        for extra in (cfg.ANIMA_DYNAMIC_NEGATIVE, cfg.ANIMA_INTEGRATION_NEGATIVE):
            if extra and extra.split(",")[0].strip().lower() not in neg.lower():
                neg += ", " + extra
    return pos, neg


def generate(workflow, model_label, char, sampler=None, artist=None, dry_run=False):
    if workflow not in cr.WORKFLOW_SETTINGS:
        raise ValueError(f"未知工作流：{workflow}")
    st = cfg.WORKFLOW_SETTINGS.get(workflow, {})
    if sampler is None and workflow == "api":
        sampler = cfg.KSAMPLER_COMBOS[0]
    print(f"\n[生成] {model_label} | {char['name_cn']} | 主题 {char['theme']} | 景别 {char['framing']}")
    print(f"       画师：{artist or '无'} | 采样器：{sampler[4] if sampler else '工作流默认'}")
    if dry_run:
        print("[dry-run] 不实际出图")
        return None
    if workflow in ("api", "anima_flow"):
        cfg.set_active_unet("native")
    ensure_comfyui()
    pos, neg = build_prompt(char, workflow)
    if artist:
        pos = am._replace_artist(pos, char["series"], artist)
    out_dir = os.path.join(OUT_ROOT, time.strftime("%Y-%m-%d"))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{am._slug(char['name_en'], 40)}_{am._slug(char['theme'], 20)}.png")
    steps = sampler[2] if sampler else int(st.get("steps", 30))
    conf = sampler[3] if sampler else float(st.get("cfg", 5.0))
    sp = sampler[0] if sampler else st.get("sampler")
    sc = sampler[1] if sampler else st.get("scheduler")
    flow_settings = (cfg.ANIMA_FLOW_SETTINGS if workflow == "anima_flow"
                     else st.get("flow_settings"))
    got = cr._run_once(workflow, pos, neg, char["seed"], out,
                       steps=steps, cfg=conf, sampler=sp, scheduler=sc,
                       flow_settings=flow_settings)
    score = None
    try:
        score = round(cr._score_image(got), 3)
    except Exception:
        pass
    print(f"\n[输出] {got} | score={score}")
    save_json(os.path.join(out_dir, "last_entry.json"), {
        "workflow": workflow, "model": model_label, "character": char,
        "artist": artist, "sampler": sampler, "file": got, "score": score,
    })
    return got


def change_comfyui_path():
    s = load_settings()
    print(f"\n当前 ComfyUI 目录：{getattr(cfg, 'COMFY_DIR', '?')}")
    d = input("新 ComfyUI 目录（留空不改）：").strip()
    p = getattr(cfg, "COMFY_PYTHON", "")
    print(f"当前 Python：{p}")
    py = input("新 ComfyUI Python 路径（留空不改）：").strip()
    if d:
        s["comfyui_dir"] = d
        cfg.COMFY_DIR = d
    if py:
        s["comfyui_python"] = py
        cfg.COMFY_PYTHON = py
    save_settings(s)
    try:
        import ensure_comfyui as ec
        ec.COMFY_DIR = cfg.COMFY_DIR
        ec.COMFY_PYTHON = cfg.COMFY_PYTHON
    except Exception:
        pass
    print("已保存到 user_settings.json")


def main():
    dry = "--dry-run" in sys.argv
    if "--list" in sys.argv:
        models = model_entries()
        list_models()
        for key, _label, _desc in models:
            list_samplers(key)
        list_artists()
        return
    load_settings()
    print("=" * 70)
    print("自定义人物入口（原自动化流程不受影响）")
    print("=" * 70)
    workflow, label = choose_model()
    if not workflow:
        return
    sampler = choose_sampler(workflow)
    artist = choose_artist(workflow)
    char = ask_character()
    if not char["name_en"] or not char["series"]:
        print("人物/作品英文标签不能为空")
        return
    generate(workflow, label, char, sampler=sampler, artist=artist, dry_run=dry)


if __name__ == "__main__":
    main()
