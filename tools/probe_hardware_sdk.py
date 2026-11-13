# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
#!/usr/bin/env python3
"""Read-only probe of HONOR HardwareSdk.dll Battery::GetChargeThreshold.

No hardware writes are performed. Prints the raw StBatteryChangeThresholdLimit
buffer so its layout can be inferred, plus a few read-only battery getters.

Usage: python probe_hardware_sdk.py [dll_dir]
"""
import ctypes
import os
import platform
import sys
from pathlib import Path

DLL_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Program Files\HONOR\PCManager")
DLL_NAME = "HardwareSdk.dll"

CTOR = "??0Battery@@QEAA@XZ"
INIT = "?Init@Battery@@QEAAXXZ"
GET_TH = "?GetChargeThreshold@Battery@@QEAA_NAEAUStBatteryChangeThresholdLimit@@@Z"
GET_PCT = "?GetBatteryPercent@Battery@@QEAAKXZ"
GET_FULL = "?GetBatteryFullCapacity@Battery@@QEAAKXZ"
GET_DESIGN = "?GetBatteryDesignCapacity@Battery@@QEAAKXZ"
GET_REMAIN = "?GetBatteryRemainCapacity@Battery@@QEAAKXZ"
GET_VOLT = "?GetBatteryVoltage@Battery@@QEAAKXZ"
GET_CHARGE_RATE = "?GetChargeRate@Battery@@QEAAKXZ"
GET_DISCHARGE_RATE = "?GetDisChargeRate@Battery@@QEAAKXZ"


def hexdump(buf: bytes, width: int = 16) -> str:
    lines = []
    for i in range(0, len(buf), width):
        chunk = buf[i:i + width]
        hexs = " ".join(f"{b:02X}" for b in chunk)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"  {i:04X}  {hexs:<47}  {ascii_}")
    return "\n".join(lines)


def main() -> int:
    print(f"python: {platform.architecture()[0]} {platform.python_version()}")
    print(f"dll:    {DLL_DIR / DLL_NAME}")
    if not (DLL_DIR / DLL_NAME).exists():
        print("ERROR: DLL not found")
        return 1
    os.add_dll_directory(str(DLL_DIR))
    os.environ["PATH"] = str(DLL_DIR) + os.pathsep + os.environ.get("PATH", "")
    try:
        dll = ctypes.WinDLL(str(DLL_DIR / DLL_NAME))
    except OSError as e:
        print(f"ERROR LoadLibrary: {e}")
        return 2
    print("LoadLibrary: OK")

    for name in (CTOR, INIT, GET_TH, GET_PCT, GET_FULL, GET_DESIGN,
                 GET_REMAIN, GET_VOLT, GET_CHARGE_RATE, GET_DISCHARGE_RATE):
        print(f"  {name}: {'present' if hasattr(dll, name) else 'MISSING'}")
    if not all(hasattr(dll, n) for n in (CTOR, INIT, GET_TH)):
        return 3

    ctor = getattr(dll, CTOR)
    ctor.argtypes = [ctypes.c_void_p]
    ctor.restype = ctypes.c_void_p
    init = getattr(dll, INIT)
    init.argtypes = [ctypes.c_void_p]
    init.restype = None

    # Oversized buffer: Battery object layout is unknown; 8 KiB avoids overflow.
    obj = ctypes.create_string_buffer(8192)
    this = ctypes.addressof(obj)
    print(f"Battery object buffer: {len(obj)} bytes @ 0x{this:X}")
    try:
        ctor(ctypes.c_void_p(this))
        print("Battery::Battery(): OK")
        init(ctypes.c_void_p(this))
        print("Battery::Init(): OK")
    except Exception as e:  # noqa: BLE001
        print(f"ERROR during ctor/init: {e}")
        return 4

    for label, sym in (("GetBatteryPercent", GET_PCT),
                       ("GetBatteryFullCapacity", GET_FULL),
                       ("GetBatteryDesignCapacity", GET_DESIGN),
                       ("GetBatteryRemainCapacity", GET_REMAIN),
                       ("GetBatteryVoltage", GET_VOLT),
                       ("GetChargeRate", GET_CHARGE_RATE),
                       ("GetDisChargeRate", GET_DISCHARGE_RATE)):
        if not hasattr(dll, sym):
            continue
        fn = getattr(dll, sym)
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_uint32
        try:
            print(f"  {label} = {fn(ctypes.c_void_p(this))}")
        except Exception as e:  # noqa: BLE001
            print(f"  {label} ERROR: {e}")

    get_th = getattr(dll, GET_TH)
    get_th.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    get_th.restype = ctypes.c_bool
    out = ctypes.create_string_buffer(256)
    out[:] = b"\xCC" * 256
    try:
        ok = get_th(ctypes.c_void_p(this), ctypes.c_void_p(ctypes.addressof(out)))
        print(f"GetChargeThreshold returned: {ok}")
        print("raw StBatteryChangeThresholdLimit buffer (first 128 bytes):")
        print(hexdump(out.raw[:128]))
        vals = [int.from_bytes(out.raw[i:i + 4], "little", signed=False) for i in range(0, 64, 4)]
        print("u32[0..15]:", vals)
        print("u8[0..31]:", list(out.raw[:32]))
    except Exception as e:  # noqa: BLE001
        print(f"ERROR GetChargeThreshold: {e}")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
