# -*- coding: utf-8 -*-
# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""v2.2.0 回归：关闭窗口两种行为 + 托盘菜单动态勾选状态。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psutil
import win32gui

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import HonorBatteryGuard as H  # noqa: E402

EXE = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.exe"
CFG = EXE.parent / "HonorBatteryGuard.json"
LOG = EXE.parent / "HonorBatteryGuard.log"
TITLE_KEY = "HONOR 电池安全管理"
WM_CLOSE = 0x0010


def visible_windows():
    out = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and TITLE_KEY in win32gui.GetWindowText(hwnd):
            out.append((hwnd, win32gui.GetWindowText(hwnd)))

    win32gui.EnumWindows(cb, None)
    return out


def tree_alive(proc):
    try:
        return proc.is_running() or any(c.is_running() for c in proc.children(recursive=True))
    except (psutil.Error, OSError):
        return False


def kill_tree(proc):
    try:
        for c in proc.children(recursive=True):
            try:
                c.terminate()
            except Exception:
                pass
        proc.terminate()
        proc.wait(timeout=4)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def test_close(hide_to_tray: bool) -> dict:
    # 必须直接写 exe 同目录的配置（源码模式 read_config 指向 dev/，不能复用）
    cfg = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {}
    cfg["hide_to_tray"] = hide_to_tray
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    log_size = LOG.stat().st_size if LOG.exists() else 0
    proc = psutil.Popen([str(EXE)], cwd=str(EXE.parent))
    r = {"hide_to_tray": hide_to_tray}
    try:
        time.sleep(5)
        r["windows_before"] = len(visible_windows())
        for hwnd, _ in visible_windows():
            win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
        time.sleep(2.5)
        r["windows_after"] = len(visible_windows())
        r["alive_after"] = tree_alive(proc)
        with LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(log_size)
            r["new_log"] = f.read().strip().splitlines()[-5:]
        if hide_to_tray:
            r["verdict"] = "PASS" if (r["windows_before"] == 1
                                      and r["windows_after"] == 0
                                      and r["alive_after"]) else "FAIL"
        else:
            r["verdict"] = "PASS" if (r["windows_before"] == 1
                                      and r["windows_after"] == 0
                                      and not r["alive_after"]) else "FAIL"
    finally:
        kill_tree(proc)
        r["alive_after_cleanup"] = tree_alive(proc)
    return r


def test_menu_dynamic() -> dict:
    """直接验证菜单描述符的动态 text / checked 会随注册表状态变化。"""
    import pystray

    orig = H.autostart_state()["enabled"]
    r = {}
    try:
        H.enable_autostart("home", True)
        items = {
            "auto": pystray.MenuItem(
                lambda item: "随系统启动（已启用）" if H.autostart_state()["enabled"] else "随系统启动（未启用）",
                lambda *_: None,
                checked=lambda item: H.autostart_state()["enabled"]),
        }
        r["text_when_on"] = items["auto"].text
        r["checked_when_on"] = items["auto"].checked
        H.disable_autostart()
        r["text_when_off"] = items["auto"].text
        r["checked_when_off"] = items["auto"].checked
        r["verdict"] = "PASS" if (r["checked_when_on"] is True
                                  and r["checked_when_off"] is False
                                  and "已启用" in r["text_when_on"]
                                  and "未启用" in r["text_when_off"]) else "FAIL"
    finally:
        if orig:
            H.enable_autostart("home", True)
        else:
            H.disable_autostart()
        r["autostart_restored"] = H.autostart_state()["enabled"] == orig
    return r


def main():
    cfg_orig = CFG.read_text(encoding="utf-8") if CFG.exists() else None
    results = {}
    try:
        results["close_exit"] = test_close(False)
        results["close_hide_to_tray"] = test_close(True)
        results["menu_dynamic"] = test_menu_dynamic()
    finally:
        if cfg_orig is not None:
            CFG.write_text(cfg_orig, encoding="utf-8")
        results["config_restored"] = (
            json.loads(CFG.read_text(encoding="utf-8")).get("hide_to_tray")
            if CFG.exists() else None)
    results["overall"] = "PASS" if all(
        v.get("verdict") == "PASS" for k, v in results.items() if isinstance(v, dict)
    ) else "FAIL"
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if results["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
