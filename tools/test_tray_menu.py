# -*- coding: utf-8 -*-
"""逐项验证托盘右键菜单：三档带百分比、当前档位单选、随系统启动勾选同步。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import HonorBatteryGuard as H  # noqa: E402


def dump(menu) -> list[dict]:
    out = []
    for it in menu:
        if it is H.pystray.Menu.SEPARATOR if hasattr(H, "pystray") else False:
            out.append({"separator": True})
            continue
        try:
            text = it.text
            checked = it.checked
            radio = it.radio
            enabled = it.enabled
            out.append({"text": text, "checked": checked, "radio": radio, "enabled": enabled})
        except TypeError:
            out.append({"separator": True})
    return out


def find(items, prefix):
    return next((x for x in items if isinstance(x.get("text"), str)
                 and x["text"].startswith(prefix)), None)


def main():
    import pystray
    cfg_orig = H.read_config()
    auto_orig = H.autostart_state()["enabled"]
    r = {}
    try:
        # 状态：home 档 + 自启动关闭
        c = dict(cfg_orig, profile="home")
        H.write_config(c)
        H.disable_autostart()
        menu = H.build_tray_menu(lambda k, p=None: (lambda *_: None))
        items_a = dump(menu)
        r["items"] = items_a

        home = find(items_a, "家用模式")
        office = find(items_a, "办公模式")
        travel = find(items_a, "差旅模式")
        auto = find(items_a, "随系统启动")
        cur = find(items_a, "当前：")

        r["percentages"] = all(x and "%" in x["text"] for x in (home, office, travel))
        r["checked_home_when_home"] = bool(home and home["checked"] is True)
        r["unchecked_others"] = bool(office and travel
                                     and office["checked"] is False
                                     and travel["checked"] is False)
        r["radio_mode"] = bool(home and home["radio"] is True)
        r["auto_off"] = bool(auto and auto["checked"] is False and "未启用" in auto["text"])
        r["current_has_percent"] = bool(cur and "%" in cur["text"])

        # 状态变化：office 档 + 自启动开启 —— 同一菜单对象应读到新值
        H.write_config(dict(cfg_orig, profile="office"))
        H.enable_autostart("office", True)
        items_b = dump(menu)
        home_b = find(items_b, "家用模式")
        office_b = find(items_b, "办公模式")
        auto_b = find(items_b, "随系统启动")
        r["checked_office_after_change"] = bool(office_b and office_b["checked"] is True)
        r["unchecked_home_after_change"] = bool(home_b and home_b["checked"] is False)
        r["auto_on"] = bool(auto_b and auto_b["checked"] is True and "已启用" in auto_b["text"])

        keys = ["percentages", "checked_home_when_home", "unchecked_others", "radio_mode",
                "auto_off", "current_has_percent", "checked_office_after_change",
                "unchecked_home_after_change", "auto_on"]
        r["verdict"] = "PASS" if all(r[k] for k in keys) else "FAIL"
        r["checked_keys"] = keys
    finally:
        H.write_config(cfg_orig)
        if auto_orig:
            H.enable_autostart(cfg_orig.get("profile", "home"), True)
        else:
            H.disable_autostart()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
