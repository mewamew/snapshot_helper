#!/bin/bash
# SnapTool LaunchAgent 安装脚本
# 运行此脚本将配置开机自动启动

PLIST_NAME="com.snaptool.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "正在安装 SnapTool 开机自启动..."
echo "安装路径: $SCRIPT_DIR"

# 确保 LaunchAgents 目录存在
mkdir -p "$LAUNCH_AGENTS_DIR"

# 如果已存在，先卸载
if [ -f "$LAUNCH_AGENTS_DIR/$PLIST_NAME" ]; then
    echo "检测到已安装，正在卸载旧版本..."
    launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null
fi

# 检测真实的 Python 路径
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
if [ -L "$VENV_PYTHON" ]; then
    # 追踪符号链接找到真实的 Python 可执行文件
    REAL_PYTHON=$(python3 -c "import os; print(os.path.realpath('$VENV_PYTHON'))")
    # 获取 Python.app/Contents/MacOS/Python 路径 (从 bin/python3.x 往上两级是 Framework 根目录)
    FRAMEWORK_PATH=$(dirname "$(dirname "$REAL_PYTHON")")
    PYTHON_EXEC="$FRAMEWORK_PATH/Resources/Python.app/Contents/MacOS/Python"
    if [ ! -f "$PYTHON_EXEC" ]; then
        # 如果 Python.app 路径不存在，使用原始真实路径
        PYTHON_EXEC="$REAL_PYTHON"
    fi
else
    PYTHON_EXEC="$VENV_PYTHON"
fi

echo "检测到 Python 路径: $PYTHON_EXEC"

# 复制 plist 文件并替换路径占位符
sed -e "s|__INSTALL_PATH__|$SCRIPT_DIR|g" -e "s|__PYTHON_PATH__|$PYTHON_EXEC|g" "$SCRIPT_DIR/$PLIST_NAME" > "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

# 加载服务
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo ""
echo "=========================================="
echo "安装完成！"
echo "=========================================="
echo ""

# 提示授权
echo "⚠️  首次使用需要授予 macOS 权限才能正常工作！"
echo ""
echo "请打开「系统设置 → 隐私与安全性」，在以下两项中添加："
echo ""
echo "📌 辅助功能 (Accessibility)："
echo "   $PYTHON_EXEC"
echo ""
echo "📌 屏幕录制 (Screen Recording)："
echo "   $PYTHON_EXEC"
echo ""
echo "提示：添加时按 Cmd+Shift+G 可以粘贴路径"
echo ""

echo "=========================================="
echo "其他命令："
echo "  重启服务: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo "  卸载: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && rm ~/Library/LaunchAgents/$PLIST_NAME"
echo "  查看日志: cat /tmp/snaptool.log"
echo "  查看错误: cat /tmp/snaptool.err"
echo "=========================================="
