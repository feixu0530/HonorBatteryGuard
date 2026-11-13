# HonorBatteryGuard · 荣耀电池安全管理独立控制工具

独立于荣耀电脑管家的「电池安全管理」绿色单文件工具。通过 ACPI-WMI 直接向笔记本 **EC 固件**下发充电阈值，把电池充到指定上限即停充，从而延长电池寿命——**全程无需运行荣耀电脑管家**。

## 功能

- **三档充电策略**：家用 `40→70%` / 办公 `70→90%` / 差旅 `95→100%`（带滞回，到上限即停充，不主动放电）
- **单文件 exe（约 20 MB）**：免安装、可携带，不写注册表（自启动走任务计划程序）
- **当前状态面板**：每分钟整点自动刷新，电量 / 电源 / 状态 / 电池健康度 / EC 充电阈值 五项彩色标识，数值按状态动态配色
- **趋势验证**：长时间观察 `ChargeRate` 与容量曲线，确认真的停充（而不是误判）
- **后台守护**：每 60 秒校验阈值，对抗「荣耀电脑管家退出时把 EC 清零」
- **随系统启动**：任务计划程序登录触发器 + 最高权限，登录静默提权、**无 UAC 弹窗**
- **单实例保护**：重复双击只把已运行的窗口提到前台，不会多开
- **电池报告**：一键生成 `powercfg /batteryreport` HTML

## 下载与运行

从本仓库 `releases/` 目录获取 `HonorBatteryGuard.exe`，**右键「以管理员身份运行」**（写入 EC 需要管理员权限）。正常双击也会弹 UAC，请点「是」。

## 工作原理

充电上限由 **EC 固件**执行并保存在其 NVRAM 中，**跨关机持久化**——它独立于 Windows，也独立于本工具。Windows 侧（本工具 / 荣耀电脑管家）只是通过 WMI 把参数「下发」给 EC，至于充不充电、充到多少，全部由 EC 自己决定。

通道：`root\wmi` → `OemWMIMethod.OemWMIfun` → 实例 `ACPI\PNP0C14\HWMI_0`

| 命令 | opcode | 作用 |
|---|---|---|
| `\GBTT` | `0x1103` | 读取当前阈值 |
| `\SBTT` | `0x1003` | 写入阈值（payload `[start, end]`） |
| `\GBCM` | `0x1603` | 读取模式 |
| `\SBCM` | `0x1503` | 写入模式（须带回 `dact`） |

> 判据：`Charging` 布尔值不可靠；本工具用 `ChargeRate == 0` + 容量「不上升」来判定停充。

更完整的原理、可行性分析与构建踩坑见 `reference/` 目录。

## 重要须知

- **设置保存到 EC，关机 / 重启后依然生效**：哪怕本工具完全不开，电池也会按上次设的上限限充。
- 后台守护循环**只为防御**「荣耀电脑管家退出时把 EC 清零」，并非 EC 会「遗忘」。
- 若你重新打开荣耀电脑管家并退出，它会把阈值清回 `0→100`；此时本工具的守护会在 60 秒内自动抢回，或手动点一次「应用并验证」。

## 构建

需要 Python 3.12 + `pywin32 / pyinstaller / pystray / pillow / psutil`。构建脚本与测试脚本见 `tools/`，完整命令见 `tools/README.md`：

```bash
pyinstaller --onefile --noconsole --uac-admin \
  --name HonorBatteryGuard \
  --icon assets/HonorBatteryGuard.ico \
  --add-data "assets/HonorBatteryGuard.png;." \
  --add-data "assets/HonorBatteryGuard.ico;." \
  HonorBatteryGuard.py
```

## 仓库结构

```
HonorBatteryGuard.py   主程序源码
assets/                图标资源（打包时需要）
releases/              交付物：exe + 使用说明 + 版本发布记录
reference/             底层原理 / 可行性分析 / 构建踩坑笔记
tools/                 构建脚本与回归测试脚本
```

## 免责声明

本工具通过厂商公开的 ACPI-WMI 通道下发参数，不修改任何系统文件；但操作 EC 充电策略存在一定风险，请在了解原理后再使用。
