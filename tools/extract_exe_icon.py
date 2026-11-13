# -*- coding: utf-8 -*-
# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""提取 exe 的关联/资源图标保存为 PNG，用于核对打包图标是否生效。"""
import sys
from pathlib import Path

import win32con
import win32gui
import win32ui
from PIL import Image


def dump(exe: str, out: str) -> None:
    large, small = win32gui.ExtractIconEx(exe, 0)
    icons = large or small
    if not icons:
        print("NO ICON RESOURCE")
        return
    hicon = icons[0]
    info = win32gui.GetIconInfo(hicon)
    hbmp = info[3]  # hbmColor
    bm = win32gui.GetObject(hbmp)
    w, h = bm.bmWidth, bm.bmHeight

    hwnd = win32gui.GetDesktopWindow()
    hdc = win32gui.GetWindowDC(hwnd)
    srcdc = win32ui.CreateDCFromHandle(hdc)
    memdc = srcdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(srcdc, w, h)
    memdc.SelectObject(bmp)
    memdc.DrawIcon((0, 0), hicon)
    bits = bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGBA", (w, h), bits, "raw", "BGRA", 0, 1)
    img.save(out)
    print(f"icon={w}x{h} -> {out}")
    for hi in large + small:
        try:
            win32gui.DestroyIcon(hi)
        except Exception:
            pass
    memdc.DeleteDC()
    srcdc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    win32gui.DeleteObject(hbmp)


if __name__ == "__main__":
    dump(sys.argv[1], sys.argv[2])
