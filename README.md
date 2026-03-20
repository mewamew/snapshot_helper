# SnapTool - 截屏标注工具

一款轻量级截屏工具，支持 macOS 和 Windows，可快速截图并添加标注。

## 功能特性

- **全局热键快速截图**
  - macOS: `Ctrl + A`
  - Windows: `Shift + Alt + B`
- **区域选择**: 鼠标框选需要截取的屏幕区域
- **窗口截图**: 悬停在窗口上自动高亮，点击可截取整个窗口
- **标注工具**:
  - 移动工具（默认）：拖拽已绘制的图形
  - 画笔：自由涂鸦
  - 矩形：绘制矩形框
  - 圆形：绘制椭圆框
  - 箭头：绘制箭头
  - 直线：绘制直线
  - 橡皮擦：擦除标注
  - 文字：在截图上添加文字
- **颜色选择**: 红色 / 绿色 / 蓝色
- **粗细选择**: 细 / 中 / 粗
- **字号选择**: 小 / 中 / 大（文字工具）
- **撤回功能**: 撤销上一步操作
- **双击保存**: 在截图区域双击左键快速保存
- **自动保存**: 截图自动保存到下载目录
- **剪贴板集成**: 文件路径自动复制到剪贴板
- **系统托盘**: 最小化到托盘，不占用任务栏
- **多显示器支持**: 自动识别鼠标所在显示器
- **高 DPI 支持**: 完美支持 Retina/高分辨率屏

---

## 安装

### 1. 克隆项目

```bash
git clone <仓库地址>
cd snapshot_helper
```

### 2. 创建虚拟环境

**macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. macOS 额外设置

首次运行需要授予权限：

1. **辅助功能权限**（热键监听）:
   - 系统设置 → 隐私与安全性 → 辅助功能
   - 添加 Terminal.app 或你的终端应用

2. **屏幕录制权限**（截图功能）:
   - 系统设置 → 隐私与安全性 → 屏幕录制
   - 添加 Terminal.app 或你的终端应用

---

## 使用方法

### 启动程序

**macOS:**

```bash
source venv/bin/activate
python3 snap_tool.py
```

或双击运行 `run_mac.command`

**Windows:**

双击运行 `run.bat`

程序启动后会最小化到系统托盘。

---

### 截图操作

#### 1. 触发截图

| 系统 | 热键 |
|------|------|
| macOS | `Ctrl + A` |
| Windows | `Shift + Alt + B` |

或右键点击托盘图标 → "截取屏幕"

#### 2. 选择截图区域

- **框选区域**: 鼠标拖动框选
- **窗口截图**: 将鼠标移到窗口上，会自动高亮显示，点击即可截取该窗口

#### 3. 编辑标注

截图后会进入编辑模式，底部工具栏提供以下工具：

| 工具 | 说明 |
|------|------|
| 移动 | 拖拽已绘制的图形（任何工具下都可用） |
| 画笔 | 自由涂鸦 |
| 矩形 | 绘制矩形框 |
| 圆形 | 绘制椭圆框 |
| 箭头 | 绘制箭头 |
| 直线 | 绘制直线 |
| 橡皮擦 | 擦除标注 |
| 文字 | 添加文字标注 |

点击工具按钮后，如果该工具有参数（颜色/粗细/字号），会弹出参数面板：

- **颜色面板**: 红色 / 绿色 / 蓝色
- **粗细面板**: 细 / 中 / 粗
- **字号面板**: 小 / 中 / 大（仅文字工具）

#### 4. 撤回操作

点击工具栏的 **↩ 撤销** 按钮可撤销上一步操作。

#### 5. 保存截图

保存方式（三选一）:

1. 点击工具栏 **✓** 按钮
2. 在截图区域 **双击左键**（快捷方式）
3. 按 `Enter` 键

取消截图: 按 `ESC` 键 或 点击 **✕** 按钮

---

### 系统托盘操作

右键点击托盘图标可以：

- **截取屏幕** - 手动触发截图
- **退出** - 关闭程序

---

### 开机自启动

#### macOS

运行安装脚本：

```bash
chmod +x install_launchagent.sh
./install_launchagent.sh
```

卸载：

```bash
launchctl unload ~/Library/LaunchAgents/com.snaptool.plist
rm ~/Library/LaunchAgents/com.snaptool.plist
```

#### Windows

运行 PowerShell 脚本：

```powershell
.\create_startup.ps1
```

---

## 截图保存

截图自动保存到系统下载目录：

| 系统 | 路径 |
|------|------|
| macOS | `~/Downloads/screenshots/` |
| Windows | `C:\Users\<用户名>\Downloads\screenshots\` |

文件名格式: `screenshot_YYYYMMDD_HHMMSS.png`

截图路径会自动复制到剪贴板。

---

## 故障排查

### 热键不响应

- 确保程序正在运行（检查系统托盘图标）
- macOS: 检查是否已授予辅助功能权限

### 截图黑屏

- macOS: 检查是否已授予屏幕录制权限

### 多显示器问题

运行诊断工具检查显示器配置：

```bash
# macOS
source venv/bin/activate
python3 diag.py

# Windows
venv\Scripts\python.exe diag.py
```

---

## 项目结构

```
snapshot_helper/
├── snap_tool.py              # 主程序
├── requirements.txt          # Python 依赖
├── README.md                 # 项目说明
├── run.bat                   # Windows 启动脚本
├── run_mac.command           # macOS 启动脚本
├── install_launchagent.sh    # macOS 开机自启动安装脚本
├── create_startup.ps1        # Windows 开机启动配置脚本
├── com.snaptool.plist        # macOS LaunchAgent 配置
└── diag.py                   # 显示器诊断工具
```

---

## 依赖项

- **PyQt6**: GUI 框架
- **pynput**: 全局热键监听（Windows）
- **mss**: 跨平台截屏库
- **Pillow**: 图像处理

---

## 日志

程序运行日志保存在：

| 系统 | 路径 |
|------|------|
| macOS | `/tmp/snaptool_logs/snaptool.log` |
| Windows | `%TEMP%\snaptool_logs\snaptool.log` |

如果遇到问题，可查看日志文件排查。

---

MIT License
