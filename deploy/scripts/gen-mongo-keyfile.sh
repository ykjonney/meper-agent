#!/usr/bin/env bash
# 生成 MongoDB 副本集内部鉴权 keyfile（单节点 RS + auth 必需，#64 E0）。
#
# mongod 在同时启用 authorization 与 --replSet 时强制要求 keyFile/x.509
# 内部鉴权——即使只有单成员。keyfile 是敏感凭证：
#   - 权限 400（mongod 要求 600 以下 Owner-only）
#   - 不要提交进 git（.gitignore 已排除 deploy/mongo/keyfile）
#   - 已初始化的副本集更换 keyfile 需滚动重启全部成员（单节点即重启）
set -euo pipefail

dir="$(cd "$(dirname "$0")/.." && pwd)/mongo"
target="$dir/keyfile"

if [ -f "$target" ]; then
  echo "keyfile 已存在：$target（如需轮换请先删除再重跑）"
  exit 0
fi

mkdir -p "$dir"
umask 077
openssl rand -base64 756 | tr -d '\n' > "$target"
chmod 400 "$target"
echo "已生成 $target"
echo "提示：MONGODB_URI 需带 &replicaSet=rs0（见 .env.example）"
