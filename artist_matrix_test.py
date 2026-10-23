# -*- coding: utf-8 -*-
"""
artist_matrix_test.py — 画师组合相关的轻量工具函数。

公开版只保留主链实际使用的两个函数：
  · _slug             生成安全的文件名片段
  · _replace_artist   把画师串插到作品标签之后
"""
import re


def _slug(s, n=54):
    s = re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")
    return s[:n] or "combo"


def _replace_artist(prompt, series_tag, combo):
    """删掉原画师 @ 段，把新组合插到系列标签后面。"""
    frags = [x.strip() for x in str(prompt).split(",") if x.strip()]
    frags = [x for x in frags if "@" not in x]
    new = [x.strip() for x in combo.split(",") if x.strip()]
    out, done = [], False
    for x in frags:
        out.append(x)
        if not done and x.lower() == series_tag.lower():
            out.extend(new)
            done = True
    if not done:
        # 兜底：插在 solo 后
        out2 = []
        for x in out:
            out2.append(x)
            if not done and x.lower() == "solo":
                out2.extend(new)
                done = True
        out = out2 if done else new + out
    return ", ".join(out)
