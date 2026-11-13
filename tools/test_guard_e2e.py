"""端到端实测托盘守护：模拟「阈值被改偏」，验证 exe 自动恢复。

步骤：
  1. 把 \SBTT 写成 40/71（仅偏离 1%，最大程度降低对电池的影响）；
  2. 启动 HonorBatteryGuard.exe --tray（守护首次校验在启动后 5 秒）；
  3. 等待 9 秒，检查日志是否记录自动恢复；
  4. 回读 EC 确认恢复为 40/70；
  5. 终止托盘进程树。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import HonorBatteryGuard as hbg  # noqa: E402

EXE = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.exe"
LOG = ROOT / "releases" / "HonorBatteryGuard" / "HonorBatteryGuard.log"


def read_ec():
    with hbg.Hwmi() as hw:
        th = hbg.get_thresholds(hw)
        cm = hbg.get_charge_mode(hw)
    return th.start, th.end, cm.mode


def main():
    result = {}
    result["before"] = read_ec()
    # 1) 制造一个可检测的偏差
    with hbg.Hwmi() as hw:
        hw.invoke(hbg.OP_SBTT, bytes([40, 71]))
    time.sleep(0.4)
    result["after_tamper"] = read_ec()

    log_size = LOG.stat().st_size if LOG.exists() else 0
    # 2) 启动托盘守护
    proc = psutil.Popen([str(EXE), "--tray"], cwd=str(EXE.parent))
    result["tray_pid"] = proc.pid
    try:
        time.sleep(9)
        result["tray_alive"] = proc.is_running()
        with LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(log_size)
            new_lines = f.read()
        result["new_log"] = new_lines.strip().splitlines()[-12:]
        result["recovered_in_log"] = any("自动恢复" in line for line in result["new_log"])
        result["tray_initialized"] = any("系统托盘已初始化" in line for line in result["new_log"])
        result["after_guard"] = read_ec()
        result["verdict"] = "PASS" if (result["recovered_in_log"]
                                       and result["after_guard"][:2] == (40, 70)) else "FAIL"
    finally:
        # 5) 终止进程树（onefile 会有 bootloader 子进程）
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
        result["tray_alive_after_cleanup"] = proc.is_running()

    # 收尾：无论如何把 EC 恢复到用户原本的 40/70
    with hbg.Hwmi() as hw:
        hbg.set_profile(hw, "home")
    result["final_ec"] = read_ec()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
