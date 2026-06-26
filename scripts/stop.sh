#!/bin/bash
# Agent Flow 停止脚本
# 停止后端、前端

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

# PID文件目录
PID_DIR="$PROJECT_ROOT/.pids"

# 停止服务的函数
stop_service() {
    local service_name=$1
    local pid_file=$2

    if [ ! -f "$pid_file" ]; then
        echo -e "${YELLOW}⚠️  $service_name 未运行 (PID文件不存在)${NC}"
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        echo -e "${YELLOW}⚠️  $service_name 未运行 (进程不存在)${NC}"
        rm -f "$pid_file"
        return 0
    fi

    echo -e "${BLUE}停止 $service_name (PID: $pid)...${NC}"

    # 先尝试优雅停止
    kill "$pid" 2>/dev/null

    # 等待进程退出（最多10秒）
    for i in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${GREEN}✓ $service_name 已停止${NC}"
            rm -f "$pid_file"
            return 0
        fi
        sleep 1
    done

    # 如果还在运行，强制终止
    echo -e "${YELLOW}⚠️  优雅停止失败，强制终止...${NC}"
    kill -9 "$pid" 2>/dev/null
    sleep 1

    if kill -0 "$pid" 2>/dev/null; then
        echo -e "${RED}❌ 无法停止 $service_name${NC}"
        return 1
    fi

    echo -e "${GREEN}✓ $service_name 已强制停止${NC}"
    rm -f "$pid_file"
    return 0
}

# 停止所有Python进程（包括uvicorn的子进程）
stop_python_processes() {
    echo -e "${BLUE}清理Python进程...${NC}"

    # 查找并终止所有uvicorn进程
    pkill -f "uvicorn app.main:app" 2>/dev/null || true

    echo -e "${GREEN}✓ Python进程已清理${NC}"
}

# 停止Node进程
stop_node_processes() {
    echo -e "${BLUE}清理Node进程...${NC}"

    # 查找并终止vite进程
    pkill -f "vite --port=3000" 2>/dev/null || true

    echo -e "${GREEN}✓ Node进程已清理${NC}"
}

# 主函数
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Agent Flow 停止脚本${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    # 停止服务
    stop_service "后端服务" "$PID_DIR/backend.pid"
    stop_service "前端服务" "$PID_DIR/frontend.pid"

    echo ""

    # 清理子进程
    stop_python_processes
    stop_node_processes

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  所有服务已停止！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

main "$@"
