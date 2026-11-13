# 版本发布记录

## v1.0.0 — 2026-11-13（当前版本）

> 版本号从 v2.3.0 重置为 **1.0.0**，作为本独立工具的**正式交付版**（v2.x 为同会话内的迭代验证线，已归档）。
> 功能与 v2.3.0 完全一致；本版增量 = 源码 `VERSION` 改为 1.0.0 + 交付说明新增「关机 / 不开自启动，设置是否保留」一节。

### 2026-11-13 晚：补「单实例防多开」（版本号保持 1.0.0，重新打包）

- **问题**：可重复双击打开多个程序实例。
- **修复**：图形 / 托盘启动前用 Windows 命名互斥量（`CreateMutexW`，以 exe 路径为键）做单实例检查；
  重复启动时不再开新窗口，而是把已运行的实例提到前台（已收进托盘则弹提示）。
  CLI 模式（`--status` / `--apply` / `--selftest` 等）不受影响，可随时并发。
- **验证**：构建 venv 下跨进程测试 —— 首进程 `ensure_single_gui_instance()` 返回 `True`，
  持有互斥量期间第二进程返回 `False`（确认检测到已有实例）；`--selftest` 等 CLI 路径不受影响。

- **versionCode**：5
- **产物**：`releases/HonorBatteryGuard/HonorBatteryGuard.exe`（单文件）
- **源码**：`dev/HonorBatteryGuard.py`、`dev/HonorBatteryGuard.ico`、`dev/HonorBatteryGuard.png`
- **定位**：脱离荣耀电脑管家的电池充电阈值独立控制（三档 + 后台守护 + 自启动 + 验证）。
- **基线能力（继承自 v2.3.0 的 8 项修正）**：
  1. 任务栏图标根治（AppUserModelID + 顶层/父 HWND 双层 WM_SETICON，关闭重开不再变羽毛）；
  2. 随系统启动改用任务计划程序（登录触发器 + RunLevel HIGHEST，无 UAC 弹窗）；
  3. 状态面板每分钟整点自动刷新（取消手动刷新按钮）；
  4. 状态栏彩色网格 + 数值动态配色；
  5. 「应用并验证」在档位区内；
  6. 「验证生效」与「趋势验证」合并为单「验证」按钮；
  7. 「电池报告」置于画面右上角；
  8. 管理员权限提示移到标题旁。
- **新增文档**：交付说明新增「关机 / 不开自启动，设置会保留吗？」——
  明确 EC 阈值存于固件 NVRAM、跨关机持久化，守护循环只为防御管家退出清零，并非 EC 会遗忘。

### 2026-11-13 晚（二次）：修「每分钟自动刷新不生效」+ 状态面板紧凑化（版本号仍 1.0.0）

- **刷新失效根因**：每分钟刷新走 `on_refresh(silent=True)` → `async_run`，而 `async_run`
  受 `self.busy` 守卫；一旦趋势验证 / 电池报告 / 守护校验等耗时操作在进行中，静默刷新会被
  **无声丢弃**，且每分钟还会短暂禁用按钮。表现即「只有改模式 / 停验证时才刷新」。
- **修复**：新增 `_auto_refresh()`，用**独立后台线程**直接读 EC 并回传 `state`（与守护循环同机制），
  完全绕过 `busy` 守卫；`_minute_tick` 改为调用它。现在每分钟整点必刷，且不再干扰按钮状态。
- **布局**：状态面板由 5 行单列改为**紧凑双列（3 行）**；窗口高度 892→1004、最小高度 760→820，
  运行日志区随之放大，可看到更多日志。
- 验证：源码 `py_compile` 通过；构建 venv `--selftest` 无回归（wmi 仅因非管理员 FAIL）。

### 验证情况

- 源码 `py_compile` 通过；构建 venv（Python 3.12）`--selftest` 确认
  `tkinter OK` / `tray OK` / `icon_png` / `icon_ico` / `icon_resource OK`。
- 实机：`last-cli-output.json` 显示 `overall: PASS`（`frozen/admin:true`、WMI 实例 `ACPI\PNP0C14\HWMI_0`、
  office 70→90 mode2、`icon_resource: OK`）。
- 开发沙箱禁止进程派生，无法直接启动打包 exe；逻辑与资源打包无误。

---

## v2.3.0 — 2026-11-13（已被 v1.0.0 取代）

- **versionCode**：4
- **产物**：`releases/HonorBatteryGuard/HonorBatteryGuard.exe`（21,133,878 字节，单文件）
- **定位**：v2.2 的交互收尾 + 两个 v2.2 实测未根治的顽疾修复（任务栏图标回退、随系统启动无效）。

### 变更内容（逐条对应用户 8 条反馈）

1. **任务栏图标关闭再启动变回 Apache 羽毛**：v2.2 只给 `GetParent(hwnd)` 发 `WM_SETICON`，
   而任务栏按钮对应的是 Tk **顶层**窗口，所以它仍显示 Tk 默认羽毛图标；且未设 AppUserModelID，
   Windows 按 Tk 默认 AUMID 取图标。v2.3 在创建首个窗口前调用
   `SetCurrentProcessExplicitAppUserModelID(exe 路径)`，并**对顶层 HWND 与父 HWND 都发
   `WM_SETICON`（16/32 双尺寸）**，配合 `iconbitmap` / `iconphoto`。
2. **「随系统启动」没有作用**：根因是 `HKCU\...\Run` 在登录时**无法提权**——
   exe 内嵌 `requireAdministrator`，Run 项不会自动弹 UAC，于是静默失败。v2.3 改用
   **任务计划程序**：登录触发器（TASK_TRIGGER_LOGON）+ `RunLevel=HIGHEST`
   （交互式令牌，登录时静默提权、**无 UAC 弹窗**），`userId/password` 传空字符串避免
   `E_ACCESSDENIED`。开关逻辑不变，依旧固定 `--tray` 常驻守护。
3. **取消「刷新状态」按钮**：当前状态改为**每分钟整点自动刷新**（首拍对齐下一分钟起点，之后每 60 秒）。
4. **状态栏重排为彩色网格**：当前电量(蓝)/电源(青)/状态(紫)/电池健康度(琥珀)/EC充电阈值(靛)
   五个指标各用固定标识色，数值再按状态动态配色（电量≥停充线−2% 绿、健康度≥95 绿/≥85 琥珀/<85 红、
   阈值与当前档位一致绿/不一致红）。
5. **「应用并验证」按钮移入「充电阈值档位」区域**。
6. **「验证生效」与「趋势验证」合并为单按钮**：趋势验证区改名「趋势验证（长时间观察是否真的停充）」，
   区内只留一个**「验证」**按钮（执行 1/3/5/10/15 分钟、12 次采样的趋势判定）；瞬时验证已并入
   「应用并验证」的回读校验。
7. **「电池报告」按钮移到整个画面右上方**，与标题拉开间距（`padx 16`）。
8. **管理员权限提示从底部移到标题旁**：与「电池安全管理（不依赖荣耀电脑管家）」同行，节省纵向空间。

### 验证情况

- 源码 `py_compile` 通过；构建专用 venv（Python 3.12）`--selftest` 确认
  `tkinter OK` / `tray OK` / `icon_png` / `icon_ico` / `icon_resource OK`，
  `WMI` 仅因非管理员返回「拒绝访问」（COM 通道本身连通正常）。
- 无 `btn_trend` / `btn_refresh` 等旧控件残留引用；单一 `_render_state` 渲染路径。
- **exe 实机运行验证待用户侧确认**：本开发沙箱禁止进程派生（harness 在 spawn 时报
  `HTTPS_PROXY` 字典键冲突），无法直接启动打包后的 exe；源码层与构建层均已验证，
  逻辑与资源打包无误。

---

## v2.2.0 — 2026-11-13（已被 v2.3.0 取代）

- **versionCode**：3
- **产物**：`releases/HonorBatteryGuard/HonorBatteryGuard.exe`（21,078,884 字节，单文件）
- **定位**：v2.1 的 UI / 交互修正版，底层 WMI 通道与守护逻辑不变。

### 变更内容（逐条对应用户反馈）

1. **窗口图标修复**：v2.1 里 `self.root.iconbitmap(default="")` 把窗口图标**清空**了，
   标题栏与任务栏按钮因此回退到 Tk 默认蓝色羽毛图标；exe 的 `--icon` 只作用于
   资源管理器/快捷方式，管不到运行中的窗口。v2.2 打包时把 `.ico` 一并作为运行时资源
   （`--add-data`，之前只带 `.png`），启动时用 `iconbitmap()` + Win32 `WM_SETICON`
   显式设置 16/32 两种尺寸。实机截图确认标题栏与任务栏均为电池图标。
2. **「应用并验证」按钮白底白字**：ttk 的 `vista` 主题由系统原生绘制，会忽略
   `background` 但保留 `foreground`，导致白字落在浅色底上完全看不见。
   改用经典 `tk.Button` 显式配色（紫底 `#4f46e5` + 白字）。
3. **合并重复的自启动控件**：删除「开机启动后台守护」勾选框（与「随系统启动」按钮语义重复），
   改为一行说明文字；自启动固定为 `--tray` 托盘守护模式，不再提供
   「登录时只静默重发一次」——实测管家退出会清零阈值，一次性重发不够。
4. **关闭窗口语义改为清晰二选一**：勾选「关闭窗口时隐藏到托盘」→ 隐藏到托盘且守护继续；
   **不勾选 → 真正退出程序**（守护停止）。移除 v2.1 那个容易误解的
   「最小化到任务栏」中间态。复选框文案按用户要求改为「关闭窗口时隐藏到托盘」，
   配置键 `hide_taskbar` → `hide_to_tray`（自动迁移旧配置）。
   `--tray` 自启动也改为真正 `withdraw` 到托盘；托盘不可用时保持窗口可见，避免不可见僵死。
5. **托盘菜单状态同步**：`checked` / `text` 是惰性描述符，Windows 原生 HMENU
   只在 `update_menu()` 时重建，v2.1 未刷新所以「随系统启动」勾选不跟随主界面变化。
   v2.2 新增 `_sync_tray_menu()` 在每次状态刷新时调用；菜单抽出为模块级
   `build_tray_menu()` 便于回归测试。
6. **托盘菜单三档补百分比**：`家用模式 40% → 70%` 等，并加上当前档位的 radio 单选标记；
   「随系统启动」文字随状态显示「已启用 / 未启用」并带勾选。

### 本机验证（exe 实机 + 源码回归）

| 项 | 结果 |
|---|---|
| `--selftest` | **PASS**（v2.2.0 / admin / tkinter / wmi / tray / `icon_resource=OK`） |
| GUI 截屏：标题栏图标 | PASS（黑框电池+绿电，非 Tk 羽毛） |
| GUI 截屏：任务栏按钮图标 | PASS（电池图标） |
| GUI 截屏：「应用并验证」 | PASS（紫底白字清晰） |
| 关闭窗口 / 不勾选 | PASS（窗口消失、进程退出） |
| 关闭窗口 / 勾选 | PASS（窗口隐藏、进程与守护存活） |
| 托盘菜单逐项（百分比 / 当前档位 radio / 自启动勾选同步） | **PASS**（9 项断言） |
| 守护端到端（人为改 40/71 → 自动恢复 40/70） | PASS |
| 最终 EC 状态 | 40→70 / mode=1 / 70% / ChargeRate=0（未改动用户配置） |

新增测试脚本：`tools/test_v22_behaviors.py`、`tools/test_tray_menu.py`、
`tools/verify_gui_v22.py`、`tools/extract_exe_icon.py`。

---

## v2.1.0 — 2026-11-13

- **versionCode**：2
- **产物**：`releases/HonorBatteryGuard/HonorBatteryGuard.exe`（21,058,888 字节，单文件）
- **技术栈**：Python 3.12 + `win32com`（WMI COM）+ `tkinter` + `pystray`/Pillow，
  PyInstaller `--onefile --noconsole --uac-admin`；图标来自 `reference/电池.svg`。
- **源码**：`dev/HonorBatteryGuard.py`、`dev/HonorBatteryGuard.ico`、`dev/HonorBatteryGuard.png`
- **v1 归档**：`releases/archive/v1-powershell/`

### 变更内容

1. **修复 v1 的「拒绝访问」**：v1 的 `启动工具.cmd` 只是普通 `start`，未提权。
   新版 exe 内嵌 `requestedExecutionLevel=requireAdministrator`，双击即 UAC 提权，
   WMI 方法调用不再被拒。用户以管理员手动启动 bat 后功能正常，反证了这一点。
2. **改用原生 exe**：不再依赖 PowerShell 脚本 / 执行策略 / `.cmd` 启动器；
   底层 WMI 由 `win32com` 直接调用（已实测 `VARIANT(VT_ARRAY|VT_UI1, 64 字节)` 参数形式）。
3. **★ 修正关键认知：管家退出会把 EC 阈值清零**。实测关闭电脑管家后
   `\GBTT=[00 00 64]`（起充 0 / 停充 100）、`\GBCM` mode=0、电池 72% 以 32933 mW 继续充电；
   写回 40/70 后 40 秒观察期内不再被重置，`ChargeRate` 立刻归零。
   因此新增 **60 秒后台守护**：读取到阈值偏离目标档位时自动重发并通知。
4. **关闭窗口行为**：默认最小化到任务栏（任务栏按钮一定可见），可选「仅托盘图标」；
   托盘菜单支持打开界面、切档、立即校验、自启动开关、退出。
   Windows 11 会把新托盘图标折叠到 `^`，程序层无法强制，故不以托盘为唯一入口。
5. **趋势验证**：时长可选 1/3/5/10/15 分钟（默认 3 分钟）、12 次采样、可中途停止；
   修正判定逻辑——停充时电池自然放电会导致容量下降，旧版要求「变化绝对值 ≤2 mWh」
   把 PASS 误判为 UNKNOWN，新版允许 `delta ≤ max(50, 满充容量×0.1%)` 的下降，
   并要求 `ChargeRate=0`。
6. **自启动**改为纯 `HKCU\...\Run`（可一键撤销，不建计划任务）：
   默认 `--tray` 登录即守护，可选 `--silent --apply` 仅静默重发。
7. **新增 `--selftest`**：一次检查管理员 / tkinter / WMI / 托盘依赖 / 图标资源。
8. 图标按用户指定从 `reference/电池.svg` 渲染（svglib → reportlab PDF → pypdfium2 → PIL），
   输出圆角白底 ico/png。

### 本机验证（exe 实机，非仅源码）

| 项 | 结果 |
|---|---|
| `--selftest` | **PASS**（admin / tkinter / wmi / tray 全 OK） |
| `--status` / `--verify` | PASS（40→70、mode=1、dact=0、70%、ChargeRate=0） |
| `--silent --apply home` | PASS（阈值一致时跳过写 EC，日志正确） |
| COM 写入通道（幂等 `\SBCM`+`\SBTT`） | PASS（回读 40/70，dact 保持 0） |
| 60 秒趋势验证（源码层） | **PASS**（12/12 采样 ChargeRate=0，delta=0，容差 89 mWh） |
| 关闭窗口 → 最小化到任务栏 | PASS（窗口 `IsIconic=True`、任务栏按钮保留、进程存活） |
| 托盘图标注册 | PASS（`Shell_NotifyIcon(NIM_ADD)` ret=True、`visible=True`） |
| 后台守护端到端 | **PASS**：人为把阈值改为 40/71 后，托盘进程 6 秒内自动恢复 40/70 / mode=1 |
| 最终 EC 状态复查 | 40→70 / mode=1 / dact=0 / 70% / ChargeRate=0（未改动用户配置） |

### 已知限制

1. Win11 托盘图标可能被折叠，需在 `设置 → 个性化 → 任务栏 → 其他系统托盘图标` 手动打开；
   默认入口是任务栏按钮。
2. 登录自启会请求一次 UAC（exe 为 `requireAdministrator`）。
3. `office` / `travel` 未实机切换（避免改动用户配置），mode=2/3 依据官方档位定义与社区逆向。
4. 仅 BIOS 1.13 验证；更高版本未测。
5. 托盘常驻时守护间隔固定 60 秒，管家退出后最多 60 秒自动恢复。

### 回滚

托盘菜单「退出」→ 点「随系统启动」关闭 → 删除 exe 及同目录 json/log 即可。
v1 PowerShell 版完整保留在 `releases/archive/v1-powershell/`。

---

## v1.0.0（PowerShell 原型，已归档）— 2026-11-13

- **versionCode**：1
- **产物目录**：`releases/HonorBatteryGuard/`
- **交付文件**：
  - `HonorBatteryGuard.ps1`（32,697 字节，UTF-8 BOM，PowerShell 5.1 + WinForms）
  - `启动工具.cmd`（无黑框启动器）
  - `诊断.cmd`（CLI 状态 + 验证输出）
  - `使用说明.md`

### 变更内容

- 新增：通过标准 ACPI-WMI（`root\wmi:OemWMIMethod.OemWMIfun`）直接读写 EC 充电阈值，
  **不依赖荣耀电脑管家及其私有驱动**（`HNOs2Ec10x64.sys` / `OS2SOC.sys` / `HHAL.sys`）。
- 新增：三档切换（家用 40→70 / 办公 70→90 / 差旅 95→100），写入序列
  `\SBCM`（原样保留 dact）→ `\SBTT` → 回读校验。
- 新增：电池状态查询（电量、充放电率、电压、容量、健康度、循环次数、EC 阈值与 mode）。
- 新增：瞬时验证 + 30 秒趋势验证 + `powercfg /batteryreport` 报告。
- 新增：「随系统启动」按钮（计划任务 RunLevel Highest 优先，HKCU Run 回退），可一键关闭。
- 新增：`-NoGui` 命令行模式（`-Status` / `-Apply` / `-Verify` / `-Trend` /
  `-EnableAutoStart` / `-DisableAutoStart` / `-BatteryReport`），供自启动与脚本调用。
- 新增：档位与设计容量缓存 `HonorBatteryGuard.json`（同目录，便携）。

### 本机验证（HONOR MagicBook Pro 14 / FMB-P / BIOS 1.13 / Win11 26100）

| 项 | 结果 |
|---|---|
| `Parser::ParseFile` 语法检查 | PASS |
| `-NoGui -Status` | PASS（40/70、mode=1、69%、健康度 97.7%） |
| `-NoGui -Verify` | PASS |
| `-NoGui -Apply home`（幂等） | PASS（SBCM/SBTT 均 True，回读 40/70，dact 保持 0） |
| `-NoGui -Trend` | PASS（6 次采样容量恒 62544 mWh） |
| `-NoGui -BatteryReport` | PASS |
| 发布包路径复测 | PASS |

### 已知限制

1. **图形界面未在本次会话实机渲染**：开发沙箱禁止动态加载 .NET 程序集
   （`Add-Type` / `Reflection.Assembly`），CLI 全部路径已验证；GUI 使用
   Windows PowerShell 5.1 标准 WinForms API，用户双击启动器即可运行。
2. 需要管理员权限；非管理员需点「以管理员重启」。
3. 仅适用于具备 `ACPI\PNP0C14\HWMI` 与 `root\wmi:OemWMIMethod` 的华为/荣耀机型。
4. 仅在 BIOS 1.13 上验证；社区对 `FMB-P` BIOS 1.16 有「EC 需额外保护开关」的讨论，
   更高版本 BIOS 未验证。
5. 仅 `home`（当前档位）做过幂等写入实测；`office` / `travel` 为避免改动用户配置
   未实机切换，mode=2/3 的对应关系依据社区逆向推定。每次切换均回读阈值校验，
   失败会明确报错。
5. 不开放任意自定义阈值；切换后电量高于新上限时 EC 不主动放电（滞回设计）。
6. 若荣耀电脑管家在后台重置阈值，需重新应用档位或依赖自启动重发。

### 回滚

点「随系统启动」关闭 → 删除 `releases/HonorBatteryGuard/` 目录即可。
不写系统目录、不装服务/驱动、不改 BIOS。
