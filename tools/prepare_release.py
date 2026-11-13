# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""整理发布目录：归档 v1 PowerShell 版，移走测试运行时产物。"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REL = ROOT / "releases" / "HonorBatteryGuard"
ARCH = ROOT / "releases" / "archive" / "v1-powershell"
DEV = ROOT / "dev"
TMP = ROOT / "temp"
ARCH.mkdir(parents=True, exist_ok=True)
TMP.mkdir(exist_ok=True)

V1_FILES = ["HonorBatteryGuard.ps1", "启动工具.cmd", "诊断.cmd", "使用说明.md"]
RUNTIME = ["HonorBatteryGuard.json", "HonorBatteryGuard.log", "last-cli-output.json"]

for name in V1_FILES:
    src = REL / name
    if src.exists():
        shutil.move(str(src), str(ARCH / name))

for name in ["HonorBatteryGuard.ps1", "启动工具.cmd", "诊断.cmd"]:
    src = DEV / name
    if src.exists():
        shutil.move(str(src), str(ARCH / f"dev-{name}"))

for base, prefix in [(REL, "release"), (DEV, "dev")]:
    for name in RUNTIME:
        src = base / name
        if src.exists():
            dest = TMP / f"{prefix}-{name}"
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))

cache = DEV / "__pycache__"
if cache.exists():
    shutil.rmtree(str(cache), ignore_errors=True)

print("发布包:", sorted(p.name for p in REL.iterdir()))
print("dev   :", sorted(p.name for p in DEV.iterdir()))
print("归档  :", sorted(p.name for p in ARCH.iterdir()))
