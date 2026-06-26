#!/bin/bash
# Agent Flow 启动脚本
# 启动后端、前端

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend-studio"

# PID文件目录
PID_DIR="$PROJECT_ROOT/.pids"
mkdir -p "$PID_DIR"

# 日志目录
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

# 检查依赖服务
check_dependencies() {
    echo -e "${BLUE}检查依赖服务...${NC}"

    # 检查MongoDB
    if ! pgrep -x "mongod" > /dev/null; then
        echo -e "${YELLOW}⚠️  MongoDB未运行，尝试启动...${NC}"
        if command -v brew &> /dev/null && brew services list | grep -q "mongodb-community"; then
            brew services start mongodb-community
            sleep 2
        else
            echo -e "${RED}❌ MongoDB未安装或未配置，请手动启动${NC}"
            return 1
        fi
    else
        echo -e "${GREEN}✓ MongoDB运行中${NC}"
    fi

    # 检查Redis
    if ! pgrep -x "redis-server" > /dev/null; then
        echo -e "${YELLOW}⚠️  Redis未运行，尝试启动...${NC}"
        if command -v brew &> /dev/null && brew services list | grep -q "redis"; then
            brew services start redis
            sleep 2
        else
            echo -e "${RED}❌ Redis未安装或未配置，请手动启动${NC}"
            return 1
        fi
    else
        echo -e "${GREEN}✓ Redis运行中${NC}"
    fi

    return 0
}

# 启动后端
start_backend() {
    echo -e "${BLUE}启动后端服务...${NC}"

    if [ -f "$PID_DIR/backend.pid" ] && kill -0 "$(cat "$PID_DIR/backend.pid")" 2>/dev/null; then
        echo -e "${YELLOW}⚠️  后端已在运行 (PID: $(cat "$PID_DIR/backend.pid"))${NC}"
        return 0
    fi

    cd "$BACKEND_DIR"

    # 使用uvicorn启动
    nohup uv run uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --reload \
        > "$LOG_DIR/backend.log" 2>&1 &

    echo $! > "$PID_DIR/backend.pid"
    echo -e "${GREEN}✓ 后端已启动 (PID: $!)${NC}"
    echo -e "${BLUE}  日志: $LOG_DIR/backend.log${NC}"
}

# 启动前端
start_frontend() {
    echo -e "${BLUE}启动前端服务...${NC}"

    if [ -f "$PID_DIR/frontend.pid" ] && kill -0 "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null; then
        echo -e "${YELLOW}⚠️  前端已在运行 (PID: $(cat "$PID_DIR/frontend.pid"))${NC}"
        return 0
    fi

    cd "$FRONTEND_DIR"

    # 检查node_modules
    if [ ! -d "node_modules" ]; then
        echo -e "${YELLOW}安装前端依赖...${NC}"
        npm install
    fi

    # 使用vite dev启动
    nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &

    echo $! > "$PID_DIR/frontend.pid"
    echo -e "${GREEN}✓ 前端已启动 (PID: $!)${NC}"
    echo -e "${BLUE}  日志: $LOG_DIR/frontend.log${NC}"
}

# 主函数
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Agent Flow 启动脚本${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    # 检查依赖
    if ! check_dependencies; then
        echo -e "${RED}依赖服务检查失败，请手动启动MongoDB和Redis${NC}"
        exit 1
    fi

    echo ""

    # 启动服务
    start_backend
    sleep 2

    start_frontend

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  所有服务已启动！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${BLUE}访问地址:${NC}"
    echo -e "  后端API:   ${GREEN}http://localhost:8000${NC}"
    echo -e "  API文档:   ${GREEN}http://localhost:8000/docs${NC}"
    echo -e "  前端界面:  ${GREEN}http://localhost:3000${NC}"
    echo ""
    echo -e "${YELLOW}停止服务: ./scripts/stop.sh${NC}"
    echo ""
}

main "$@"
