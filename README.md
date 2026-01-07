# SnapTool - 跨平台截屏工具

一款轻量级的截屏工具，支持 macOS 和 Windows，具备全局热键快速截图、区域选择和图像标注功能。

## 功能特性

- **全局热键触发**:
  - macOS: `Ctrl+A`
  - Windows: `Shift+Alt+B`
- **区域选择**: 鼠标框选需要截取的屏幕区域
- **图像标注**: 支持在截图上进行涂鸦、画矩形、圆形、箭头等标注
- **多种工具**:
  - 自由画笔
  - 矩形标注
  - 圆形标注
  - 箭头标注（拖动控制方向和长度）
  - 橡皮擦（可擦除特定区域的标注）
  - 3 种颜色选择（红、绿、蓝）
  - 3 种笔触粗细
  - 撤回功能（撤销上一步操作）
- **自动保存**: 截图自动保存到系统临时目录
- **剪贴板集成**: 截图和文件路径自动复制到剪贴板，可直接粘贴
- **快捷确认**: 支持双击鼠标左键快速确认保存截图
- **系统托盘运行**: 最小化到系统托盘，不占用任务栏/Dock 空间
- **多显示器支持**: 自动识别鼠标所在的显示器进行截图
- **高 DPI/Retina 支持**: 完美支持高分辨率显示器

## 系统要求

- **macOS**: macOS 10.15 (Catalina) 或更高版本
- **Windows**: Windows 10/11
- **Python**: 3.8 或更高版本

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/your-username/snapshot_helper.git
cd snapshot_helper
```

### 2. 创建虚拟环境

```bash
python -m venv venv
```

### 3. 激活虚拟环境并安装依赖

**macOS / Linux:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
venv\Scripts\activate
pip install -r requirements.txt
```

## 使用方法

### 启动程序

**macOS:**
```bash
source venv/bin/activate && python snap_tool.py
```

**Windows:**
```bash
run.bat
```

程序将在后台启动，并在系统托盘显示图标。

### 截图操作

1. **触发截图**:
   - macOS: 按 `Ctrl+A`
   - Windows: 按 `Shift+Alt+B`
2. **框选区域**: 鼠标拖动选择截图区域
3. **编辑标注**（可选）:
   - 选择工具（画笔/矩形/圆形/箭头/橡皮擦）
   - 选择颜色和笔触粗细
   - 在截图上进行标注
   - 使用橡皮擦工具擦除不需要的标注
   - 点击撤回按钮可撤销上一步操作
4. **保存截图**:
   - 方式 1: 点击工具栏中的 `✓` 确定按钮
   - 方式 2: 在截图区域双击鼠标左键（快捷方式）
5. **取消截图**: 点击 `✕` 取消按钮或按 `ESC` 键

### 系统托盘操作

右键点击系统托盘图标可以:
- 手动触发截图
- 退出程序

## 开机自启动

### macOS

运行安装脚本：

```bash
chmod +x install_launchagent.sh
./install_launchagent.sh
```

卸载开机自启动：
```bash
launchctl unload ~/Library/LaunchAgents/com.snaptool.plist
rm ~/Library/LaunchAgents/com.snaptool.plist
```

### Windows

运行 PowerShell 脚本来创建开机启动快捷方式:

```powershell
.\create_startup.ps1
```

## macOS 权限设置

首次运行时，macOS 可能需要授予以下权限：

1. **辅助功能权限**（用于全局热键监听）:
   - 打开 **系统设置** → **隐私与安全性** → **辅助功能**
   - 添加 Terminal.app（或你使用的终端应用）

2. **屏幕录制权限**（用于截取屏幕）:
   - 打开 **系统设置** → **隐私与安全性** → **屏幕录制**
   - 添加 Terminal.app（或你使用的终端应用）

## 项目结构

```
snapshot_helper/
├── snap_tool.py              # 主程序
├── requirements.txt          # Python 依赖
├── README.md                 # 项目说明
├── run.bat                   # Windows 启动脚本
├── run_mac.command           # macOS 启动脚本
├── com.snaptool.plist        # macOS LaunchAgent 配置
├── install_launchagent.sh    # macOS 开机自启动安装脚本
├── create_startup.ps1        # Windows 开机启动配置脚本
└── diag.py                   # 显示器诊断工具
```

## 依赖项

- **PyQt6** (>= 6.0.0): GUI 框架
- **pynput** (>= 1.7.0): 全局热键监听
- **mss** (>= 9.0.0): 跨平台截屏库（Windows fallback）
- **pyobjc-framework-Quartz** (macOS): 原生截屏 API
- **pyobjc-framework-Cocoa** (macOS): 应用控制

## 截图保存位置

截图默认保存在系统临时目录:

- **macOS**: `/tmp/screenshots/`
- **Windows**: `%TEMP%\screenshots\`

文件名格式: `screenshot_YYYYMMDD_HHMMSS.png`

## 故障排查

### 常见问题

1. **热键不响应**
   - 确保程序正在运行（检查系统托盘图标）
   - macOS: 检查是否已授予辅助功能权限

2. **截图黑屏或无法截取**
   - macOS: 检查是否已授予屏幕录制权限

3. **截图模糊**
   - 程序已启用高 DPI/Retina 支持
   - 如果仍有问题，尝试重启程序

4. **多显示器问题**
   - 运行 `python diag.py` 检查显示器配置

### 诊断显示器信息

```bash
source venv/bin/activate  # macOS
python diag.py
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
