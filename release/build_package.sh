#!/usr/bin/env bash
# build_package.sh —— 全流程构建脚本（前端 + 后端 .so + runtime + 组装 + zip）。
#
# 在两种环境中被调用（同一份逻辑）：
#   · 宿主机直接跑（backend/scripts/build_release.sh 的本机模式）
#   · 构建容器内跑（release/build.Dockerfile 镜像，--docker 模式）
#
# 产物平台 = 当前运行环境平台，自动命名：
#   agent-flow-<版本>-<os>-<arch>.zip   如 linux-x86_64 / linux-arm64 / macos-arm64
#
# 参数：
#   $1  版本号（必填）
#   --release      正式构建（license 强制编入 .so）；缺省 dev 构建
set -euo pipefail
cd "$(dirname "$0")/.."   # 仓库根

VERSION="${1:?用法: build_package.sh <版本> [--keys <dir>] [--with-runtime] [--with-wheels]}"
shift || true
RELEASE=0
WITH_RUNTIME=0
WITH_WHEELS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --release) RELEASE=1; shift ;;
    --with-runtime) WITH_RUNTIME=1; shift ;;
    --with-wheels) WITH_WHEELS=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

say() { echo -e "\033[1;36m[build]\033[0m $*"; }
OUT_DIR_LATE=1   # OUT_DIR 依赖 $SUFFIX，移至平台标识段之后定义

# 平台标识（产物命名 + 明示）
OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_NAME="$(uname -m)"
case "$OS_NAME/$ARCH_NAME" in
  linux/x86_64)  PLATFORM_DESC="Linux x86_64（主流服务器）" ;;
  linux/aarch64) PLATFORM_DESC="Linux ARM64（国产化/ARM 服务器）" ;;
  darwin/arm64)  PLATFORM_DESC="macOS Apple Silicon（仅本机/同平台测试用）" ;;
  darwin/x86_64) PLATFORM_DESC="macOS Intel（仅本机/同平台测试用）" ;;
  *)             PLATFORM_DESC="$OS_NAME/$ARCH_NAME" ;;
esac
case "$ARCH_NAME" in x86_64) ARCH_TAG=x86_64 ;; aarch64) ARCH_TAG=arm64 ;; *) ARCH_TAG="$ARCH_NAME" ;; esac
SUFFIX="$OS_NAME-$ARCH_TAG"
OUT_DIR="dist/agent-flow-$VERSION-$SUFFIX"   # 每个 <版本-平台> 独立目录；同 ver-plat rebuild 自动覆盖

# 前提检查（宿主机跑时友好提示；容器内已预装）
command -v npm >/dev/null || { echo "✗ 缺少 npm"; exit 1; }
command -v uv  >/dev/null || { echo "✗ 缺少 uv（https://docs.astral.sh/uv/）"; exit 1; }
command -v zip >/dev/null || { echo "✗ 缺少 zip"; exit 1; }
# Python 解释器选择：容器内已预装 Cython → python3；宿主 → uv 临时带（不污染 venv）
if python3 -c "import Cython" >/dev/null 2>&1; then
  BUILD_PY=(python3)
elif command -v uv >/dev/null; then
  # --python 3.12 显式锚定：uv 自动发现/下载 3.12（pyproject 版本范围可能允许 3.13，
  # 不锚定的话新机器上会选中 3.13——虽有后置校验兜底，直接用对版本更顺）
  BUILD_PY=(uv run --project backend --python 3.12 --with cython --with setuptools python)
else
  echo "✗ 缺少 Cython（容器镜像已预装；宿主需安装 uv 或 pip3 install cython setuptools）" >&2; exit 1
fi
# 编译解释器必须是 3.12：Cython 产物 ABI 标签由编译时的解释器决定——
# 在 3.13 上跑会静默产出 cpython-313 的 .so，客户 3.12 环境直接跑不了。
if ! "${BUILD_PY[@]}" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
  echo "✗ 编译解释器不是 Python 3.12（${BUILD_PY[*]}）——产物 ABI 将与交付目标不符。" >&2
  echo "  3.13 编出来的是 cpython-313 的 .so，客户 3.12 环境无法加载。" >&2
  echo "  请用 Python 3.12（uv: uv python install 3.12）或走 Docker 构建（镜像已锚定 3.12）。" >&2
  exit 1
fi

[ "$RELEASE" = 0 ] && echo "[build] ⚠ 未加 --release → dev 构建（license 不强制，仅内部用）" >&2
say "目标平台: $PLATFORM_DESC"

# ── 1) 前端 ───────────────────────────────────────────────────────────
say "[1/5] 前端构建…"
# --registry 国内镜像：官方源经代理时常 ECONNRESET（曾连续构建失败于此）；
# 不用 --silent：npm ci 失败原因必须可见（曾被静默吞掉，极难排查）
NPM_CI=(npm ci --registry=https://registry.npmmirror.com --no-audit --no-fund)
(cd frontend-studio  && "${NPM_CI[@]}" && npm run build)
(cd frontend-client && "${NPM_CI[@]}" && npm run build)

# ── 2) 后端 .so（Cython）──────────────────────────────────────────────
say "[2/5] Cython 编译（412 模块 → .so）…"
KEY_ARGS=()
[ "$RELEASE" = 1 ] && KEY_ARGS=(--release)
rm -rf dist/compiled-release
"${BUILD_PY[@]}" backend/scripts/build_compiled.py --out dist/compiled-release "${KEY_ARGS[@]+"${KEY_ARGS[@]}"}"

# ── 3) runtime（独立 Python + 全依赖 + harness 普通安装）─────────────
say "[3/5] 依赖清单与运行环境…"
# 依赖锁定清单（随包分发：客户 ./agent-flow setup 一条命令安装）
# 先写临时位置——组装段会 rm -rf 整个 OUT_DIR（每版本独立目录）
REQ_TMP="$(mktemp /tmp/af-req.XXXXXX)"
(cd backend && uv export --frozen --no-dev --no-emit-project --no-emit-workspace -q -o "$REQ_TMP")
REQ_LOCK="$REQ_TMP"
(cd backend && uv export --frozen --no-dev --no-emit-project --no-emit-workspace -q -o "$REQ_LOCK.tmp")
grep -vE "agent.flow.harness|packages/harness" "$REQ_LOCK.tmp" > "$REQ_LOCK" || true
rm -f "$REQ_LOCK.tmp"

if [ "$WITH_RUNTIME" = 1 ] || [ "$WITH_WHEELS" = 1 ]; then
  uv python install 3.12
  PYINSTALL="$(uv python find 3.12)"
fi
# 捆绑 runtime（可选：客户免装 Python）
if [ "$WITH_RUNTIME" = 1 ]; then
  say "      捆绑 runtime（--with-runtime）…"
  RUNTIME="$OUT_DIR/runtime"
  rm -rf "$RUNTIME"
  cp -a "$PYINSTALL" "$RUNTIME"
  "$RUNTIME/bin/python" -m pip install -q --break-system-packages --no-cache-dir -r "$OUT_DIR/requirements.lock.txt"
  "$RUNTIME/bin/python" -m pip install -q --break-system-packages --no-cache-dir "$PWD/backend/packages/harness"
  find "$RUNTIME/lib" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$RUNTIME/lib" -type f \( -name "*.pyc" -o -name "*.pyi" \) -delete 2>/dev/null || true
  find "$RUNTIME/lib" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + 2>/dev/null || true
  "$RUNTIME/bin/python" -c "import fastapi, celery, agent_flow_harness" || { echo "✗ runtime 自检失败" >&2; exit 1; }
else
  say "      默认形态：客户自备 Python 3.12（./agent-flow setup 一条命令装依赖）"
fi
# 离线 wheel 包（可选：内网客户首次安装用，独立 zip）
if [ "$WITH_WHEELS" = 1 ]; then
  say "      导出离线 wheelhouse（--with-wheels）…"
  WHEEL_DIR="dist/wheels-$SUFFIX"
  rm -rf "$WHEEL_DIR" && mkdir -p "$WHEEL_DIR"
  "$PYINSTALL/bin/python" -m pip download -r "$OUT_DIR/requirements.lock.txt" -d "$WHEEL_DIR" --quiet
  (cd dist && zip -qr "agent-flow-wheels-$VERSION-$SUFFIX.zip" "$(basename "$WHEEL_DIR")")
  say "      离线依赖包: dist/agent-flow-wheels-${VERSION}-${SUFFIX}.zip"
fi

# ── 4) 组装交付文件夹 ────────────────────────────────────────────────
say "[4/5] 组装交付文件夹…"
# 全清再建，彻底杜绝同 ver-plat re-build 时旧 .so/前端/runtime 残留
# 提示（不阻断）：产物目录若含运行痕迹（.venv/license/数据），构建会全清。
# 正规流程 = 新版本目录 + 旧现场 ./agent-flow upgrade；若只是图方便在产物目录
# 直接跑（纯测试无宝贵数据），此提示可忽略。
if [ -e "$OUT_DIR/.venv" ] || [ -e "$OUT_DIR/etc/jasper.identity" ]; then
  echo "[i] $OUT_DIR 含 .venv / 授权——构建将整目录重建，这些会丢失（测试现场请用 upgrade 流程或另存目录）" >&2
fi
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/app" "$OUT_DIR/web" "$OUT_DIR/etc"
cp -a dist/compiled-release/app "$OUT_DIR/app"
rm -rf "$OUT_DIR/app/app/cli" && cp -a backend/app/cli "$OUT_DIR/app/app/cli"
mkdir -p "$OUT_DIR/app/agent_flow_harness"
cp -a dist/compiled-release/agent_flow_harness/. "$OUT_DIR/app/agent_flow_harness/"
cp -a frontend-studio/dist/. "$OUT_DIR/web/"
cp -a frontend-client/dist/. "$OUT_DIR/web/client/"
cp release/agent-flow "$OUT_DIR/agent-flow" && chmod +x "$OUT_DIR/agent-flow"
cp -a release/infra "$OUT_DIR/infra"
cp release/env.template "$OUT_DIR/env.template"
grep -vE "agent.flow.harness|packages/harness" "$REQ_TMP" > "$OUT_DIR/requirements.lock.txt" || true
rm -f "$REQ_TMP"
cp release/env.template "$OUT_DIR/etc/agent-flow.env"
cp LICENSE "$OUT_DIR/"
[ -f NOTICE ] && cp NOTICE "$OUT_DIR/"
cp release/DEPLOY.md "$OUT_DIR/部署指南.md"
cp release/Dockerfile release/docker-compose.yml release/Caddyfile "$OUT_DIR/"

# ── 5) zip + 校验和 ──────────────────────────────────────────────────
say "[5/5] 打包…"
ZIP="agent-flow-$VERSION-$SUFFIX.zip"
rm -f "dist/$ZIP" "dist/$ZIP.sha256"
(cd dist && zip -qr "$ZIP" "$(basename "$OUT_DIR")" -x "*.DS_Store")
SHA_CMD="$(command -v sha256sum || command -v shasum || true)"
(cd dist && ${SHA_CMD:+$SHA_CMD -a 256} "$ZIP" > "$ZIP.sha256" 2>/dev/null || ${SHA_CMD:+$SHA_CMD} "$ZIP" > "$ZIP.sha256")
say "完成: dist/${ZIP}（平台: ${PLATFORM_DESC}）"
say "客户使用: 解压 → 看包内《部署指南.md》→ ./agent-flow start"
