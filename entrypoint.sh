#!/bin/bash
set -e

# 读取版本信息
VERSION=$(python3 -c "from version import __version__; print(__version__)" 2>/dev/null || echo "unknown")

echo "=================================================="
echo "企业微信记账助手 v${VERSION} 启动检查..."
echo "=================================================="

echo "数据库: 本地 SQLite (data/data.db)"

# 依赖检查（可选依赖自动安装）
echo ""
echo "正在检查依赖..."
python check_deps.py

# 启动应用
echo ""
echo "启动应用..."
exec python app.py
