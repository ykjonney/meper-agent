# agent-flow 构建镜像——一条命令全流程构建正式交付包的运行环境。
# 组件：Python 3.12 + Node 22 + uv + gcc（Cython 编译）+ zip。
# 由 backend/scripts/build_release.sh 自动构建/复用（tag: agent-flow-builder）。

# ── Node 22（vite 构建前端用）────────────────────────────────────────
FROM node:22-bookworm AS node

# ── 基底：Python 3.12（bookworm = glibc 2.36，产物兼容 Debian 12+/多数发行版）──
FROM python:3.12-bookworm

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# uv（runtime 捆绑 / 依赖导出用）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# 编译与打包工具链
# Debian 源换国内镜像：deb.debian.org（Fastly CDN）经代理常 502，曾致构建失败
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends gcc g++ make zip unzip patchelf \
       ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ cython setuptools cryptography

WORKDIR /src
