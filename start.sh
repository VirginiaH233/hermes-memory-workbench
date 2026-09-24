#!/usr/bin/env bash
# 记忆审阅台 —— 启动脚本（macOS / Linux）
#
# 用法：
#   ./start.sh              看自己的真实记忆
#   ./start.sh --demo       用演示数据启动（假档案，碰不到真实记忆）
#   ./start.sh --port 8899  换端口（默认 8787）
#
# 只依赖 Python 3（标准库），不需要装任何东西。
set -u
cd "$(dirname "$0")" || exit 1

pick_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        echo "$c"; return 0
      fi
    fi
  done
  return 1
}

PY="$(pick_python)" || {
  echo "✗ 没找到 Python 3.9 以上的版本。"
  echo "  装一个再来：https://www.python.org/downloads/  （或 brew install python3）"
  exit 1
}

echo "用这个 Python：$PY（$("$PY" -c 'import sys;print(sys.version.split()[0])')）"
exec "$PY" server.py "$@"
