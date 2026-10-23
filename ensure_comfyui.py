# -*- coding: utf-8 -*-
"""
ensure_comfyui.py — ComfyUI 自动拉起 / 健康检查

为什么需要它：
    流水线跑出图前如果 ComfyUI 没开，generate_images 会直接失败，
    而且 client 默认不会报错（requests 异常被吞成空列表），只留下"出图失败"。
    这个模块在跑图前确认服务在，不在就自动拉起来并等到就绪。

为什么不用 start_comfyui.bat：
    那个脚本带 --lowvram，会把 Anima 的文本编码器甩到 CPU 上跑。
    实测同一配置单张从 115s 退化到 372s（慢 3 倍）。
    这里默认不带 --lowvram（显存不够时 ComfyUI 自己会按需 offload）。

用法：
    python ensure_comfyui.py          # 检查，必要时拉起，等到就绪
    python ensure_comfyui.py --status # 只看状态，不拉起
    python ensure_comfyui.py --stop   # 停掉本模块拉起的 ComfyUI

在代码里：
    from ensure_comfyui import ensure_comfyui
    ensure_comfyui()        # 失败会抛 RuntimeError
"""
import argparse
import os
import subprocess
import sys
import time

import httpx

from config import (
    COMFY_URL, COMFY_DIR, COMFY_PYTHON, COMFY_START_ARGS,
    COMFY_BOOT_TIMEOUT, COMFY_AUTOSTART,
)

PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comfyui.pid")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comfyui_server.log")
ERR_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comfyui_server.err.log")


def is_ready(timeout=4.0):
    """ComfyUI 是否已经能响应 /system_stats"""
    try:
        r = httpx.get(f"{COMFY_URL}/system_stats", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def system_stats(timeout=6.0):
    try:
        return httpx.get(f"{COMFY_URL}/system_stats", timeout=timeout).json()
    except Exception:
        return None


def _read_pid():
    try:
        with open(PID_FILE, "r", encoding="ascii") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _pid_alive(pid):
    if not pid:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=15)
        return "python" in out.stdout.lower()
    except Exception:
        return False


def start_comfyui(wait=True, verbose=True):
    """启动 ComfyUI（分离进程，日志写到 comfyui_server*.log）"""
    if not os.path.isfile(COMFY_PYTHON):
        raise RuntimeError(f"找不到 ComfyUI 的 python：{COMFY_PYTHON}")
    if not os.path.isdir(COMFY_DIR):
        raise RuntimeError(f"找不到 ComfyUI 目录：{COMFY_DIR}")

    creationflags = 0
    if os.name == "nt":
        creationflags = (subprocess.DETACHED_PROCESS
                         | subprocess.CREATE_NEW_PROCESS_GROUP)

    if verbose:
        print(f"[ComfyUI] 启动中：{COMFY_PYTHON} {' '.join(COMFY_START_ARGS)}")
        print(f"[ComfyUI] 日志：{LOG_FILE}")

    with open(LOG_FILE, "wb") as out, open(ERR_LOG_FILE, "wb") as err:
        proc = subprocess.Popen(
            [COMFY_PYTHON] + COMFY_START_ARGS,
            cwd=COMFY_DIR, stdout=out, stderr=err,
            creationflags=creationflags, close_fds=True,
        )

    try:
        with open(PID_FILE, "w", encoding="ascii") as f:
            f.write(str(proc.pid))
    except Exception:
        pass

    if not wait:
        return proc.pid

    deadline = time.time() + COMFY_BOOT_TIMEOUT
    while time.time() < deadline:
        if is_ready():
            if verbose:
                print(f"[ComfyUI] 已就绪（PID={proc.pid}）：{COMFY_URL}")
            return proc.pid
        if proc.poll() is not None:
            tail = ""
            try:
                with open(ERR_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    tail = f.read()[-800:]
            except Exception:
                pass
            raise RuntimeError(
                f"ComfyUI 启动后立即退出（exit={proc.returncode}）\n{tail}")
        time.sleep(3)

    raise RuntimeError(f"等待 ComfyUI 就绪超时（{COMFY_BOOT_TIMEOUT}s），"
                       f"请看日志 {LOG_FILE} / {ERR_LOG_FILE}")


def stop_comfyui(verbose=True):
    pid = _read_pid()
    if not pid or not _pid_alive(pid):
        if verbose:
            print("[ComfyUI] 没有记录到正在运行的进程")
        return False
    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                   capture_output=True, text=True, timeout=20)
    if verbose:
        print(f"[ComfyUI] 已停止 PID={pid}")
    return True


def ensure_comfyui(auto_start=None, verbose=True):
    """
    对外主入口：服务在就返回 True，不在就按配置拉起。
    拉起失败抛 RuntimeError；配置关闭自动拉起且服务不在时抛 RuntimeError。
    """
    if auto_start is None:
        auto_start = COMFY_AUTOSTART

    if is_ready():
        if verbose:
            stats = system_stats()
            free = None
            try:
                free = round(stats["devices"][0]["vram_free"] / 2 ** 30, 2)
            except Exception:
                pass
            print(f"[ComfyUI] 已在运行：{COMFY_URL}"
                  + (f"（显存空闲 {free} GB）" if free else ""))
        return True

    if not auto_start:
        raise RuntimeError(f"ComfyUI 未运行且未开启自动拉起：{COMFY_URL}")

    if verbose:
        print("[ComfyUI] 未检测到服务，自动拉起……")
    start_comfyui(wait=True, verbose=verbose)
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只看状态，不拉起")
    ap.add_argument("--stop", action="store_true", help="停止 ComfyUI")
    ap.add_argument("--start", action="store_true", help="强制拉起（已在运行则跳过）")
    args = ap.parse_args()

    if args.stop:
        stop_comfyui()
        sys.exit(0)

    if args.status:
        if is_ready():
            stats = system_stats() or {}
            dev = (stats.get("devices") or [{}])[0]
            print(f"运行中：{COMFY_URL}")
            print(f"  显存：空闲 {dev.get('vram_free', 0) / 2**30:.2f} GB "
                  f"/ 共 {dev.get('vram_total', 0) / 2**30:.2f} GB")
            print(f"  ComfyUI 版本：{stats.get('system', {}).get('comfyui_version')}")
            pid = _read_pid()
            print(f"  记录的 PID：{pid}（存活={_pid_alive(pid)}）")
        else:
            print(f"未运行：{COMFY_URL}")
        sys.exit(0)

    try:
        ensure_comfyui(auto_start=True)
    except Exception as e:
        print(f"[失败] {type(e).__name__}: {e}")
        sys.exit(1)
