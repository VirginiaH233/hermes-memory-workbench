#!/usr/bin/env bash
# macOS 上双击就能启动（Finder 里双击 .command 文件）。
# 它是 start.sh 的薄壳：出错时停住，好让你看到原因。
cd "$(dirname "$0")" || exit 1

if [ ! -f start.sh ]; then
  echo "✗ 找不到 start.sh —— 是不是把文件挪出去了？"
  read -r -p "回车关闭…" _
  exit 1
fi

bash start.sh "$@"
code=$?

if [ $code -ne 0 ]; then
  echo
  echo "（出错了，exit $code）"
  read -r -p "回车关闭…" _
fi
