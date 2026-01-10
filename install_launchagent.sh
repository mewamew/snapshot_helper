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

# 复制 plist 文件并替换路径占位符
sed "s|__INSTALL_PATH__|$SCRIPT_DIR|g" "$SCRIPT_DIR/$PLIST_NAME" > "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

# 加载服务
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo ""
echo "=========================================="
echo "安装完成！"
echo "=========================================="
echo ""

# 检测 Python 路径并提示授权
PYTHON_PATH="$SCRIPT_DIR/venv/bin/python"
if [ -L "$PYTHON_PATH" ]; then
    # 追踪符号链接找到真实路径
    REAL_PYTHON=$(readlink -f "$PYTHON_PATH")
    FRAMEWORK_DIR=$(dirname "$(dirname "$REAL_PYTHON")")
    PYTHON_BIN="$FRAMEWORK_DIR/bin/python3"
    PYTHON_APP="$FRAMEWORK_DIR/Resources/Python.app"

    echo "⚠️  首次使用需要授予 macOS 权限才能正常工作！"
    echo ""
    echo "请打开「系统设置 → 隐私与安全性」，在以下两项中添加："
    echo ""
    echo "📌 辅助功能 (Accessibility)："
    if [ -f "$PYTHON_BIN" ]; then
        echo "   $PYTHON_BIN"
    fi
    if [ -d "$PYTHON_APP" ]; then
        echo "   $PYTHON_APP"
    fi
    echo ""
    echo "📌 屏幕录制 (Screen Recording)："
    if [ -f "$PYTHON_BIN" ]; then
        echo "   $PYTHON_BIN"
    fi
    if [ -d "$PYTHON_APP" ]; then
        echo "   $PYTHON_APP"
    fi
    echo ""
    echo "提示：添加时按 Cmd+Shift+G 可以粘贴路径"
    echo ""
fi

echo "=========================================="
echo "其他命令："
echo "  重启服务: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo "  卸载: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && rm ~/Library/LaunchAgents/$PLIST_NAME"
echo "  查看日志: cat /tmp/snaptool.log"
echo "  查看错误: cat /tmp/snaptool.err"
echo "=========================================="
