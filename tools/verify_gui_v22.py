# -*- coding: utf-8 -*-
"""启动 v2.2 exe，截窗口图 + 托盘区域图，验证图标/按钮/文案改动。"""
import subprocess
import time
from pathlib import Path

import psutil
import win32con
import win32gui
from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.exe"
TEMP = ROOT / "temp"


def find_windows():
    out = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if "HONOR 电池安全管理" in t:
                out.append((hwnd, t))

    win32gui.EnumWindows(cb, None)
    return out


def main():
    before = {p.pid for p in psutil.process_iter(["name"])
              if p.info["name"] and "HonorBatteryGuard" in p.info["name"]}
    proc = subprocess.Popen([str(EXE)], close_fds=True)
    print("launched pid", proc.pid)
    time.sleep(6)

    wins = find_windows()
    print("windows:", wins)
    if wins:
        hwnd, title = wins[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(1.5)
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        print("window rect", (l, t, r, b))
        img = ImageGrab.grab(bbox=(l, t, r, b))
        img.save(TEMP / "gui_v22_window.png")
        # 单独放大标题栏左上角 + 按钮行
        w, h = img.size
        img.crop((0, 0, min(200, w), min(60, h))).resize(
            (min(200, w) * 3, min(60, h) * 3), Image.NEAREST).save(TEMP / "gui_v22_titlebar.png")

    screen = ImageGrab.grab()
    sw, sh = screen.size
    screen.crop((sw - 460, sh - 90, sw, sh)).save(TEMP / "gui_v22_tray_area.png")
    screen.save(TEMP / "gui_v22_screen.png")
    print("screenshots saved")

    # 清理：只结束本次启动的进程树
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if p.info["pid"] in before:
                continue
            if p.info["name"] and "HonorBatteryGuard" in p.info["name"]:
                p.terminate()
        except Exception:
            pass
    time.sleep(1)
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and "HonorBatteryGuard" in p.info["name"]:
                p.kill()
        except Exception:
            pass
    print("cleaned")


if __name__ == "__main__":
    main()
