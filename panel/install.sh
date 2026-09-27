#!/usr/bin/env bash
# 高级路径：以现有游戏服务用户执行；已有 panel.json 原样保留。
set -Eeuo pipefail
umask 077
cd -- "$(dirname -- "$0")"
[[ $EUID != 0 ]] || { echo '请以运行游戏的普通用户执行；全新主机请使用 get.sh。' >&2; exit 1; }
command -v python3 >/dev/null || { echo '需要 Python 3.10 或更新'; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo '需要 Python 3.10 或更新'; exit 1; }
python3 -c 'import ensurepip' 2>/dev/null || { echo '缺少 venv 模块：sudo apt install python3-venv'; exit 1; }
[[ ! -L venv ]] || { echo '拒绝使用链接的 venv 目录'; exit 1; }
[[ -d venv ]] || python3 -m venv venv
venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
exec venv/bin/python -m l4d2panel.install_advanced
