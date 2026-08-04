#!/usr/bin/env bash
# M0 开发环境引导：安装项目依赖（editable + dev extras）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

.venv/Scripts/python -m pip install --upgrade pip -q
.venv/Scripts/python -m pip install -e ".[dev]" -q

echo "bootstrap done:"
.venv/Scripts/python -m pip list 2>/dev/null | grep -iE "langgraph|fastapi|pydantic|pytest|ruff|mypy|httpx|uvicorn" || true
