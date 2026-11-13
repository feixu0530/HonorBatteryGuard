# 本项目自建工具脚本

- **探测类**（`probe_*` / `strings_extract` / `pe_exports`）为只读，不改系统配置。
- **实测类**（`test_*`）为受控验证，会短暂改写 EC 阈值并立即恢复，仅用于开发复测。
- **构建类**（`svg_to_ico.py` / `prepare_release.py` / `.buildenv/`）生成或移动项目内文件。
- 需要 `win32com` / `tkinter` / `Pillow` 的脚本请用 `tools/.buildenv/Scripts/python.exe`，
  不要直接用 WorkBuddy 内嵌的 Python 3.13（不带 tkinter）。

构建 exe 的完整命令见 `reference/03-v2构建与踩坑.md`。

| 脚本 | 用途 | 用法 |
|---|---|---|
| `strings_extract.py` | 从 PE/二进制提取 ASCII 与 UTF-16LE 字符串（带文件偏移） | `python strings_extract.py <in.dll\|sys> <out.txt> [min_ascii] [min_utf16]` |
| `pe_exports.py` | 无第三方依赖的 PE 导出表解析器 | `python pe_exports.py <file.dll> [more...]` |
| `probe_hardware_sdk.py` | **只读**加载 `HardwareSdk.dll`，构造 `Battery` 对象并调用电池 getter / `GetChargeThreshold` | `python probe_hardware_sdk.py [dll_dir]` |
| `probe_devices.py` | **只读**测试 `\\.\HHAL` / `\\.\OS2SOC` / `\\.\HNOs2EcX64` 能否打开（不发任何 IOCTL），并报告管理员状态 | `python probe_devices.py` |
| `probe_wmi_com.py` | **只读**探测 `OemWMIMethod.OemWMIfun` 的多种 COM 调用形式与参数类型 | `.buildenv\Scripts\python.exe probe_wmi_com.py` |
| `probe_tray.py` | 拦截 `Shell_NotifyIcon` 返回值，判断托盘图标是否真的注册成功 | `.buildenv\Scripts\python.exe probe_tray.py` |
| `check_tray_icon.py` | 启动 `--tray` 并截取屏幕右下角通知区域到 `temp/tray_area.png` | `.buildenv\Scripts\python.exe check_tray_icon.py` |
| `test_tray_hide.py` | v2.1 遗留：发 `WM_CLOSE` 验证最小化到任务栏（v2.2 语义已变，见 `test_v22_behaviors.py`） | `.buildenv\Scripts\python.exe test_tray_hide.py` |
| `test_v22_behaviors.py` | **v2.2 回归**：不勾选=退出、勾选=隐藏到托盘、菜单动态勾选；自动恢复配置与自启动 | `.buildenv\Scripts\python.exe test_v22_behaviors.py` |
| `test_tray_menu.py` | 逐项检查托盘菜单：三档百分比、当前档位 radio、自启动文字/勾选同步（9 项断言） | `.buildenv\Scripts\python.exe test_tray_menu.py` |
| `verify_gui_v22.py` | 启动 exe 截窗口图/标题栏/托盘区，核对图标与按钮文字 | `.buildenv\Scripts\python.exe verify_gui_v22.py` |
| `extract_exe_icon.py` | 用 `ExtractIconEx` 导出 exe 内嵌图标为 PNG，核对 `--icon` 是否生效 | `.buildenv\Scripts\python.exe extract_exe_icon.py <exe> <out.png>` |
| `test_guard_e2e.py` | 人为把 EC 阈值改成 40/71，验证托盘守护自动恢复 40/70 | `.buildenv\Scripts\python.exe test_guard_e2e.py` |
| `test_trend.py` | 60 秒 / 12 次采样，实测趋势判定修正 | `.buildenv\Scripts\python.exe test_trend.py` |
| `svg_to_ico.py` | 把 `reference/电池.svg` 渲染成 `dev/HonorBatteryGuard.ico/.png` | `.buildenv\Scripts\python.exe svg_to_ico.py` |
| `make_icon.py` | 早期 PIL 手绘图标（v2 已改用 `svg_to_ico.py`，保留作回退参考） | `python make_icon.py` |
| `prepare_release.py` | 归档 v1 PowerShell 版、清理发布包运行时产物 | `.buildenv\Scripts\python.exe prepare_release.py` |

## 关键探测结论（2026-11-13）

```
probe_hardware_sdk.py
  LoadLibrary OK；Battery 构造/Init OK
  GetBatteryPercent=70  FullCapacity=89961  DesignCapacity=92041
  Voltage=16279  ChargeRate=0  DisChargeRate=0
  GetChargeThreshold -> False，输出缓冲未被写入（HHAL 被管家独占）

probe_devices.py
  IsUserAnAdmin = 1
  \\.\HHAL          FAILED  GetLastError=5（拒绝访问 / Exclusive 独占）
  \\.\OS2SOC         OK
  \\.\HNOs2EcX64     OK
  \\.\HwOs2EcX64     FAILED  GetLastError=5

pe_exports.py HardwareSdk.dll
  ?GetChargeThreshold@Battery@@QEAA_NAEAUStBatteryChangeThresholdLimit@@@Z
  ?SetChargeThreshold@Battery@@QEAA_NAEBUStBatteryChangeThresholdLimit@@@Z
pe_exports.py HardwareHal.dll
  HalInit / HalOpenDevice / HalCloseDevice / HalRead / HalWrite /
  HalControl / HalQueryInformation / HalSetInformation / HalSetCallback
pe_exports.py HnWMISDK.dll
  HnWMI::GetWMIData(string, initializer_list<uint8_t>, string&)
  字符串：ACPI\PNP0C14\HWMI_0 / OemWMIMethod / OemWMIfun
```

## 中间产物

`temp/strings_*.txt`、`temp/exports*.txt` 为探测输出，可随时清空；
`temp/` 不纳入长期保留内容。

## 环境注意

- 本机开发沙箱禁止 `reg.exe`、`csc.exe`、`Add-Type` / `Reflection.Assembly` 动态加载、
  `schtasks.exe`，以及从 Bash 直接调用 PowerShell；
  注册表读写改用 Python `winreg`，语法检查用
  `[System.Management.Automation.Language.Parser]::ParseFile`（PowerShell 工具内）。
  这是**开发环境限制**，不影响交付给用户的 exe。
- PowerShell 5.1 的 `.ps1` 必须带 UTF-8 BOM，中文才不乱码。
- 运行 `.ps1` 需在执行策略受限环境里用 `-ExecutionPolicy Bypass`（进程级）。
