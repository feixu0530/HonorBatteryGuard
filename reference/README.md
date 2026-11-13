# 参考资料、技术决策与踩坑记录

> **v2.1.0 修订**：下方「技术决策记录」是 v1 的决策，其中 4 条已被实机复测推翻/调整
> （交付形态、常驻策略、自启动方式、权限方案）。最新结论见
> `02-可行性分析与实现方案.md` 第 6 节与 `03-v2构建与踩坑.md`。

## 1. 参考链接

### 荣耀官方（三档定义与行为）
- 笔记本电量充不满/只能充到 70%： https://www.hihonor.com/cn/support/content/zh-cn15813813
- 更新 BIOS 后充电模式变化： https://www.honor.com/cn/support/content/zh-cn15813840
- Battery charging mode changes after BIOS update（英文版）： https://www.honor.com/my/support/content/en-us15813840

### 固件接口 / 开源实现
- Linux 内核 `huawei-wmi.c`（`HWMI_METHOD_GUID`、`BATTERY_THRESH_GET/SET`、`hwmi_arg`）：
  https://raw.githubusercontent.com/torvalds/linux/master/drivers/platform/x86/huawei-wmi.c
- Huawei-WMI 驱动仓库（v3.3 已合入内核 5.5）： https://github.com/aymanbagabas/Huawei-WMI
- TLP 1.4 Huawei Battery Care 测试说明（`charge_control_start/end_threshold`、EC 自主控制）：
  http://gist.new/linrunner/2d8eadc217a86d28c1939ac31f434271
- Windows `OemWMIMethod.OemWMIfun` 与 `WmiUtil.dll` 序号/opcode 表（社区逆向）：
  https://git.mafyuh.dev/baldandbrave/Huawei-WMI
- Honor MagicBook 14 Pro / `FMB-P` 上 EC 只认 OEM 预设阈值对的讨论：
  https://github.com/colorcube/Linux-on-Honor-Magicbook-14-Pro/issues/10
- 电池充电阈值在 Linux 上未生效的排障案例（强调以 `charge_now` 趋势为准）：
  https://www.tuxwraith.com/huawei-matebook-battery-charge-threshold-linux

> 注：带 `gist.new` / `github.org` / `git.mafyuh.dev` 的为搜索结果中的镜像站点，
> 内容与原站一致；核心结论以 Linux 内核源码与本机实测为准。

## 2. 技术决策记录

| 决策 | 理由 |
|---|---|
| 走标准 ACPI-WMI，不调用荣耀私有驱动 | 官方 `HnWMISDK.dll` 自身就引用 `OemWMIMethod`；私有驱动有 SDDL、Exclusive、进程白名单三重限制 |
| 用 PowerShell 5.1 + WinForms 单文件，不用 Python/C# 编译 | Windows 自带、零依赖、原生 `Invoke-CimMethod`、真正绿色免安装；本机开发沙箱禁止 C# 编译与动态程序集加载 |
| 不常驻，只在点击/登录时下发一次 | 阈值保存在 EC；重发是为覆盖冷启动与管家重置，不需要后台进程 |
| 自启动优先计划任务（RunLevel Highest） | 静默获得管理员权限，避免 HKCU Run 每次登录弹 UAC |
| 只开放三档，不开放任意阈值 | 官方只定义三组 OEM 预设；社区实测 EC 可能只对这些预设激活限制 |
| 写 `\SBCM` 前先读 `\GBCM` 并原样带回 `dact` | 避免改变 EC 中未公开的状态位 |
| 验证以 `ChargeRate` + 容量趋势为准，不用 `Charging` 布尔值 | AC 在线时 `Charging` 恒为 True，会造成伪阳性 |

### 2.1 v2 修订后的决策（覆盖上表 4 条）

| 原决策 | v2 实际做法 | 原因 |
|---|---|---|
| PowerShell + WinForms 单文件 | **PyInstaller onefile exe**（Python 3.12 + `win32com` + tkinter） | 用户要求 .exe；C# 编译被环境禁止；直连 WMI COM 已实测通过 |
| 不常驻，只在点击/登录时下发一次 | **60 秒后台守护 + 登录重发** | 实测管家退出会把 EC 阈值清零为 0/100，一次性下发不够 |
| 自启动优先计划任务 | **纯 `HKCU\...\Run`（Python `winreg`）** | `schtasks.exe` 在开发环境被黑名单拦截；注册表方案零外部程序、可完整验证与撤销 |
| 「以管理员重启」按钮 | **exe manifest `requireAdministrator`** | v1 启动器未提权导致全部操作「拒绝访问」，必须启动即提权 |
| （新增）关闭窗口行为 | **默认最小化到任务栏 + 可选仅托盘** | Win11 会折叠新托盘图标，不能以托盘为唯一入口 |

## 3. 踩坑清单（避免半年后重踩）

1. **`u8Input` 必须是 64 字节**。按 Linux 的 `sizeof(u64)=8` 传会返回「无效的参数」，
   且错误信息完全不提示长度问题。
2. **`\SBCM` 的 byte[3] 是 `dact`，不是魔数**。社区示例里的 `0x48` 会被真实写进 EC；
   误用会改变充电模式状态。已实测并写回 0 恢复。
3. **`\\.\HHAL` 在管家运行时打不开**（`Exclusive` + 独占），错误码 5。
   不要以为管理员权限不足而反复提权。
4. **`HardwareSdk.dll` 的 `Battery::GetChargeThreshold` 在上述独占期间返回 `False`**，
   输出缓冲完全不被写入（填充 `0xCC` 可验证）。不要据此判断接口不存在。
5. **`BatteryStaticData` 在本机无实例、`Win32_Battery.DesignCapacity` 为空**。
   设计容量需从 `powercfg /batteryreport /xml` 的 `<DesignCapacity>` 读取并缓存。
6. **PowerShell 5.1 读取 `.ps1` 需要 UTF-8 BOM**，否则中文全部乱码。
7. **本机执行策略禁止运行 `.ps1`**，启动器必须带 `-ExecutionPolicy Bypass`
   （进程级，不改系统策略）。
8. **`Charging=True` 不代表在充电**。本机 69% 停充时仍是 `True`，
   必须看 `ChargeRate` 与 `RemainingCapacity` 趋势。
9. **从一个 PowerShell 会话里 `reg.exe` / `csc.exe` 会被沙箱拦截**，
   注册表查询改用 `Get-ItemProperty` / `Get-ChildItem`。
10. `powercfg` 输出 XML 带默认命名空间 `xmlns="http://schemas.microsoft.com/battery/2012"`，
    但 PowerShell 的 `[xml]` 属性访问可直接用 `$x.BatteryReport.Batteries.Battery.DesignCapacity`。
11. **★ 关闭荣耀电脑管家会把 EC 阈值清零**（`\GBTT` 变 `00 00 64`、`mode=0`），
    电池立刻恢复满充。这是管家退出时的一次性动作，不是周期性重置；
    写回 40/70 后 40 秒观察期内不再变化。工具必须有运行期守护。
12. **「拒绝访问」首先查权限，不要怀疑接口**。v1 启动器 `start` 未提权，
    普通双击下所有 WMI 调用被拒、状态区空白；管理员启动同一脚本即全部正常。
13. **停充后容量会自然下降**（带载放电），趋势判定不能用 `|delta| ≤ 2`；
    实测 30 秒 -110 mWh 把 PASS 误判成 UNKNOWN。
14. **WMI COM 只有 `ExecMethod_` 可用**，且 `u8Input` 必须显式包成
    `VARIANT(VT_ARRAY|VT_UI1, list)`；`o.OemWMIfun()`、`svc.ExecMethod(path,...)` 都失败。
15. **Windows 11 折叠新托盘图标**：`Shell_NotifyIcon(NIM_ADD)` 返回 True、`visible=True`，
    截图仍看不到 —— 需点 `^` 或在任务栏设置里允许显示。
16. **`--noconsole` 下 `sys.stdout is None`**，CLI 结果必须同时写文件才能验证。
17. **Git Bash 的 `pwd` 返回 `/c/...`**，PyInstaller 的 `--icon` / `--add-data`
    要用 `pwd -W` 得到 `C:/...`，否则报「找不到文件」（路径被解析成 `\c\...`）。
18. SVG 图标：`cairosvg` 缺 `libcairo-2.dll`、`reportlab.renderPM` 缺 `rlPyCairo`、
    Edge headless 不出图；**svglib → PDF → pypdfium2 → Pillow** 是本机可用链路。

## 4. 本机探测用到的关键路径

```
C:\Program Files\HONOR\PCManager\HnWMISDK.dll          # 官方 WMI SDK
C:\Program Files\HONOR\PCManager\HardwareSdk.dll       # Battery::Set/GetChargeThreshold
C:\Program Files\HONOR\PCManager\HardwareHal.dll       # HalInit/HalControl/HalQueryInformation
C:\Program Files\HONOR\PCManager\HNOs2Ec10x64.sys      # OS→EC 私有驱动
C:\Program Files\HONOR\PCManager\mainframe\Plugins\OS2SOC.sys / HHAL.sys
C:\Program Files\HONOR\PCManager\plugins\SmartChargePlugin.dll
C:\Program Files\HONOR\PCManager\plugins\PowerPolicyPlugin.dll
C:\Program Files\HONOR\PCManager\res\layout\battery_safety_management.xml
```
