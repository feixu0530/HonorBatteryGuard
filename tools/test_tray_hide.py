# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""验证点击窗口关闭按钮时，程序隐藏到系统托盘而不是退出。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psutil
import win32gui

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.exe"
LOG = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.log"
TITLE_KEY = "HONOR 电池安全管理"
WM_CLOSE = 0x0010


def visible_windows():
    """返回 (hwnd, 标题, 是否最小化)。最小化窗口仍算可见，任务栏按钮保留。"""
    found = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if TITLE_KEY in title:
                found.append((hwnd, title, bool(win32gui.IsIconic(hwnd))))

    win32gui.EnumWindows(cb, None)
    return found


def tree_alive(proc):
    try:
        if proc.is_running():
            return True
        return any(c.is_running() for c in proc.children(recursive=True))
    except (psutil.Error, OSError):
        return False


def main():
    r = {}
    log_size = LOG.stat().st_size if LOG.exists() else 0
    proc = psutil.Popen([str(EXE)], cwd=str(EXE.parent))
    try:
        time.sleep(5)
        r["windows_before_close"] = [t for _, t, _ in visible_windows()]
        r["alive_before_close"] = tree_alive(proc)
        for hwnd, _, _ in visible_windows():
            win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
        time.sleep(2)
        after = visible_windows()
        r["windows_after_close"] = [f"{t}（最小化={i}）" for _, t, i in after]
        r["taskbar_button_kept"] = bool(after) and all(i for _, _, i in after)
        r["alive_after_close"] = tree_alive(proc)
        with LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(log_size)
            lines = f.read().strip().splitlines()
        r["new_log"] = lines[-8:]
        r["hidden_log"] = any("最小化到任务栏" in x for x in lines)
        r["verdict"] = "PASS" if (r["windows_before_close"]
                                  and r["taskbar_button_kept"]
                                  and r["alive_after_close"]
                                  and r["hidden_log"]) else "FAIL"
    finally:
        try:
            children = proc.children(recursive=True)
            for c in children:
                try:
                    c.terminate()
                except Exception:
                    pass
            psutil.wait_procs(children, timeout=3)
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        r["alive_after_cleanup"] = tree_alive(proc)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
