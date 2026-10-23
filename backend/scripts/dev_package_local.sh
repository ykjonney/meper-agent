#!/usr/bin/env bash
# dev_package_local.sh —— 本地拼装【交付包形态】并测试完整客户流程。
#
# 与正式包的差异（本地测试专属）：
#   · runtime 用 backend/.venv 链接代替捆绑 Python（正式包为独立 runtime/）
#   · .so 为本机平台（mac arm64；正式包在 Linux x86_64 构建机产出）
#   · license 强制通过 etc/agent-flow.env 注入（staging + 测试公钥）——
#     正式包在编译期固化，客户不可见不可改
#
# 用法：
#   scripts/dev_package_local.sh build    # 拼装 /tmp/agent-flow-local（含测试密钥）
#   scripts/dev_package_local.sh clean    # 清理包与测试密钥
#
# 拼装后按【客户视角】走流程：
#   cd /tmp/agent-flow-local
#   ./agent-flow start                     # 启动（未激活 → 激活向导）
#   ./agent-flow fingerprint               # 取指纹（发给"供应商"=你自己）
#   # —— 签发（供应商视角，另开终端，在仓库根执行）：
#     --keys /tmp/af-dev-keys --licensee 本地测试 --fingerprint <指纹> --expires 2027-12-31 --out /tmp/t.key
#   ./agent-flow license install /tmp/t.key   # 激活 + 自动补起 worker/beat
#   ./agent-flow status
#   浏览器 http://localhost:8000/ → 登录页
set -euo pipefail
cd "$(dirname "$0")/.."   # backend/

PKG=/tmp/agent-flow-local
KEYS=/tmp/af-dev-keys

say() { echo -e "\033[1;36m[本地交付包]\033[0m $*"; }

cmd_build() {
  # 前提检查
  ls dist/compiled/app/main.*.so >/dev/null 2>&1 || {
    echo "✗ 缺少 .so 编译产物，先构建：" >&2
    echo "    uv run --with cython --with setuptools python scripts/build_compiled.py --out dist/compiled" >&2
    exit 1
  }
  [ -f ../frontend-studio/dist/index.html ] && [ -f ../frontend-client/dist/index.html ] || {
    echo "✗ 缺少前端 dist，先构建：cd frontend-studio && npm run build（client 同理）" >&2
    exit 1
  }

  # 测试密钥（首次生成，之后复用——避免每次重签）
  # 测试 RSA 密钥对
  if [ ! -f "$KEYS/test_rsa.pem" ]; then
    .venv/bin/python -c "
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
open('$KEYS/test_rsa.pem','wb').write(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
" 2>/dev/null
  fi
  local pub_hex=""


  # 拼装
  rm -rf "$PKG" && mkdir -p "$PKG"/{app,web,etc}
  cp ../release/agent-flow "$PKG/" && chmod +x "$PKG/agent-flow"
  cp ../release/env.template "$PKG/"
  cp -a ../release/infra "$PKG/infra"
  [ -f ../LICENSE ] && cp ../LICENSE "$PKG/"
  [ -f ../NOTICE ] && cp ../NOTICE "$PKG/"
  # app：.so + cli 源码
  cp -a dist/compiled/app "$PKG/app"
  rm -rf "$PKG/app/app/cli" && cp -a app/cli "$PKG/app/app/cli"
  mkdir -p "$PKG/app/agent_flow_harness"
  cp -a dist/compiled/agent_flow_harness/. "$PKG/app/agent_flow_harness/"
  # runtime：链接 venv（本地测试专属，见文件头说明）
  ln -s "$(pwd)/.venv" "$PKG/runtime"
  # web
  cp -a ../frontend-studio/dist/. "$PKG/web/"
  cp -a ../frontend-client/dist/. "$PKG/web/client/"
  # 预置配置：模拟正式包（__BASE__ 展开 + license 强制注入）
  sed "s#__BASE__#$PKG#g; s#^APP_ENV=production#APP_ENV=staging#" ../release/env.template > "$PKG/etc/agent-flow.env"
  cat >> "$PKG/etc/agent-flow.env" <<EOF

# （本地测试注入——正式包为编译期固化，无此段落）
LICENSE_ENFORCE_EXTRA=true
LICENSE_PATH=$PKG/etc/jasper.identity
EOF
  # 真实场景测试：独立数据库（新客户视角，不污染开发库；测完可 drop）
  echo "MONGODB_URI=mongodb://127.0.0.1:27017/agent_flow_e2e" >> "$PKG/etc/agent-flow.env"
  # 复用 backend/.env 的加密密钥（保证多次重测 key 稳定，模型凭证不失效）
  for k in MODEL_ENCRYPTION_KEY JWT_SECRET_KEY; do
    v="$(grep -E "^$k=" .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
    [ -n "$v" ] && echo "$k=$v" >> "$PKG/etc/agent-flow.env"
  done
  chmod 600 "$PKG/etc/agent-flow.env"

  # macOS Gatekeeper：清除隔离属性，避免首次启动逐个扫描 412 个 .so（分钟级卡顿）
  [ "$(uname -s)" = Darwin ] && xattr -dr com.apple.quarantine "$PKG" 2>/dev/null || true
  say "拼装完成: $PKG"
  echo "──────────────────────────────────────────────"
  echo " 客户视角测试（按序执行）："
  echo "   cd $PKG"
  echo "   ./agent-flow start                # 未激活 → 向导"
  echo "   ./agent-flow fingerprint          # 指纹"
  echo "   # 签发（仓库根目录，供应商视角）："
  echo "     --keys $KEYS --licensee 本地测试 --fingerprint <指纹> --expires 2027-12-31 --out /tmp/t.key"
  echo "   ./agent-flow license install /tmp/t.key   # 激活+自动补 worker"
  echo "   ./agent-flow status && 浏览器 http://localhost:8000/"
  echo " 升级测试：改码 → 重新编译 .so → 再跑本脚本 build → 包内 ./agent-flow upgrade 不适用（直接重拼），正式升级在 Linux 包上验证"
  echo "──────────────────────────────────────────────"
}

cmd_clean() {
  "$PKG/agent-flow" stop >/dev/null 2>&1 || true
  rm -rf "$PKG" "$KEYS"
  say "已清理 $PKG 与 $KEYS"
}

case "${1:-build}" in
  build) cmd_build ;;
  clean) cmd_clean ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
