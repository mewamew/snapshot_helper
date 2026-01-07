#!/bin/bash
# SnapTool Mac 启动脚本
# 双击此文件即可启动截屏工具

cd "$(dirname "$0")"
source venv/bin/activate
python snap_tool.py
