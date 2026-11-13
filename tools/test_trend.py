# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""实测趋势验证判定（60 秒 / 12 次采样），验证「容量自然下降仍判 PASS」的修正。"""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))
import HonorBatteryGuard as hbg  # noqa: E402


def emit(kind, payload):
    if kind == "sample":
        s = payload["sample"]
        print(f"  {payload['index']:2d}/{payload['points']} {s['t']}  "
              f"电量={s['percent']}% 容量={s['capacity']} mWh ChargeRate={s['charge_rate']}",
              flush=True)


with hbg.Hwmi() as hw:
    result = hbg.trend_verify(hw, 60, 12, emit, threading.Event())
    print("\n=== RESULT ===")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"},
                     ensure_ascii=False, indent=2))
