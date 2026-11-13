# HonorBatteryGuard — 工具脚本（构建 / 测试 / 探针）
# Copyright (c) 2026 feixu0530
# SPDX-License-Identifier: MIT
# 基于 MIT 协议开源；复制/修改/分发须保留版权与许可声明（注明出处）。
"""只读探针：验证 Python/win32com 能否直接调用 root\\wmi OemWMIMethod.OemWMIfun。

仅下发 \\GBTT (0x1103) 读取命令，不写 EC。
"""
import sys
import pythoncom
import win32com.client
from win32com.client import VARIANT


def build(opcode, payload=b""):
    b = bytearray(64)
    b[0] = opcode & 0xFF
    b[1] = (opcode >> 8) & 0xFF
    for i, v in enumerate(payload):
        b[i + 2] = v
    return bytes(b)


def show(tag, fn):
    try:
        r = fn()
        print(f"{tag:38s} OK  type={type(r).__name__}  value={str(r)[:200]}")
    except Exception as e:
        print(f"{tag:38s} FAIL {type(e).__name__}: {e}")


def main():
    pythoncom.CoInitialize()
    b = build(0x1103)
    arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_UI1, list(b))

    # 方式 A: GetObject + 实例方法直接调用
    def a():
        wmi = win32com.client.GetObject(r"winmgmts:root\wmi")
        o = next(x for x in wmi.InstancesOf("OemWMIMethod") if "HWMI_0" in x.InstanceName)
        return o.OemWMIfun(list(b))
    show("A GetObject + o.OemWMIfun(list)", a)

    def a2():
        wmi = win32com.client.GetObject(r"winmgmts:root\wmi")
        o = next(x for x in wmi.InstancesOf("OemWMIMethod") if "HWMI_0" in x.InstanceName)
        return o.OemWMIfun(arr)
    show("A2 GetObject + o.OemWMIfun(VARIANT)", a2)

    # 方式 B: SWbemServices.ExecMethod，指定对象路径
    def b1():
        loc = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        svc = loc.ConnectServer(".", r"root\wmi")
        cls = svc.Get("OemWMIMethod")
        inp = cls.Methods_("OemWMIfun").InParameters.SpawnInstance_()
        inp.u8Input = arr
        path = r"OemWMIMethod.InstanceName='ACPI\\PNP0C14\\HWMI_0'"
        out = svc.ExecMethod(path, "OemWMIfun", inp)
        return (out.ReturnValue, list(out.u8Output)[:8], out.u32Resrved)
    show("B svc.ExecMethod(path, ..., VARIANT)", b1)

    # 方式 C: ExecMethod_ 返回对象的属性名枚举
    def c1():
        loc = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        svc = loc.ConnectServer(".", r"root\wmi")
        cls = svc.Get("OemWMIMethod")
        inp = cls.Methods_("OemWMIfun").InParameters.SpawnInstance_()
        inp.u8Input = arr
        o = next(x for x in svc.InstancesOf("OemWMIMethod") if "HWMI_0" in x.InstanceName)
        out = o.ExecMethod_("OemWMIfun", inp)
        names = [p.Name for p in out.Properties_]
        return (names, getattr(out, "ReturnValue", "?"), [int(x) & 0xFF for x in list(out.u8Output)[:8]])
    show("C ExecMethod_ + out.Properties_ (attr)", c1)

    pythoncom.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())
