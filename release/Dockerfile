# Agent Flow（.so 交付包）Docker 部署模板——供偏好容器化运维的客户。
# 构建上下文 = 解压后的 agent-flow 包目录：
#   cd agent-flow && docker build -f Dockerfile -t agent-flow-app:1.0.0 .
# 运行：见 docker-compose.yml（caddy + app + worker + beat + 3 DB）

FROM python:3.12-slim

# .so 依赖的运行库（cv2/onnxruntime 等原生扩展需要）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/agent-flow

# 应用（仅必需文件：.so 代码 + 依赖清单 + 启动器 + 许可证）
COPY app/ ./app/
COPY requirements.lock.txt LICENSE agent-flow ./

# 依赖（requirements.lock.txt 与交付版本锁定一致）
RUN python -m pip install --no-cache-dir -r requirements.lock.txt

# 静态托管由 caddy 容器（compose）接管；本镜像只跑 API+WS。
# 同一镜像被 app/worker/beat 三个 service 复用，仅 command 不同。
ENV AGENT_FLOW_SERVE_STATIC=false \
    PYTHONPATH=/opt/agent-flow/app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -sf http://127.0.0.1:8000/health || exit 1

# 默认起 uvicorn；worker/beat 在 compose 中用 command: 覆盖
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
