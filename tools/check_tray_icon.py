# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""截取屏幕右下角通知区域，检查托盘图标是否真的可见，并收集程序日志。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import psutil
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.exe"
LOG = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.log"
SHOT = ROOT / "temp" / "tray_area.png"


def main():
    r = {}
    log_size = LOG.stat().st_size if LOG.exists() else 0
    proc = psutil.Popen([str(EXE), "--tray"], cwd=str(EXE.parent))
    try:
        time.sleep(6)
        full = ImageGrab.grab(all_screens=False)
        w, h = full.size
        box = (max(0, w - 700), max(0, h - 180), w, h)
        full.crop(box).save(SHOT)
        r["screen"] = [w, h]
        r["crop_box"] = list(box)
        r["screenshot"] = str(SHOT)
        r["alive"] = proc.is_running() or any(
            c.is_running() for c in proc.children(recursive=True))
        with LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(log_size)
            r["new_log"] = f.read().strip().splitlines()[-10:]
        r["tray_error"] = any("托盘" in x and ("失败" in x or "异常" in x)
                              for x in r["new_log"])
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
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
