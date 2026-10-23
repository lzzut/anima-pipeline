# -*- coding: utf-8 -*-
"""
prompt_style.py — 给"提示词生成模型"看的风格指令

【变更记录 2026-10-10】
Z-Image 工作流已整体移除（通用系模型画指定角色只出通用脸，还原度不达标），
因此本模块中所有 Z-Image 专用机制（风格锚、去玩偶脸替换规则、身份锚加权、
纯拟真档等）一并删除。现在只保留各在用工作流的风格指令。
"""


def style_directive(workflow, anchor=None):
    """按工作流给出该模型要求的提示词风格规范（anchor 参数已废弃，保留兼容）"""
    if workflow == "anima_flow":
        return (
            "【本工作流的风格要求 — Anima-2.9B (Flow 采样器)】\n"
            "- 目标风格：纯二次元赛璐璐插画，线条清晰、色块干净\n"
            "- 保留 Danbooru 标签写法，正常输出负面提示词"
        )
    if workflow in ("animagine_xl", "nova_xl"):
        return (
            "【本工作流的风格要求 — SDXL 动漫底模（danbooru 标签训练）】\n"
            "- 目标风格：高质量动漫插画，线条清晰、上色干净\n"
            "- 该模型**认识角色标签**：角色名与作品名要按 Danbooru 标准标签写准\n"
            "- 质量词与负面提示词都正常生效"
        )
    return (
        "【本工作流的风格要求 — Anima-2.9B (KSampler)】\n"
        "- 目标风格：纯二次元赛璐璐插画，线条清晰、色块干净\n"
        "- 保留 Danbooru 标签写法，正常输出负面提示词"
    )
