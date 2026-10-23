# -*- coding: utf-8 -*-
"""
smoke_test.py — 不依赖 DeepSeek 的最小出图验证。

用途：
    先确认 ComfyUI、Anima 权重、VAE、CLIP 和 workflow_api.json 能正常工作。
    这一步只生成一张 8 步测试图，不选角、不调用任何外部 API。

运行：
    python smoke_test.py

成功时输出：
    [smoke] OK: <path> (1024x1536, ... bytes)
"""
import os
import sys

import comfy_runner as cr
from config import ANIMA_UNET
from ensure_comfyui import is_ready


def main():
    if not is_ready():
        print("[smoke] ComfyUI 未运行。请先启动 ComfyUI，或配置 COMFY_DIR / "
              "COMFY_PYTHON 后重试。")
        return 2

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "smoke")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "smoke.png")
    pos = ("year 2025, masterpiece, best quality, score_7, safe, 1girl, solo, "
           "upper body, looking at viewer, simple background, soft lighting")
    neg = ("worst quality, low quality, score_1, score_2, score_3, blurry, "
           "bad anatomy, watermark, text")

    print(f"[smoke] ComfyUI OK; unet={ANIMA_UNET}")
    print("[smoke] generating 8-step test image ...")
    got = cr._run_once("api", pos, neg, 20261024, out,
                       steps=8, cfg=3.7,
                       sampler="euler", scheduler="sgm_uniform")
    if not (got and os.path.isfile(got) and os.path.getsize(got) > 0):
        print("[smoke] FAILED: no image returned")
        return 1

    from PIL import Image
    with Image.open(got) as im:
        w, h = im.size
    print(f"[smoke] OK: {got} ({w}x{h}, {os.path.getsize(got)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
