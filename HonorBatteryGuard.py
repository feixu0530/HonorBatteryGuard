# -*- coding: utf-8 -*-
"""
HONOR 电池安全管理 · 独立控制工具（原生单文件 exe）

底层通道：root\\wmi / OemWMIMethod.OemWMIfun -> ACPI\\PNP0C14\\HWMI_0 -> EC 固件
命令（u8Input 必须 64 字节；前 2 字节为小端 u16 opcode）：
    \\GBTT 0x1103 读阈值 -> [status, start, end, ...]
    \\SBTT 0x1003 写阈值 <- [start, end]
    \\GBCM 0x1603 读模式 -> [status, mode, dact, start, end, ...]
    \\SBCM 0x1503 写模式 <- [mode, dact, start, end]   (dact 必须原样带回)

三档（荣耀官方定义，均为滞回区间）：
    home   40 -> 70  mode 1
    office 70 -> 90  mode 2
    travel 95 -> 100 mode 3

命令行：
    (无参数)                    启动图形界面
    --tray                      启动后直接隐藏到系统托盘（后台守护）
    --status                    输出 JSON 状态
    --apply <home|office|travel> 应用档位
    --silent                    与 --apply 同用，完全无窗口、写日志后退出
    --verify                    瞬时验证
    --selftest                  自检运行时依赖
    --enable-autostart / --disable-autostart
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

APP_NAME = "HonorBatteryGuard"
VERSION = "1.0.0"
GUARD_INTERVAL_SECONDS = 60   # 托盘守护校验 EC 阈值的间隔

PROFILES = {
    "home":   {"name": "家用模式", "mode": 1, "start": 40, "end": 70,  "hint": "长期插电使用，最保护电池"},
    "office": {"name": "办公模式", "mode": 2, "start": 70, "end": 90,  "hint": "经常插拔电源，兼顾续航"},
    "travel": {"name": "差旅模式", "mode": 3, "start": 95, "end": 100, "hint": "长时间离开电源，接近满充"},
}

OP_GBTT, OP_SBTT, OP_GBCM, OP_SBCM = 0x1103, 0x1003, 0x1603, 0x1503
CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- 路径与配置
def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """绿色版优先把配置写在 exe 同目录；只读目录时回退到 %APPDATA%。"""
    d = app_dir()
    try:
        probe = d / (".write-test-" + str(os.getpid()))
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return d
    except Exception:
        d = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
        d.mkdir(parents=True, exist_ok=True)
        return d


def resource_path(name: str) -> Path:
    """打包后资源在 _MEIPASS，源码运行时在 dev/ 目录。"""
    return Path(getattr(sys, "_MEIPASS", app_dir())) / name


CONFIG_PATH = data_dir() / "HonorBatteryGuard.json"
LOG_PATH = data_dir() / "HonorBatteryGuard.log"


def read_config() -> dict:
    try:
        c = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(c, dict):
            c.setdefault("profile", "home")
            c.setdefault("design_capacity", 0)
            c.setdefault("trend_minutes", 3)
            c.setdefault("tray_on_boot", True)
            # 旧版 hide_taskbar 平滑迁移为 hide_to_tray
            c.setdefault("hide_to_tray", bool(c.get("hide_taskbar", False)))
            return c
    except Exception:
        pass
    return {"profile": "home", "design_capacity": 0,
            "trend_minutes": 3, "tray_on_boot": True, "hide_to_tray": False}


def write_config(c: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def file_log(msg: str) -> None:
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 1024 * 1024:
            LOG_PATH.unlink()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_window_icon(root, ico: Path) -> bool:
    """用 WM_SETICON 显式设置大/小图标，保证标题栏左上角与任务栏按钮都是电池图标。

    PyInstaller 的 --icon 只写进 exe 资源（资源管理器里显示的图标），
    不会自动套用到运行中的 Tk 窗口；Tk 的 iconbitmap(default='') 反而会清空它。
    """
    if not ico.exists():
        return False
    try:
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT,
                                      ctypes.c_int, ctypes.c_int, wt.UINT]
        user32.LoadImageW.restype = wt.HICON
        user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.GetParent.argtypes = [wt.HWND]
        user32.GetParent.restype = wt.HWND

        hwnd = wt.HWND(int(root.winfo_id()))
        # Tk 顶层窗口本身就是任务栏按钮对应的窗口；只设置其父窗口（旧实现）会让顶层
        # 窗口仍显示 Tk 默认羽毛图标。这里两个 HWND 都设置，优先顶层。
        targets = [hwnd]
        try:
            parent = user32.GetParent(hwnd)
            if parent:
                targets.append(parent)
        except Exception:
            pass
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
        ok = False
        for h in targets:
            for size, kind in ((16, ICON_SMALL), (32, ICON_BIG)):
                hicon = user32.LoadImageW(None, str(ico), IMAGE_ICON, size, size, LR_LOADFROMFILE)
                if hicon:
                    user32.SendMessageW(h, WM_SETICON, kind, hicon)
                    ok = True
        return ok
    except Exception:
        return False


# ---------------------------------------------------------------- 单实例（防多开）
# 用 Windows 命名互斥量保证同一份 exe 同时只跑一个图形/托盘实例；
# CLI 模式（--status/--apply 等）不受影响，可随时并发调用。
_SINGLE_INSTANCE_MUTEX = None  # 进程级持有，程序运行期间不释放，退出时由内核自动回收


def _instance_mutex_name() -> str:
    """以 exe 完整路径为键生成互斥量名，不同副本互不干扰、同一份 exe 全局唯一。"""
    if getattr(sys, "frozen", False):
        key_src = os.path.abspath(sys.executable)
    else:
        try:
            key_src = os.path.abspath(__file__)
        except NameError:
            key_src = sys.executable
    digest = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    return "Local\\HonorBatteryGuard_" + digest


def _mark_instance_window(root) -> None:
    """在主窗口上打一个标记属性，供重复启动时定位并激活本实例。"""
    if not hasattr(ctypes, "windll"):
        return
    try:
        user32 = ctypes.windll.user32
        user32.SetPropW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR, ctypes.c_void_p]
        user32.SetPropW(ctypes.wintypes.HWND(int(root.winfo_id())),
                       "HonorBatteryGuardInstance", ctypes.c_void_p(1))
    except Exception:
        pass


def _find_existing_instance_hwnd() -> int:
    """枚举顶层窗口，返回已打标记实例的 hwnd（找不到返回 0）。"""
    if not hasattr(ctypes, "windll"):
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.GetPropW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR]
        user32.GetPropW.restype = ctypes.c_void_p
        PROP = "HonorBatteryGuardInstance"
        result = {"hwnd": 0}

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def cb(hwnd, lparam):
            if user32.GetPropW(hwnd, PROP):
                result["hwnd"] = int(hwnd)
                return False  # 停止枚举
            return True

        user32.EnumWindows(cb, 0)
        return result["hwnd"]
    except Exception:
        return 0


def _activate_existing_instance() -> None:
    """重复启动时，把已存在的实例提到前台；若它已收进托盘则提示用户。"""
    if not hasattr(ctypes, "windll"):
        return
    try:
        user32 = ctypes.windll.user32
        user32.IsIconic.argtypes = [ctypes.wintypes.HWND]
        user32.IsIconic.restype = ctypes.c_bool
        user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool
        user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
        user32.SetForegroundWindow.restype = ctypes.c_bool
        user32.MessageBoxW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR,
                                       ctypes.wintypes.LPCWSTR, ctypes.wintypes.UINT]
        hwnd = _find_existing_instance_hwnd()
        if not hwnd:
            return
        SW_RESTORE, SW_SHOW = 9, 5
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        elif not user32.IsWindowVisible(hwnd):
            # 已隐藏到系统托盘：外部无法直接 un-withdraw，提示用户并退出
            user32.MessageBoxW(
                0,
                "程序已在系统托盘运行。\n请点击任务栏右侧「^」展开托盘，右键图标打开主界面。",
                "HONOR 电池安全管理",
                0x40,
            )
            return
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def ensure_single_gui_instance() -> bool:
    """图形/托盘启动前调用。

    返回 True  → 本进程是首个实例，应继续启动（互斥量句柄由 _SINGLE_INSTANCE_MUTEX 持有至退出）。
    返回 False → 已有实例在运行（已尝试将其提到前台），本进程应直接退出。
    非 Windows 或互斥量创建失败时按「允许」处理（fail-open），避免互斥逻辑本身卡死程序。
    """
    if not hasattr(ctypes, "windll"):
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
        kernel32.GetLastError.restype = ctypes.wintypes.DWORD
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        h = kernel32.CreateMutexW(None, 0, _instance_mutex_name())
        if not h:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(h)
            _activate_existing_instance()
            return False
        global _SINGLE_INSTANCE_MUTEX
        _SINGLE_INSTANCE_MUTEX = h  # 持有至进程退出，内核自动释放
        return True
    except Exception:
        return True


# ---------------------------------------------------------------- WMI 会话
class Hwmi:
    """每个使用线程各自创建/销毁，避免 COM 跨线程封送问题。"""

    def __init__(self):
        import pythoncom
        import win32com.client
        self._pycom = pythoncom
        self._VARIANT = win32com.client.VARIANT
        self._VT_ARRAY_UI1 = pythoncom.VT_ARRAY | pythoncom.VT_UI1
        pythoncom.CoInitialize()
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        self.wmi = locator.ConnectServer(".", r"root\wmi")
        self.cim = locator.ConnectServer(".", r"root\cimv2")
        self._cls = self.wmi.Get("OemWMIMethod")
        instances = list(self.wmi.InstancesOf("OemWMIMethod"))
        if not instances:
            raise RuntimeError("未找到 OemWMIMethod 实例（ACPI\\PNP0C14\\HWMI 驱动未就绪）")
        self.target = next((i for i in instances if "HWMI_0" in i.InstanceName), instances[0])
        self.instance_name = self.target.InstanceName

    def close(self):
        """先显式释放 COM 引用再 CoUninitialize，避免 pywin32 退出时的 IUnknown 警告。"""
        try:
            import gc
            self.target = None
            self._cls = None
            self.wmi = None
            self.cim = None
            gc.collect()
            self._pycom.CoUninitialize()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def _build(opcode: int, payload: bytes = b"") -> bytes:
        b = bytearray(64)
        b[0] = opcode & 0xFF
        b[1] = (opcode >> 8) & 0xFF
        for i, v in enumerate(payload):
            if i + 2 < 64:
                b[i + 2] = v
        return bytes(b)

    def invoke(self, opcode: int, payload: bytes = b"") -> bytes:
        raw = self._build(opcode, payload)
        inp = self._cls.Methods_("OemWMIfun").InParameters.SpawnInstance_()
        inp.u8Input = self._VARIANT(self._VT_ARRAY_UI1, list(raw))
        out = self.target.ExecMethod_("OemWMIfun", inp)
        return bytes(int(x) & 0xFF for x in out.u8Output)

    @staticmethod
    def first(service, class_name: str):
        try:
            for o in service.InstancesOf(class_name):
                return o
        except Exception:
            return None
        return None

    @staticmethod
    def pget(obj, name, default=0):
        try:
            return getattr(obj, name)
        except Exception:
            return default


@dataclass
class Thresholds:
    status: int
    start: int
    end: int


@dataclass
class ChargeMode:
    status: int
    mode: int
    dact: int
    start: int
    end: int


@dataclass
class Battery:
    percent: int
    charging: bool
    discharging: bool
    online: bool
    charge_rate: int
    discharge_rate: int
    remaining: int
    full_capacity: int
    design_capacity: int
    health: float
    voltage: int
    cycle_count: int
    name: str


def get_thresholds(hw: Hwmi) -> Thresholds:
    o = hw.invoke(OP_GBTT)
    if len(o) < 3:
        raise RuntimeError("\\GBTT 返回数据过短")
    return Thresholds(o[0], o[1], o[2])


def get_charge_mode(hw: Hwmi) -> ChargeMode:
    o = hw.invoke(OP_GBCM)
    if len(o) < 5:
        raise RuntimeError("\\GBCM 返回数据过短")
    return ChargeMode(o[0], o[1], o[2], o[3], o[4])


def set_profile(hw: Hwmi, key: str) -> dict:
    """按管家顺序下发：\\SBCM -> \\SBTT -> 回读校验。dact 原样带回。"""
    p = PROFILES[key]
    before = get_charge_mode(hw)
    hw.invoke(OP_SBCM, bytes([p["mode"], before.dact, p["start"], p["end"]]))
    time.sleep(0.15)
    hw.invoke(OP_SBTT, bytes([p["start"], p["end"]]))
    time.sleep(0.25)
    th = get_thresholds(hw)
    cm = get_charge_mode(hw)
    return {
        "ok": th.start == p["start"] and th.end == p["end"],
        "requested": {"profile": key, **p},
        "readback": {"start": th.start, "end": th.end, "mode": cm.mode, "dact": cm.dact},
        "dact_before": before.dact,
    }


def enforce_profile(hw: Hwmi, key: str) -> dict:
    """静默守护用：阈值已一致则只读取、不重复写 EC。"""
    p = PROFILES[key]
    th, cm = get_thresholds(hw), get_charge_mode(hw)
    if th.start == p["start"] and th.end == p["end"] and cm.mode == p["mode"]:
        return {"ok": True, "skipped": True, "profile": key,
                "readback": {"start": th.start, "end": th.end, "mode": cm.mode}}
    r = set_profile(hw, key)
    r["skipped"] = False
    return r


def design_capacity_from_report() -> int:
    tmp = Path(os.environ.get("TEMP", ".")) / f"hbg-{os.getpid()}.xml"
    try:
        subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", str(tmp)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=30)
        if not tmp.exists():
            return 0
        root = ET.parse(tmp).getroot()
        for node in root.iter():
            if node.tag.split("}")[-1] == "Battery" and "DesignCapacity" in node.attrib:
                return int(float(node.attrib["DesignCapacity"]))
    except Exception:
        return 0
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    return 0


def battery_snapshot(hw: Hwmi, cfg: dict | None = None) -> Battery:
    cfg = cfg or read_config()
    bs = hw.first(hw.wmi, "BatteryStatus")
    full = hw.first(hw.wmi, "BatteryFullChargedCapacity")
    static = hw.first(hw.wmi, "BatteryStaticData")
    cycle = hw.first(hw.wmi, "BatteryCycleCount")
    w32 = hw.first(hw.cim, "Win32_Battery")
    g = Hwmi.pget

    design = int(g(static, "DesignedCapacity", 0) or 0) if static else 0
    if design <= 0 and w32:
        design = int(g(w32, "DesignCapacity", 0) or 0)
    if design <= 0:
        design = int(cfg.get("design_capacity", 0) or 0)
    if design <= 0:
        design = design_capacity_from_report()
        if design > 0:
            cfg["design_capacity"] = design
            write_config(cfg)

    full_cap = int(g(full, "FullChargedCapacity", 0) or 0) if full else 0
    remain = int(g(bs, "RemainingCapacity", 0) or 0) if bs else 0
    percent = int(g(w32, "EstimatedChargeRemaining", 0) or 0) if w32 else 0
    if percent <= 0 and full_cap > 0:
        percent = round(100.0 * remain / full_cap, 1)
    health = round(100.0 * full_cap / design, 1) if design > 0 and full_cap > 0 else 0.0

    return Battery(
        percent=percent,
        charging=bool(g(bs, "Charging", False)) if bs else False,
        discharging=bool(g(bs, "Discharging", False)) if bs else False,
        online=bool(g(bs, "PowerOnline", False)) if bs else False,
        charge_rate=int(g(bs, "ChargeRate", 0) or 0) if bs else 0,
        discharge_rate=int(g(bs, "DischargeRate", 0) or 0) if bs else 0,
        remaining=remain,
        full_capacity=full_cap,
        design_capacity=design,
        health=health,
        voltage=int(g(bs, "Voltage", 0) or 0) if bs else 0,
        cycle_count=int(g(cycle, "CycleCount", 0) or 0) if cycle else 0,
        name=str(g(w32, "Name", "") or "") if w32 else "",
    )


def full_state(hw: Hwmi) -> dict:
    th, cm, bat = get_thresholds(hw), get_charge_mode(hw), battery_snapshot(hw)
    key = next((k for k, p in PROFILES.items()
                if p["start"] == th.start and p["end"] == th.end), "custom")
    return {
        "time": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "profile": key,
        "profile_name": PROFILES.get(key, {}).get("name", "自定义"),
        "thresholds": asdict(th),
        "charge_mode": asdict(cm),
        "battery": asdict(bat),
        "autostart": autostart_state(),
        "is_admin": is_admin(),
        "instance": hw.instance_name,
    }


def verify_state(hw: Hwmi) -> dict:
    s = full_state(hw)
    t, b = s["thresholds"], s["battery"]
    reasons, verdict = [], "UNKNOWN"
    if not b["online"]:
        verdict = "SKIP"
        reasons.append("未接电源适配器：EC 充电限制只在 AC 在线时可观测")
    elif b["percent"] >= (t["end"] - 2) and b["charge_rate"] == 0:
        verdict = "PASS"
        reasons.append(f"已停充：电量 {b['percent']}% ≥ 上限 {t['end']}%-2%，ChargeRate=0")
    elif b["percent"] < t["start"] and b["charge_rate"] > 0:
        verdict = "PASS"
        reasons.append(f"正常充电：电量 {b['percent']}% < 起充线 {t['start']}%，ChargeRate={b['charge_rate']} mW")
    elif t["start"] <= b["percent"] < t["end"] and b["charge_rate"] > 0:
        verdict = "CHARGING"
        reasons.append(f"区间内充电中：{b['percent']}% 位于 [{t['start']}%, {t['end']}%]")
    elif b["percent"] > t["end"]:
        verdict = "ABOVE"
        reasons.append(f"电量 {b['percent']}% 高于上限 {t['end']}%：EC 不主动放电，需自然消耗回落")
    else:
        reasons.append("瞬时状态不足以判定，建议执行较长时间的趋势验证")
    reasons.append(f"EC 回读：起充 {t['start']}% / 停充 {t['end']}% / mode={s['charge_mode']['mode']} / dact={s['charge_mode']['dact']}")
    return {"verdict": verdict, "reasons": reasons, "state": s}


def trend_verify(hw: Hwmi, duration_seconds: int, points: int, emit, cancel: threading.Event) -> dict:
    """长时间趋势判定：停充时容量可以自然缓慢下降，但不应当持续上升。"""
    th = get_thresholds(hw)
    cfg = read_config()
    interval = duration_seconds / max(1, points - 1)
    samples = []
    for i in range(points):
        if cancel.is_set():
            return {"verdict": "CANCELLED", "reason": "用户中止", "samples": samples}
        b = battery_snapshot(hw, cfg)
        sample = {"t": f"{datetime.now():%H:%M:%S}", "percent": b.percent,
                  "capacity": b.remaining, "charge_rate": b.charge_rate, "online": b.online}
        samples.append(sample)
        emit("sample", {"index": i + 1, "points": points, "sample": sample})
        if i < points - 1:
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                if cancel.is_set():
                    break
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    if cancel.is_set():
        return {"verdict": "CANCELLED", "reason": "用户中止", "samples": samples}

    first, last = samples[0], samples[-1]
    delta = last["capacity"] - first["capacity"]
    zero = sum(1 for s in samples if s["charge_rate"] == 0)
    full_cap = battery_snapshot(hw, cfg).full_capacity
    tol = max(50, int(full_cap * 0.001))  # 允许仪表噪声，但不接受真实充电上升
    at_cap = last["percent"] >= (th.end - 2)

    if not last["online"]:
        verdict = "SKIP"
        reason = "采样期间未接电源适配器，无法判定"
    elif at_cap and last["charge_rate"] == 0 and delta <= tol:
        verdict = "PASS"
        reason = (f"电量 {last['percent']}% 已到上限 {th.end}%，{points} 次采样 / {duration_seconds}s "
                  f"内容量净变化 {delta} mWh（≤容差 {tol}），ChargeRate=0 占比 {zero}/{points}，充电确已被 EC 截断")
    elif delta > tol and last["charge_rate"] > 0:
        verdict = "CHARGING"
        reason = (f"容量持续上升 {delta} mWh 且 ChargeRate={last['charge_rate']} mW，"
                  f"仍在充电；若已超过上限 {th.end}% 则说明阈值未生效")
    elif last["percent"] > th.end:
        verdict = "ABOVE"
        reason = (f"电量 {last['percent']}% 高于上限 {th.end}%，EC 不主动放电；"
                  f"容量净变化 {delta} mWh、ChargeRate=0 占比 {zero}/{points}，未见继续充电")
    else:
        verdict = "UNKNOWN"
        reason = (f"容量净变化 {delta} mWh、ChargeRate=0 占比 {zero}/{points}，"
                  f"未到上限且状态不明确，建议延长采样或在插电静置后再测")
    return {"verdict": verdict, "reason": reason, "samples": samples,
            "delta": delta, "tolerance": tol, "zero_rate_count": zero,
            "duration": duration_seconds, "threshold_end": th.end}


# ---------------------------------------------------------------- 自启动（任务计划程序）
# 关键修正：本程序 exe 内嵌 requireAdministrator manifest，若用 HKCU\\Run 在登录时启动，
# 会因为无法在登录桌面弹出 UAC 而静默失败（表现就是「随系统启动没有作用」）。
# 改用「任务计划程序 · 触发器=登录时 · 最高权限运行(RL HIGHEST)」：管理员登录时
# 由任务计划程序以提权令牌直接拉起，不再弹 UAC，可常驻后台守护。
TASK_NAME = APP_NAME  # "HonorBatteryGuard"


def _ts():
    import win32com.client
    s = win32com.client.Dispatch("Schedule.Service")
    s.Connect()
    return s


def _current_user_str() -> str:
    try:
        import win32api, win32security
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                                               win32security.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        name, domain, _ = win32security.LookupAccountSid(None, sid)
        return f"{domain}\\{name}"
    except Exception:
        return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def autostart_state() -> dict:
    try:
        t = _ts().GetFolder("\\").GetTask(TASK_NAME)
        act = t.Definition.Actions.Item(1)
        return {"enabled": True, "type": "任务计划程序（登录时最高权限启动）",
                "value": f"{act.Path} {act.Arguments or ''}".strip()}
    except Exception:
        return {"enabled": False, "type": "未启用", "value": ""}


def enable_autostart(profile: str = "home", tray_on_boot: bool = True) -> dict:
    import win32com.client
    try:
        s = _ts()
        folder = s.GetFolder("\\")
        exe = str(Path(sys.executable).resolve())
        args = "--tray"
        try:
            folder.DeleteTask(TASK_NAME, 0)
        except Exception:
            pass
        td = s.NewTask(0)
        ri = td.RegistrationInfo
        ri.Author = APP_NAME
        ri.Description = "HONOR 电池安全管理 · 后台守护（登录时启动）"
        st = td.Settings
        st.Enabled = True
        st.StartWhenAvailable = True
        st.DisallowStartIfOnBatteries = False
        st.StopIfGoingOnBatteries = False
        try:
            st.ExecutionTimeLimit = ""  # 不限制运行时长
        except Exception:
            pass
        trig = td.Triggers.Create(9)  # TASK_TRIGGER_LOGON
        user = _current_user_str()
        trig.Id = "Logon"
        trig.UserId = user
        act = td.Actions.Create(0)  # TASK_ACTION_EXEC
        act.Path = exe
        act.Arguments = args
        pr = td.Principal
        pr.UserId = user
        pr.LogonType = 3   # TASK_LOGON_INTERACTIVE_TOKEN
        pr.RunLevel = 1    # TASK_RUNLEVEL_HIGHEST（登录时静默提权，不弹 UAC）
        # userId/password 传空字符串：交互式令牌登录不需要密码，避免 E_ACCESSDENIED
        folder.RegisterTaskDefinition(TASK_NAME, td, 6, "", "", 3)
        return {"ok": True,
                "detail": f"已创建登录时自启动任务（最高权限，无 UAC 弹窗）：{exe} {args}",
                "state": autostart_state()}
    except Exception as e:
        return {"ok": False, "detail": f"创建计划任务失败：{type(e).__name__}: {e}",
                "state": autostart_state()}


def disable_autostart() -> dict:
    try:
        folder = _ts().GetFolder("\\")
        try:
            folder.DeleteTask(TASK_NAME, 0)
            detail = "已关闭随系统启动"
        except Exception:
            detail = "自启动任务本来就不存在"
    except Exception as e:
        detail = f"删除失败：{e}"
    return {"ok": not autostart_state()["enabled"], "detail": detail,
            "state": autostart_state()}


def battery_report() -> Path:
    out = data_dir() / f"battery-report-{datetime.now():%Y%m%d-%H%M%S}.html"
    r = subprocess.run(["powercfg", "/batteryreport", "/output", str(out)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
    if not out.exists():
        raise RuntimeError(f"powercfg 未生成报告（退出码 {r.returncode}）")
    return out


# ---------------------------------------------------------------- 命令行
def cli_out(obj) -> None:
    """--noconsole 打包后 sys.stdout 为 None，因此同时落盘一份便于自检。"""
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    try:
        print(text)
    except Exception:
        pass
    try:
        (data_dir() / "last-cli-output.json").write_text(text, encoding="utf-8")
    except Exception:
        pass


def run_selftest() -> int:
    """一次性自检打包后的运行时依赖，结果写 last-cli-output.json。"""
    r = {"version": VERSION, "frozen": getattr(sys, "frozen", False),
         "executable": sys.executable, "data_dir": str(data_dir()),
         "admin": is_admin()}
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        r["tkinter"] = "OK"
    except Exception as e:
        r["tkinter"] = f"FAIL {type(e).__name__}: {e}"
    try:
        with Hwmi() as hw:
            th, cm, bat = get_thresholds(hw), get_charge_mode(hw), battery_snapshot(hw)
            r.update({"wmi": "OK", "instance": hw.instance_name,
                      "thresholds": asdict(th), "charge_mode": asdict(cm),
                      "battery_percent": bat.percent, "charge_rate": bat.charge_rate})
    except Exception as e:
        r["wmi"] = f"FAIL {type(e).__name__}: {e}"
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        png = resource_path("HonorBatteryGuard.png")
        ico = resource_path("HonorBatteryGuard.ico")
        r["tray"] = "OK"
        r["icon_png"] = str(png) if png.exists() else "MISSING"
        r["icon_ico"] = str(ico) if ico.exists() else "MISSING"
        r["icon_resource"] = "OK" if (png.exists() and ico.exists()) else "INCOMPLETE"
    except Exception as e:
        r["tray"] = f"FAIL {type(e).__name__}: {e}"
    r["autostart"] = autostart_state()
    r["overall"] = "PASS" if (r["admin"] and r["tkinter"] == "OK"
                              and r["wmi"] == "OK" and str(r["tray"]).startswith("OK")) else "FAIL"
    cli_out(r)
    return 0 if r["overall"] == "PASS" else 1


def run_cli(args) -> int:
    with Hwmi() as hw:
        if args.status:
            cli_out(full_state(hw))
            return 0
        if args.verify:
            cli_out(verify_state(hw))
            return 0
        if args.apply:
            cfg = read_config()
            r = enforce_profile(hw, args.apply) if args.silent else set_profile(hw, args.apply)
            if r.get("ok"):
                cfg["profile"] = args.apply
                write_config(cfg)
            if args.silent:
                file_log(f"静默守护 profile={args.apply} skipped={r.get('skipped')} "
                         f"readback={r.get('readback')} ok={r.get('ok')}")
            else:
                cli_out(r)
            return 0 if r.get("ok") else 2
        if args.enable_autostart:
            cfg = read_config()
            cli_out(enable_autostart(cfg.get("profile", "home"),
                                     bool(cfg.get("tray_on_boot", True))))
            return 0
        if args.disable_autostart:
            cli_out(disable_autostart())
            return 0
        cli_out(full_state(hw))
    return 0


# ---------------------------------------------------------------- 托盘菜单
def build_tray_menu(act):
    """构造托盘右键菜单。抽出为模块级函数，便于回归测试逐项检查文字/勾选位。

    所有会变化的状态都用 callable 描述符，状态变化后由 App._sync_tray_menu()
    调用 pystray 的 update_menu() 重建 Windows 原生 HMENU。
    """
    import pystray

    def current(item):
        try:
            p = PROFILES.get(read_config().get("profile", "home"), {})
            return f"当前：{p.get('name', '?')} {p.get('start')}%→{p.get('end')}%"
        except Exception:
            return "当前档位"

    def is_auto(item):
        try:
            return autostart_state()["enabled"]
        except Exception:
            return False

    def auto_text(item):
        try:
            return "随系统启动（已启用）" if autostart_state()["enabled"] else "随系统启动（未启用）"
        except Exception:
            return "随系统启动"

    def is_profile(item, key):
        try:
            return read_config().get("profile", "home") == key
        except Exception:
            return False

    def mode_items():
        out = []
        for key in ("home", "office", "travel"):
            p = PROFILES[key]
            out.append(pystray.MenuItem(
                f"{p['name']}    {p['start']}%  →  {p['end']}%",
                act("tray_apply", key),
                checked=(lambda item, k=key: is_profile(item, k)),
                radio=True))
        return out

    return pystray.Menu(
        pystray.MenuItem("打开主界面", act("show"), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(current, lambda *_: None, enabled=False),
        pystray.Menu.SEPARATOR,
        *mode_items(),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("立即校验并恢复阈值", act("tray_check")),
        pystray.MenuItem(auto_text, act("tray_autostart"), checked=is_auto),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", act("quit")),
    )


# ---------------------------------------------------------------- 图形界面
class App:
    WIDTH, HEIGHT = 860, 1004

    def __init__(self, start_in_tray: bool = False):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self._stop_evt = threading.Event()
        self._hide_notified = start_in_tray
        self.tray_icon = None
        self.cfg = read_config()

        # 必须在创建首个窗口之前设置 AppUserModelID，才能让任务栏按钮使用 exe 内嵌的
        # 电池图标（Tk 默认是蓝色羽毛）。设为 exe 自身路径，Windows 即按该路径取图标。
        if getattr(sys, "frozen", False):
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    str(Path(sys.executable).resolve()))
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.title(f"HONOR 电池安全管理 · 独立控制工具  v{VERSION}")
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.root.minsize(820, 820)
        # 显式设置窗口图标：标题栏左上角与任务栏按钮都取自这里。
        # 旧版 iconbitmap(default="") 会清空图标，导致显示 Tk 默认羽毛图标。
        ico = resource_path("HonorBatteryGuard.ico")
        png = resource_path("HonorBatteryGuard.png")
        self._win_icon_ok = False
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass
            try:
                self.root.update_idletasks()
                self._win_icon_ok = set_window_icon(self.root, ico)
            except Exception:
                self._win_icon_ok = False
        if png.exists():
            try:
                from PIL import Image, ImageTk
                im = Image.open(png).convert("RGBA").resize((32, 32), Image.LANCZOS)
                self._icon_photo = ImageTk.PhotoImage(im)
                self.root.iconphoto(True, self._icon_photo)
                self._win_icon_ok = True
            except Exception:
                pass

        # 单实例标记：在本窗口打属性，供重复启动时定位并激活（而非开第二个窗口）
        _mark_instance_window(self.root)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 9), foreground="#5a5a68")
        style.configure("H.TLabel", font=("Microsoft YaHei UI", 9))
        # 注意：ttk 的 vista 主题由系统原生绘制，会忽略 background 但 foreground 生效，
        # 若给 TButton 设白字就会变成「白底白字」。主按钮改用经典 tk.Button。
        style.configure("TButton", font=("Microsoft YaHei UI", 9))
        style.configure("TRadiobutton", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 9, "bold"))

        self._build_widgets()
        self.root.after(60, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._init_tray()
        self._start_guard()
        self.root.after(1500, self._check_tray_visible)
        if start_in_tray:
            if self.tray_icon:
                # 登录自启动：真正隐藏到托盘，不占用任务栏按钮
                self.root.after(300, self.root.withdraw)
                self.q.put(("notify", ("电池守护已启动",
                                       "已隐藏到系统托盘，右键图标可打开主界面；每 60 秒校验一次阈值")))
            else:
                # 托盘不可用时绝不能 withdraw，否则程序会变成完全不可见、无法操作
                file_log("托盘不可用，--tray 启动改为保持窗口可见")
                self.log("托盘图标不可用，已保持窗口可见（后台守护仍会运行）", "WARN")
        self.async_run(lambda hw, emit: emit("state", full_state(hw)), "正在读取 EC 与电池状态…")
        self._schedule_minute_refresh()

    # ------------------------------------------------------------ 界面构造
    def _build_widgets(self):
        tk, ttk = self.tk, self.ttk
        root = self.root
        main = ttk.Frame(root, padding=14)
        main.pack(fill="both", expand=True)

        # ---- 顶部：标题 + 管理员权限提示（贴标题旁，节省空间）+ 电池报告（右上，留间距）
        fh = ttk.Frame(main)
        fh.pack(fill="x")
        ttk.Label(fh, text="电池安全管理（不依赖荣耀电脑管家）", style="Title.TLabel").pack(side="left", anchor="w")
        self.lbl_admin = ttk.Label(fh, text="", style="H.TLabel")
        self.lbl_admin.pack(side="left", padx=(16, 0), anchor="w")
        self.btn_report = ttk.Button(fh, text="电池报告", command=self.on_report)
        self.btn_report.pack(side="right", padx=(16, 0), ipady=6, ipadx=12)
        ttk.Label(main, text=r"通道：root\wmi / OemWMIMethod.OemWMIfun → ACPI HWMI → EC 固件；"
                            "策略在固件内执行；后台守护每 60 秒校验阈值",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 10))

        # ---- 当前状态（彩色网格）
        g1 = ttk.LabelFrame(main, text=" 当前状态（每分钟自动刷新） ", padding=10)
        g1.pack(fill="x")
        self._build_status_panel(g1)

        # ---- 充电阈值档位
        g2 = ttk.LabelFrame(main, text=" 充电阈值档位（起充 → 停充） ", padding=10)
        g2.pack(fill="x", pady=(10, 0))
        self.profile_var = tk.StringVar(value=self.cfg.get("profile", "home"))
        for key in ("home", "office", "travel"):
            p = PROFILES[key]
            ttk.Radiobutton(g2, variable=self.profile_var, value=key,
                            text=f"  {p['name']}    {p['start']}%  →  {p['end']}%      · {p['hint']}").pack(anchor="w", pady=2)
        self.btn_apply = tk.Button(g2, text="应用并验证", command=self.on_apply,
                                   bg="#4f46e5", fg="#ffffff",
                                   activebackground="#4338ca", activeforeground="#ffffff",
                                   disabledforeground="#e0e7ff", relief="flat", bd=0,
                                   font=("Microsoft YaHei UI", 10, "bold"),
                                   cursor="hand2")
        self.btn_apply.pack(anchor="w", pady=(10, 2), ipadx=14, ipady=6)

        # ---- 趋势验证（含单一「验证」按钮）
        g3 = ttk.LabelFrame(main, text=" 趋势验证（长时间观察是否真的停充） ", padding=10)
        g3.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(g3)
        row.pack(fill="x")
        ttk.Label(row, text="采样时长：", style="H.TLabel").pack(side="left")
        self.trend_var = tk.StringVar(value=f"{int(self.cfg.get('trend_minutes', 3))} 分钟")
        self.cbo_trend = ttk.Combobox(row, state="readonly", width=12, textvariable=self.trend_var,
                                      values=["1 分钟", "3 分钟", "5 分钟", "10 分钟", "15 分钟"])
        self.cbo_trend.pack(side="left", padx=(0, 14))
        self.cbo_trend.bind("<<ComboboxSelected>>", self._on_trend_change)
        ttk.Label(row, text="12 次采样，均匀分布；停充时容量允许自然缓慢下降", style="Sub.TLabel").pack(side="left")
        self.btn_verify = ttk.Button(g3, text="验证", command=self.on_trend)
        self.btn_verify.pack(anchor="w", pady=(10, 2), ipady=5, ipadx=14)
        self.progress = ttk.Progressbar(g3, mode="determinate", maximum=12)
        self.progress.pack(fill="x", pady=(8, 0))

        # ---- 随系统启动
        g5 = ttk.Frame(main)
        g5.pack(fill="x", pady=(10, 0))
        self.btn_auto = ttk.Button(g5, text="随系统启动：查询中…", command=self.on_autostart)
        self.btn_auto.pack(side="left", ipady=5, ipadx=10)
        ttk.Label(g5, text="（登录时自动启动并常驻后台守护，每 60 秒校验并恢复阈值）",
                  style="Sub.TLabel").pack(side="left", padx=(10, 0))

        g5c = ttk.Frame(main)
        g5c.pack(fill="x", pady=(4, 0))
        self.var_hide_to_tray = tk.BooleanVar(value=bool(self.cfg.get("hide_to_tray", False)))
        ttk.Checkbutton(g5c, variable=self.var_hide_to_tray, command=self._on_hide_to_tray_change,
                        text="关闭窗口时隐藏到托盘").pack(side="left")
        ttk.Label(g5c, text="（不勾选时点击关闭将直接退出程序，后台守护停止）",
                  style="Sub.TLabel").pack(side="left", padx=(6, 0))

        # ---- 日志
        g6 = ttk.LabelFrame(main, text=" 运行日志 / 验证结果 ", padding=8)
        g6.pack(fill="both", expand=True, pady=(12, 0))
        self.txt_log = tk.Text(g6, wrap="word", background="#f8f8fa", relief="solid",
                               borderwidth=1, font=("Consolas", 9), foreground="#1b1b22")
        sb2 = ttk.Scrollbar(g6, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.txt_log.pack(side="left", fill="both", expand=True)
        self.txt_log.configure(state="disabled")

        self._refresh_admin_label()
        self.log(f"已启动 v{VERSION}；配置文件 {CONFIG_PATH}")

    def _on_trend_change(self, *_):
        try:
            minutes = int(str(self.trend_var.get()).split()[0])
            self.cfg["trend_minutes"] = minutes
            write_config(self.cfg)
            self.log(f"趋势验证时长设为 {minutes} 分钟（12 次采样）")
        except Exception:
            pass

    def _on_hide_to_tray_change(self, *_):
        v = bool(self.var_hide_to_tray.get())
        self.cfg["hide_to_tray"] = v
        write_config(self.cfg)
        if v and not self.tray_icon:
            self.log("托盘图标不可用，已自动改回「关闭窗口直接退出」", "WARN")
            self.var_hide_to_tray.set(False)
            self.cfg["hide_to_tray"] = False
            write_config(self.cfg)
        else:
            self.log(f"关闭窗口行为：{'隐藏到托盘并继续后台守护' if v else '直接退出程序（后台守护停止）'}")
            if v:
                self.log("提示：Windows 11 可能把托盘图标折叠到「^ 显示隐藏的图标」，"
                         "可在 设置→个性化→任务栏→其他系统托盘图标 中打开", "WARN")

    def _refresh_admin_label(self):
        if is_admin():
            self.lbl_admin.configure(text="● 管理员权限（可写 EC）", foreground="#16794a")
        else:
            self.lbl_admin.configure(text="● 非管理员：操作会被拒绝，请右键「以管理员身份运行」",
                                     foreground="#b42318")

    # ------------------------------------------------------------ 当前状态面板（彩色网格）
    def _build_status_panel(self, parent):
        tk, ttk = self.tk, self.ttk
        # 5 个重点指标的固定「标识色」，便于一眼定位
        self._metric_colors = {
            "percent": "#1d4ed8",   # 蓝
            "online": "#0f766e",    # 青
            "status": "#7c3aed",    # 紫
            "health": "#b45309",    # 琥珀
            "threshold": "#4338ca", # 靛
        }
        f = ttk.Frame(parent)
        f.pack(fill="x")
        self._status = {}
        # 紧凑双列布局：[标签][值][标签][值]，5 个指标压成 3 行，省出空间给日志区
        layout = [
            ("percent", "当前电量", "online", "电源"),
            ("status", "状态", "health", "电池健康度"),
            ("threshold", "EC 充电阈值", None, None),
        ]

        def add_cell(r, c, key, name, val_width, span=1):
            l = ttk.Label(f, text=name, font=("Microsoft YaHei UI", 9, "bold"),
                          foreground=self._metric_colors[key], width=10, anchor="w")
            l.grid(row=r, column=c, sticky="w", padx=(0, 6), pady=1)
            v = ttk.Label(f, text="…", font=("Microsoft YaHei UI", 10, "bold"),
                          width=val_width, anchor="w")
            v.grid(row=r, column=c + 1, sticky="w", padx=(0, 0), pady=1, columnspan=span)
            self._status[key] = v

        for r, (k1, n1, k2, n2) in enumerate(layout):
            if k2 is not None:
                add_cell(r, 0, k1, n1, 16)
                add_cell(r, 2, k2, n2, 18)
            else:
                # 第三行：EC 充电阈值 跨列显示（值较长）
                add_cell(r, 0, k1, n1, 44, span=3)

        det = tk.Text(parent, height=3, wrap="none", background="#f3f4f6", relief="flat",
                      borderwidth=0, font=("Consolas", 9), foreground="#374151")
        det.insert("1.0", "读取中…")
        det.configure(state="disabled")
        det.pack(fill="x", pady=(4, 0))
        self._status_detail = det

    def _render_state(self, s):
        b, t, c = s["battery"], s["thresholds"], s["charge_mode"]
        ac = "已接通" if b["online"] else "未接通"
        if b["charge_rate"] > 0:
            chg = "充电中"
        elif b["discharge_rate"] > 0:
            chg = "放电中"
        else:
            chg = "未充电（保持）"
        is_profile = s["profile"] in PROFILES

        # 数值按状态动态配色
        pc = "#15803d" if b["percent"] >= (t["end"] - 2) else ("#c2410c" if b["percent"] < t["start"] else "#1d4ed8")
        oc = "#15803d" if b["online"] else "#6b7280"
        sc = "#15803d" if chg == "充电中" else ("#c2410c" if chg == "放电中" else "#6b7280")
        h = b["health"]
        hc = "#15803d" if h >= 95 else ("#b45309" if h >= 85 else "#b91c1c")
        if is_profile:
            tc, tval = "#15803d", f"{t['start']}% → {t['end']}%   [{s['profile_name']}]"
        else:
            tc, tval = "#b91c1c", f"{t['start']}% → {t['end']}%   [自定义/不一致]"

        self._status["percent"].configure(text=f"{b['percent']} %", foreground=pc)
        self._status["online"].configure(text=ac, foreground=oc)
        self._status["status"].configure(text=chg, foreground=sc)
        self._status["health"].configure(text=f"{b['health']} %", foreground=hc)
        self._status["threshold"].configure(text=tval, foreground=tc)

        detail = (
            f"充电功率 {b['charge_rate']} mW   放电 {b['discharge_rate']} mW   电压 {b['voltage']} mV\n"
            f"剩余 {b['remaining']} mWh   满充 {b['full_capacity']} mWh   设计 {b['design_capacity']} mWh\n"
            f"循环 {b['cycle_count']}   电池 {b['name']}\n"
            f"EC mode={c['mode']}  dact={c['dact']}  GBCM status={c['status']}   "
            f"管理员={s['is_admin']}   自启动={('已启用' if s['autostart']['enabled'] else '未启用')}\n"
            f"WMI 实例 {s['instance']}   更新 {s['time']}"
        )
        self._status_detail.configure(state="normal")
        self._status_detail.delete("1.0", "end")
        self._status_detail.insert("1.0", detail)
        self._status_detail.configure(state="disabled")

        if is_profile:
            self.profile_var.set(s["profile"])
        self.btn_auto.configure(text=("随系统启动：已启用（点击关闭）" if s["autostart"]["enabled"]
                                      else "随系统启动：未启用（点击开启）"))
        self._sync_tray_menu()

    def log(self, msg, level="INFO"):
        line = f"[{datetime.now():%H:%M:%S}] {level} {msg}"
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")
        file_log(f"{level} {msg}")

    # ------------------------------------------------------------ 异步任务
    def async_run(self, fn, note="", done=None, allow_cancel=False):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self._set_buttons(False)
        if note:
            self.log(note)
        if allow_cancel:
            self.btn_verify.configure(text="停止验证", command=self._stop_trend)
            self.btn_verify.configure(state="normal")
        self.progress.configure(value=0)

        def emit(kind, payload):
            self.q.put((kind, payload))

        def worker():
            hw = None
            try:
                hw = Hwmi()
                result = fn(hw, emit)
                self.q.put(("done", result))
            except Exception as e:
                self.q.put(("error", f"{type(e).__name__}: {e}"))
                file_log(traceback.format_exc())
            finally:
                if hw is not None:
                    hw.close()
                self.q.put(("finished", {"done": done, "cancellable": allow_cancel}))

        threading.Thread(target=worker, daemon=True).start()

    def _set_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for b in (self.btn_apply, self.btn_verify, self.btn_report, self.btn_auto):
            b.configure(state=state)

    def _stop_trend(self):
        self.cancel.set()
        self.log("已请求停止趋势验证…")
        self.btn_verify.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(str(payload))
                elif kind == "error":
                    msg = str(payload)
                    self.log(msg, "ERROR")
                    if "拒绝访问" in msg or "Access" in msg or "-214" in msg:
                        self.log("若提示权限不足，请右键 exe「以管理员身份运行」", "WARN")
                elif kind == "state":
                    self._render_state(payload)
                elif kind == "show":
                    self._show_window()
                elif kind == "notify":
                    self._tray_notify(payload)
                elif kind == "tray_apply":
                    self.profile_var.set(payload)
                    self.on_apply()
                elif kind == "tray_check":
                    self.on_guard_check()
                elif kind == "tray_autostart":
                    self.on_autostart()
                elif kind == "quit":
                    self._do_quit()
                    return
                elif kind == "verdict":
                    for line in payload:
                        self.log(line)
                elif kind == "sample":
                    i, n = payload["index"], payload["points"]
                    s = payload["sample"]
                    self.progress.configure(maximum=n, value=i)
                    self.log(f"  {i:2d}/{n}  {s['t']}  电量={s['percent']}%  "
                             f"容量={s['capacity']} mWh  ChargeRate={s['charge_rate']}")
                elif kind == "done":
                    self._handle_done(payload)
                elif kind == "finished":
                    self.busy = False
                    self._set_buttons(True)
                    self.btn_verify.configure(text="验证", command=self.on_trend)
                    cb = payload.get("done")
                    if cb:
                        cb()
        except queue.Empty:
            pass
        try:
            self.root.after(60, self._poll)
        except Exception:
            pass  # 窗口已销毁

    def _handle_done(self, r):
        if not isinstance(r, dict):
            return
        if "verdict" in r:
            self.log(f"结论 [{r['verdict']}] {r.get('reason', '')}")
            for x in r.get("reasons", []):
                self.log(f"  {x}")
            if "delta" in r:
                self.log(f"  净变化 {r['delta']} mWh（容差 {r['tolerance']}），"
                         f"ChargeRate=0 采样 {r['zero_rate_count']}/{len(r.get('samples', []))}，"
                         f"时长 {r['duration']}s")
        elif "detail" in r:
            self.log(str(r["detail"]))
        elif "ok" in r:
            if r.get("ok"):
                if r.get("skipped"):
                    self.log("阈值已一致，无需重复写 EC")
                else:
                    rb = r.get("readback", {})
                    self.log(f"写入成功：EC 回读 {rb.get('start')}% → {rb.get('end')}% "
                             f"(mode={rb.get('mode')}, dact={rb.get('dact')})")
            else:
                self.log("写入失败或回读不一致，未改动配置", "ERROR")
        elif "path" in r:
            self.log(f"电池报告已生成：{r['path']}")

    # ------------------------------------------------------------ 系统托盘与后台守护
    def _tray_image(self):
        from PIL import Image, ImageDraw
        p = Path(getattr(sys, "_MEIPASS", app_dir())) / "HonorBatteryGuard.png"
        try:
            if p.exists():
                return Image.open(p).convert("RGBA").resize((64, 64), Image.LANCZOS)
        except Exception:
            pass
        img = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((14, 12, 50, 60), radius=4, outline=(20, 20, 24, 255), width=4)
        d.rectangle((24, 6, 40, 14), fill=(20, 20, 24, 255))
        d.rectangle((18, 34, 46, 56), fill=(4, 207, 0, 255))
        return img

    def _act(self, kind, payload=None):
        def cb(*_):
            self.q.put((kind, payload))
        return cb

    def _init_tray(self):
        try:
            import pystray
            menu = build_tray_menu(self._act)
            self.tray_icon = pystray.Icon(APP_NAME, self._tray_image(),
                                          "HONOR 电池安全管理", menu)
            threading.Thread(target=self._run_tray, daemon=True).start()
            file_log("系统托盘已初始化")
        except Exception as e:
            self.tray_icon = None
            file_log(f"系统托盘初始化失败：{e}\n{traceback.format_exc()}")
            self.log(f"系统托盘不可用：{e}（关闭窗口将直接退出）", "WARN")

    def _run_tray(self):
        try:
            if self.tray_icon:
                self.tray_icon.run()
        except Exception as e:
            file_log(f"托盘线程异常：{e}")

    def _sync_tray_menu(self):
        """档位 / 自启动状态变化后必须调用：pystray 的 checked、text 是惰性描述符，
        Windows 后端的 HMENU 只在 update_menu() 时重建，不刷新会一直显示旧勾选。"""
        try:
            if self.tray_icon:
                self.tray_icon.update_menu()
        except Exception as e:
            file_log(f"托盘菜单刷新失败：{type(e).__name__}: {e}")

    def _tray_notify(self, payload):
        if not self.tray_icon:
            return
        try:
            if isinstance(payload, (tuple, list)):
                title, msg = payload[0], payload[1]
            else:
                title, msg = "电池守护", str(payload)
            self.tray_icon.notify(str(msg), str(title))
        except Exception:
            pass

    def _show_window(self):
        try:
            self.root.deiconify()
            try:
                self.root.state("normal")
            except Exception:
                pass
            self.root.lift()
            self.root.focus_force()
            self.on_refresh()
        except Exception:
            pass

    def _check_tray_visible(self):
        if not self.tray_icon:
            return
        try:
            file_log(f"托盘图标 visible={self.tray_icon.visible}；"
                     "Windows 11 可能把它折叠到「^ 显示隐藏的图标」")
        except Exception:
            pass

    def on_close(self):
        """二选一：勾选则隐藏到托盘继续守护；不勾选则真正退出程序。"""
        if bool(self.var_hide_to_tray.get()) and bool(self.tray_icon):
            self.root.withdraw()
            action = "窗口已隐藏到托盘，后台守护继续"
            if not self._hide_notified:
                self._hide_notified = True
                self._tray_notify(("电池守护仍在运行",
                                   "已隐藏到托盘；右键托盘图标可打开主界面或退出"))
            file_log(action)
            self.log(action)
        else:
            file_log("用户关闭窗口，退出程序（后台守护停止）")
            self._do_quit()

    def _do_quit(self):
        self._stop_evt.set()
        self.cancel.set()
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass
        file_log("用户从托盘退出")
        self.root.destroy()

    def _start_guard(self):
        """后台守护：定时读取 EC，若阈值被管家/固件重置则自动重发。"""
        def loop():
            first = True
            while not self._stop_evt.wait(5 if first else GUARD_INTERVAL_SECONDS):
                first = False
                try:
                    with Hwmi() as hw:
                        cfg = read_config()
                        key = cfg.get("profile", "home")
                        r = enforce_profile(hw, key)
                        if r.get("ok") and not r.get("skipped"):
                            p = PROFILES[key]
                            msg = (f"守护：检测到充电阈值被重置，已自动恢复 "
                                   f"{p['start']}%→{p['end']}%（{p['name']}）")
                            file_log(msg)
                            self.q.put(("log", msg))
                            self.q.put(("notify", ("阈值已自动恢复", msg)))
                except Exception as e:
                    file_log(f"守护检查异常：{type(e).__name__}: {e}")
        threading.Thread(target=loop, daemon=True).start()

    def on_guard_check(self):
        def job(hw, emit):
            cfg = read_config()
            key = cfg.get("profile", "home")
            r = enforce_profile(hw, key)
            emit("done", r)
            note = "阈值一致，无需重写 EC" if r.get("skipped") else "已重新下发阈值"
            emit("verdict", [f"守护校验：{note}；回读 {r.get('readback')}"])
            emit("state", full_state(hw))
            return None
        self.async_run(job, "正在校验并恢复阈值…")

    # ------------------------------------------------------------ 按钮事件
    def on_refresh(self, silent: bool = False):
        note = "" if silent else "刷新状态…"
        self.async_run(lambda hw, emit: emit("state", full_state(hw)), note)

    def on_apply(self):
        key = self.profile_var.get()
        p = PROFILES[key]
        self.log(f"正在应用 {p['name']}（{p['start']}% → {p['end']}%，mode={p['mode']}）…")

        def job(hw, emit):
            r = set_profile(hw, key)
            emit("done", r)
            if r["ok"]:
                self.cfg["profile"] = key
                write_config(self.cfg)
                v = verify_state(hw)
                emit("verdict", [f"验证 [{v['verdict']}] " + "；".join(v["reasons"])])
            emit("state", full_state(hw))
            return None
        self.async_run(job)

    # ------------------------------------------------------------ 每分钟整点自动刷新
    def _auto_refresh(self):
        """静默刷新：独立线程读 EC 并回传状态，刻意绕过 async_run 的 busy 守卫，
        避免在趋势验证 / 电池报告等耗时操作进行中把每分钟刷新无声吞掉。"""
        def worker():
            try:
                with Hwmi() as hw:
                    self.q.put(("state", full_state(hw)))
            except Exception as e:
                self.q.put(("error", f"自动刷新失败：{type(e).__name__}: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _schedule_minute_refresh(self):
        """对齐到整分钟刷新（按用户要求「按整点时间」），首拍对齐到下一分钟起点。"""
        now = datetime.now()
        delay = int((60 - now.second - now.microsecond / 1_000_000) * 1000)
        if delay < 300:
            delay += 60_000
        try:
            self.root.after(delay, self._minute_tick)
        except Exception:
            pass

    def _minute_tick(self):
        if self._stop_evt.is_set():
            return
        try:
            self._auto_refresh()
        except Exception:
            pass
        self._schedule_minute_refresh()

    def on_trend(self):
        try:
            minutes = int(str(self.trend_var.get()).split()[0])
        except Exception:
            minutes = 3
        seconds, points = minutes * 60, 12
        self.log(f"开始趋势验证：{minutes} 分钟 / {points} 次采样 / 约 {seconds / (points - 1):.0f} 秒间隔…")

        def job(hw, emit):
            r = trend_verify(hw, seconds, points, emit, self.cancel)
            emit("done", r)
            emit("state", full_state(hw))
            return None
        self.async_run(job, allow_cancel=True)

    def on_report(self):
        def job(hw, emit):
            path = battery_report()
            emit("done", {"path": str(path)})
            try:
                os.startfile(str(path))  # noqa: S606
            except Exception:
                pass
            return None
        self.async_run(job, "正在生成 Windows 电池报告…")

    def on_autostart(self):
        def job(hw, emit):
            a = autostart_state()
            if a["enabled"]:
                r = disable_autostart()
            else:
                # 已实测：关闭管家会把 EC 清零，登录时一次性重发不够，必须常驻守护。
                # 因此自启动统一固定为 --tray（后台守护），不再提供第二种模式。
                self.cfg["tray_on_boot"] = True
                write_config(self.cfg)
                r = enable_autostart(self.cfg.get("profile", "home"), True)
            emit("done", r)
            emit("state", full_state(hw))
            return None
        self.async_run(job, "正在切换随系统启动…")

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- 入口
def main() -> int:
    ap = argparse.ArgumentParser(description="HONOR 电池安全管理独立控制工具")
    ap.add_argument("--tray", action="store_true", help="启动后直接隐藏到系统托盘（后台守护）")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", choices=list(PROFILES))
    ap.add_argument("--silent", action="store_true", help="与 --apply 同用，无窗口静默执行后退出")
    ap.add_argument("--enable-autostart", action="store_true")
    ap.add_argument("--disable-autostart", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="自检运行时依赖，结果写入 last-cli-output.json")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()
    if args.silent and not args.apply:
        args.apply = read_config().get("profile", "home")
    cli = any([args.status, args.verify, args.apply, args.enable_autostart, args.disable_autostart])
    if cli:
        try:
            return run_cli(args)
        except Exception as e:
            msg = f"CLI ERROR {type(e).__name__}: {e}"
            file_log(msg + "\n" + traceback.format_exc())
            if not args.silent:
                cli_out({"error": msg})
            return 1

    # 单实例检查：仅图形/托盘模式生效，CLI 模式不受影响；重复启动会激活已有实例并退出。
    if not ensure_single_gui_instance():
        return 0

    if not is_admin():
        # 打包版带 requireAdministrator manifest，正常不会走到这里；源码调试时给出明确提示
        ctypes.windll.user32.MessageBoxW(
            0, "本工具需要管理员权限才能调用 ACPI-WMI 写入 EC。\n请右键「以管理员身份运行」。",
            "HONOR 电池安全管理", 0x30)
    try:
        App(start_in_tray=args.tray).run()
    except Exception:
        file_log("GUI FATAL:\n" + traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
