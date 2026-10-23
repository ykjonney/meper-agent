#!/usr/bin/env bash
# build_release.sh —— 交付包构建入口：检测环境 → 提示选择 → 全流程构建。
#
# 用法：
#   backend/scripts/build_release.sh <版本> [--release] [选项]
#
#   交互模式（不带选项）：展示本机/Docker 两种方式与各自的目标平台，让你选择
#   --release                 正式构建（license 强制；缺省 dev 构建）
#   选项（CI/脚本用，跳过交互）：
#     --local                   本机构建（产物平台 = 本机平台）
#     --docker [--platform P]   Docker 构建（P = linux/amd64 | linux/arm64，默认 amd64）
#
# 产物：dist/agent-flow-<版本>-<os>-<arch>.zip + .sha256（平台名在文件名里，一目了然）
set -euo pipefail
cd "$(dirname "$0")/../.."   # 仓库根

VERSION="${1:?用法: build_release.sh <版本> [--release] [--local|--docker [--platform P]]}"
shift || true
RELEASE=0
MODE=""
DOCKER_PLATFORM="linux/amd64"
while [ $# -gt 0 ]; do
  case "$1" in
    --release)   RELEASE=1; shift ;;
    --local)    MODE=local; shift ;;
    --docker)   MODE=docker; shift ;;
    --platform) DOCKER_PLATFORM="${2:?}"; shift 2 ;;
    *) echo "未知参数: $1（可用: --release | --local | --docker | --platform P）" >&2; exit 1 ;;
  esac
done

os_name() { uname -s | tr '[:upper:]' '[:lower:]'; }
arch_name() { uname -m | sed 's/aarch64/arm64/'; }
have_docker() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

KEY_ARG=()
KEY_NOTE="dev 构建（license 不强制，仅内部用）"
if [ "$RELEASE" = 1 ]; then
  KEY_ARG=(--release)
  KEY_NOTE="正式构建（license 强制）"
fi

echo "════════════════════════════════════════════════════════"
echo " Agent Flow 交付包构建   版本 $VERSION"
echo " 构建: $KEY_NOTE"
echo "════════════════════════════════════════════════════════"

# ── 模式选择（未指定时交互）──────────────────────────────────────────
if [ -z "$MODE" ]; then
  LOCAL_DESC="$(os_name)-$(arch_name)"
  case "$LOCAL_DESC" in
    linux-x86_64) LOCAL_NOTE="= 客户主流平台，可直接交付" ;;
    linux-arm64)  LOCAL_NOTE="= Linux ARM64 平台" ;;
    *)            LOCAL_NOTE="⚠ 本机平台包不能给 Linux 服务器客户使用（仅本机测试）" ;;
  esac
  echo ""
  echo " 请选择构建方式："
  echo "   [1] 本机构建      产物平台: $LOCAL_DESC  $LOCAL_NOTE"
  if have_docker; then
    echo "   [2] Docker 构建   可选平台: linux/amd64（客户服务器主流，默认）/ linux/arm64"
    echo "       （Apple Silicon 上编 amd64 为 Rosetta 模拟，速度较慢）"
  else
    echo "   [2] Docker 构建   ✗ 当前不可用（未安装或未启动 Docker）"
  fi
  printf " 选择 [1/2]（回车=1 本机）: "
  read -r choice || choice=1
  case "$choice" in
    2)
      have_docker || { echo "✗ Docker 不可用，请先安装/启动，或选本机构建" >&2; exit 1; }
      MODE=docker
      printf " Docker 平台 [amd64/arm64]（回车=amd64）: "
      read -r p || p=""
      [ -n "$p" ] && DOCKER_PLATFORM="linux/$p"
      ;;
    *) MODE=local ;;
  esac
fi

# ── 执行 ─────────────────────────────────────────────────────────────
if [ "$MODE" = local ]; then
  echo "▶ 本机构建，产物平台: $(os_name)-$(arch_name)"
  exec bash release/build_package.sh "$VERSION" "${KEY_ARG[@]+"${KEY_ARG[@]}"}"
fi

# Docker 构建
echo "▶ Docker 构建，目标平台: $DOCKER_PLATFORM"
have_docker || { echo "✗ Docker 不可用" >&2; exit 1; }
case "$DOCKER_PLATFORM" in
  linux/amd64) PLATFORM_NOTE="Linux x86_64（客户服务器主流）" ;;
  linux/arm64) PLATFORM_NOTE="Linux ARM64（国产化/ARM 服务器）" ;;
  *) echo "✗ 不支持的平台: $DOCKER_PLATFORM（可选 linux/amd64 | linux/arm64）" >&2; exit 1 ;;
esac
echo "  $PLATFORM_NOTE"

BUILDER_IMAGE=agent-flow-builder:latest
echo "▶ 准备构建镜像 ${BUILDER_IMAGE}（首次约 2-3 分钟，之后缓存复用）…"
docker build --platform "$DOCKER_PLATFORM" -f release/build.Dockerfile -t "$BUILDER_IMAGE" release/

echo "▶ 容器内全流程构建（前端 + Cython + runtime + 打包）…"
docker run --rm --platform "$DOCKER_PLATFORM" \
  -v "$PWD:/src" -w /src \
  -e UV_CACHE_DIR=/tmp/uv-cache -e npm_config_cache=/tmp/npm-cache \
  "$BUILDER_IMAGE" \
  bash release/build_package.sh "$VERSION" "${KEY_ARG[@]+"${KEY_ARG[@]}"}"

echo "════════════════════════════════════════════════════════"
echo " 完成。产物在 dist/（文件名含平台标识）："
ls -lh dist/agent-flow-*.zip 2>/dev/null | tail -3 || true
