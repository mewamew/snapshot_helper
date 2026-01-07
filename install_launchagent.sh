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
echo "安装完成！"
echo "SnapTool 将在下次登录时自动启动。"
echo ""
echo "其他命令："
echo "  卸载: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && rm ~/Library/LaunchAgents/$PLIST_NAME"
echo "  立即启动: launchctl start com.snaptool"
echo "  查看日志: cat /tmp/snaptool.log"
echo "  查看错误: cat /tmp/snaptool.err"
