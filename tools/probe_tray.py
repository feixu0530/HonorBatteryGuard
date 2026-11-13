# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""诊断 pystray 是否真的向 Shell 添加了托盘图标（拦截 Shell_NotifyIcon 返回值）。"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageGrab
import pystray
import pystray._win32 as backend

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "dev" / "HonorBatteryGuard.png"
SHOT = ROOT / "temp" / "tray_probe.png"

orig = backend.win32.Shell_NotifyIcon
calls = []


def spy(code, data):
    ret = orig(code, data)
    calls.append({"code": code, "ret": bool(ret), "hwnd": getattr(data, "hWnd", None)})
    return ret


backend.win32.Shell_NotifyIcon = spy

image = Image.open(IMG).convert("RGBA").resize((64, 64), Image.LANCZOS)
icon = pystray.Icon("HBGProbe", image, "HBG-PROBE-TRAY",
                    pystray.Menu(pystray.MenuItem("退出", lambda *_: None)))
icon.run_detached()
time.sleep(3)
print("visible =", icon.visible)
print("_hwnd   =", getattr(icon, "_hwnd", None))
print("notify calls =", calls)

full = ImageGrab.grab()
w, h = full.size
full.crop((w - 700, h - 180, w, h)).save(SHOT)
print("screenshot =", SHOT)
time.sleep(2)
icon.stop()
