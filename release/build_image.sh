#!/usr/bin/env bash
# build_image.sh —— 构建镜像并（可选）推送私有仓库（Harbor 等）。
#
# 两种镜像：
#   app     = 编译镜像（agent-flow-app）：Cython .so + license 强制，源交付形态。
#             前置：dist/agent-flow-<版本>-linux-x86_64/ 已存在（make build-release 产物）。
#   deploy  = 开发镜像三件套（agent-flow-{backend,caddy,sandbox}）：.py 源码直跑，
#             license 不强制，供 dev/test 环境。前端 dist 构建进 caddy 镜像。
#
# tag 方案（每次构建打 2~3 个）：
#   <版本>.YYYYMMDD-HHMM   快照，永不覆盖——复现/回滚/审计用（Harbor 可设 immutable）
#   <版本>                 指针，指向本次——环境文件写它即"永远最新"（更新只需 pull）
#   latest                 可选（--latest），正式线"最新"指针
#
# 用法：
#   release/build_image.sh <app|deploy> <版本> --registry <harbor地址/项目> \
#       [--push] [--latest] [--platform linux/amd64]
#   推送认证：先探测免密（已 docker login），否则用 DOCKER_USER/DOCKER_PASS 兜底登录。
#
# 示例：
#   make build-image-app    VERSION=1.0.8 REGISTRY=harbor.corp/af PUSH=1 LATEST=1
#   make build-image-deploy VERSION=1.0.8-dev REGISTRY=harbor.corp/af PUSH=1
set -euo pipefail
cd "$(dirname "$0")/.."

TYPE="${1:?用法: build_image.sh <app|deploy> <版本> --registry <harbor/项目> [--push] [--latest] [--platform P]}"
VERSION="${2:?缺少版本参数（dev 线建议形如 1.0.8-dev）}"
shift 2 || true

REGISTRY="" PUSH=0 LATEST=0 PLATFORM="linux/amd64"
while [ $# -gt 0 ]; do
  case "$1" in
    --registry)  REGISTRY="${2:?}"; shift 2 ;;
    --push)      PUSH=1; shift ;;
    --latest)    LATEST=1; shift ;;
    --platform)  PLATFORM="${2:?}"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done
[ -n "$REGISTRY" ] || { echo "✗ 缺少 --registry <harbor地址/项目>（如 harbor.corp.local/agent-flow）" >&2; exit 1; }
command -v docker >/dev/null || { echo "✗ 缺少 docker" >&2; exit 1; }

TS="$(date +%Y%m%d-%H%M)"
say() { echo -e "\033[1;36m[image]\033[0m $*"; }

# 一个镜像的构建 + 本地/远端双 tag。参数：镜像名 context dockerfile [extra build args...]
_build_one() {
  local name="$1" ctx="$2" df="$3"; shift 3
  say "构建 ${name}（${df}）…"
  docker build --platform "$PLATFORM" -f "$df" -t "${name}:${VERSION}.${TS}" -t "${name}:${VERSION}" "$ctx" "$@"
  docker tag "${name}:${VERSION}.${TS}" "${REGISTRY}/${name}:${VERSION}.${TS}"
  docker tag "${name}:${VERSION}"       "${REGISTRY}/${name}:${VERSION}"
  local tags=("${REGISTRY}/${name}:${VERSION}.${TS}" "${REGISTRY}/${name}:${VERSION}")
  if [ "$LATEST" = 1 ]; then
    docker tag "${name}:${VERSION}" "${REGISTRY}/${name}:latest"
    tags+=("${REGISTRY}/${name}:latest")
  fi
  PUSH_TAGS+=("${tags[@]}")
  printf '  %-40s %s\n' "${name}" "${VERSION}.${TS}  ${VERSION}$( [ "$LATEST" = 1 ] && echo '  latest' )"
}

PUSH_TAGS=()
case "$TYPE" in
  app)
    # 编译镜像：构建上下文 = 交付产物目录（含 .so/app、Dockerfile、requirements.lock.txt）
    OUT_DIR="dist/agent-flow-${VERSION}-linux-x86_64"
    [ -d "$OUT_DIR/app" ] || {
      echo "✗ 缺少 ${OUT_DIR}/（编译镜像从交付产物构建）" >&2
      echo "  先执行: make build-release VERSION=${VERSION} RELEASE=1 --docker" >&2
      exit 1
    }
    _build_one agent-flow-app "$OUT_DIR" "$OUT_DIR/Dockerfile"
    ;;
  deploy)
    # 开发三件套：源码镜像（backend）、前端镜像（caddy）、沙盒（lite）
    [ -f backend/Dockerfile ] && [ -f deploy/Dockerfile.caddy ] && [ -f deploy/Dockerfile.sandbox ] \
      || { echo "✗ 缺少 backend/Dockerfile / deploy/Dockerfile.{caddy,sandbox}" >&2; exit 1; }
    _build_one agent-flow-backend backend backend/Dockerfile
    _build_one agent-flow-caddy   .       deploy/Dockerfile.caddy
    _build_one agent-flow-sandbox .       deploy/Dockerfile.sandbox --target lite
    ;;
  *) echo "✗ 未知类型: $TYPE（app | deploy）" >&2; exit 1 ;;
esac

echo
say "本次构建 tag 清单（registry: ${REGISTRY}）："
printf '  %s\n' "${PUSH_TAGS[@]}"

if [ "$PUSH" = 1 ]; then
  LOGGED=0
  for t in "${PUSH_TAGS[@]}"; do
    say "push ${t}"
    if ! docker push "$t"; then
      # 免密不可用：DOCKER_USER/DOCKER_PASS 兜底登录一次后重试
      if [ "$LOGGED" = 0 ] && [ -n "${DOCKER_USER:-}" ] && [ -n "${DOCKER_PASS:-}" ]; then
        say "免密推送不可用，用 DOCKER_USER 登录 ${REGISTRY%%/*} …"
        echo "$DOCKER_PASS" | docker login "${REGISTRY%%/*}" -u "$DOCKER_USER" --password-stdin
        LOGGED=1
        docker push "$t"
      else
        echo "✗ 推送失败：先 docker login ${REGISTRY%%/*}，或设 DOCKER_USER/DOCKER_PASS" >&2
        exit 1
      fi
    fi
  done
  say "推送完成。环境文件写指针 tag（${REGISTRY}/<name>:${VERSION}）即永远最新；快照 tag ${VERSION}.${TS} 可回滚。"
else
  say "未推远端（--push 开启推送）。手动推："
  printf '  docker push %s\n' "${PUSH_TAGS[@]}"
fi
