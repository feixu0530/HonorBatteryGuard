# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
#!/usr/bin/env python3
"""Minimal PE export-table dumper (no external deps).

Usage: python pe_exports.py <file.dll|sys> [more files...]
"""
import struct
import sys
from pathlib import Path


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def rva_to_off(b, rva):
    pe = u32(b, 0x3C)
    nsec = u16(b, pe + 6)
    opt_size = u16(b, pe + 20)
    sec = pe + 24 + opt_size
    for i in range(nsec):
        s = sec + 40 * i
        vsize = u32(b, s + 8)
        vaddr = u32(b, s + 12)
        rawsize = u32(b, s + 16)
        rawptr = u32(b, s + 20)
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr)
    return None


def exports(path: Path):
    b = path.read_bytes()
    if b[:2] != b"MZ":
        return []
    pe = u32(b, 0x3C)
    if b[pe:pe + 4] != b"PE\0\0":
        return []
    opt = pe + 24
    magic = u16(b, opt)
    ddir = opt + (112 if magic == 0x20B else 96)
    exp_rva = u32(b, ddir)
    exp_size = u32(b, ddir + 4)
    if not exp_rva:
        return []
    off = rva_to_off(b, exp_rva)
    if off is None:
        return []
    nfun = u32(b, off + 20)
    nname = u32(b, off + 24)
    afun = rva_to_off(b, u32(b, off + 28))
    aname = rva_to_off(b, u32(b, off + 32))
    aord = rva_to_off(b, u32(b, off + 36))
    result = []
    for i in range(nname):
        nrva = u32(b, aname + 4 * i)
        noff = rva_to_off(b, nrva)
        end = b.find(b"\0", noff)
        name = b[noff:end].decode("ascii", "replace")
        ordinal = u16(b, aord + 2 * i)
        frva = u32(b, afun + 4 * ordinal) if afun is not None else 0
        fwd = ""
        if exp_rva <= frva < exp_rva + exp_size:
            fo = rva_to_off(b, frva)
            if fo:
                fwd = " -> " + b[fo:b.find(b"\0", fo)].decode("ascii", "replace")
        result.append((ordinal, hex(frva), name + fwd))
    return result


def main():
    for p in sys.argv[1:]:
        path = Path(p)
        print(f"=== {path.name} ===")
        try:
            ex = exports(path)
            print(f"# exported names: {len(ex)}")
            for ordinal, rva, name in ex:
                print(f"{ordinal:5d} {rva:>12} {name}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
