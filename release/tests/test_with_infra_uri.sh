#!/usr/bin/env bash
# --with-infra 默认连接串宿主适配测试（PR #73 第三轮审查 验收 4）。
#
# 从 release/agent-flow 提取 _default_host_adapt 纯函数并断言：
# - 默认 Mongo URI（带 replicaSet=rs0）→ host 变 127.0.0.1，query 参数原样保留；
# - 自定义 host / 自定义参数串不动；
# - Redis/Qdrant 默认串同步适配。
#
# 运行：bash release/tests/test_with_infra_uri.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="$HERE/../agent-flow"

# 提取函数体（避免 source 整个 launcher 触发 main）
sed -n '/^_default_host_adapt() {/,/^}/p' "$LAUNCHER" > /tmp/_adapt_fn.sh
# shellcheck source=/dev/null
source /tmp/_adapt_fn.sh
rm -f /tmp/_adapt_fn.sh

fails=0
assert_eq() { # <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then
    echo "ok   - $1"
  else
    echo "FAIL - $1"
    echo "  expected: $2"
    echo "  actual:   $3"
    fails=$((fails + 1))
  fi
}

# 默认 Mongo URI：host → 127.0.0.1，authSource + replicaSet 保留
assert_eq "默认 Mongo URI 宿主适配（保留 replicaSet）" \
  "mongodb://agentflow:changeme@127.0.0.1:27017/agent_flow?authSource=admin&replicaSet=rs0" \
  "$(_default_host_adapt "mongodb://agentflow:changeme@mongodb:27017/agent_flow?authSource=admin&replicaSet=rs0")"

# 自定义 host：不动
assert_eq "自定义 Mongo host 不改写" \
  "mongodb://user:pw@db.internal:27017/agent_flow?authSource=admin&replicaSet=rs0" \
  "$(_default_host_adapt "mongodb://user:pw@db.internal:27017/agent_flow?authSource=admin&replicaSet=rs0")"

# 自定义参数（无 replicaSet，外接独立部署形态）：只换 host，不增删参数
assert_eq "服务名 host + 自定义参数仅换 host" \
  "mongodb://agentflow:sec@127.0.0.1:27017/agent_flow?authSource=admin" \
  "$(_default_host_adapt "mongodb://agentflow:sec@mongodb:27017/agent_flow?authSource=admin")"

# Redis / Qdrant 默认串
assert_eq "Redis 默认串适配" \
  "redis://127.0.0.1:6379/0" \
  "$(_default_host_adapt "redis://redis:6379/0")"
assert_eq "Qdrant 默认串适配" \
  "http://127.0.0.1:6333" \
  "$(_default_host_adapt "http://qdrant:6333")"

if [ "$fails" -gt 0 ]; then
  echo "$fails 个断言失败"
  exit 1
fi
echo "全部通过"
