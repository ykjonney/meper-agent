#!/bin/bash
# Agent Flow 状态查看脚本

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

# 检查服务状态
check_service() {
    local service_name=$1
    local pid_file=$2
    local port=$3

    if [ ! -f "$pid_file" ]; then
        echo -e "  $service_name: ${RED}未运行${NC} (PID文件不存在)"
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        echo -e "  $service_name: ${RED}未运行${NC} (进程不存在)"
        rm -f "$pid_file"
        return 0
    fi

    # 检查端口
    if [ -n "$port" ]; then
        if lsof -i :"$port" -sTCP:LISTEN | grep -q "$pid"; then
            echo -e "  $service_name: ${GREEN}运行中${NC} (PID: $pid, 端口: $port)"
        else
            echo -e "  $service_name: ${YELLOW}运行中但未监听端口${NC} (PID: $pid)"
        fi
    else
        echo -e "  $service_name: ${GREEN}运行中${NC} (PID: $pid)"
    fi

    return 0
}

# 检查依赖服务
check_dependency() {
    local service_name=$1
    local process_name=$2
    local port=$3

    if pgrep -x "$process_name" > /dev/null; then
        echo -e "  $service_name: ${GREEN}运行中${NC}"
        return 0
    else
        echo -e "  $service_name: ${RED}未运行${NC}"
        return 0  # 不返回错误，继续执行
    fi
}

# 主函数
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Agent Flow 状态${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""

    echo -e "${BLUE}依赖服务:${NC}"
    check_dependency "MongoDB" "mongod" 27017
    check_dependency "Redis" "redis-server" 6379
    echo ""

    echo -e "${BLUE}应用服务:${NC}"
    check_service "后端 (FastAPI)" "$PID_DIR/backend.pid" 8000
    check_service "前端 (Vite)" "$PID_DIR/frontend.pid" 3000
    echo ""

    # 显示日志文件信息
    echo -e "${BLUE}日志文件:${NC}"
    if [ -f "$PROJECT_ROOT/logs/backend.log" ]; then
        local backend_lines=$(wc -l < "$PROJECT_ROOT/logs/backend.log")
        echo -e "  后端: $PROJECT_ROOT/logs/backend.log ($backend_lines 行)"
    fi
    if [ -f "$PROJECT_ROOT/logs/frontend.log" ]; then
        local frontend_lines=$(wc -l < "$PROJECT_ROOT/logs/frontend.log")
        echo -e "  前端: $PROJECT_ROOT/logs/frontend.log ($frontend_lines 行)"
    fi
    echo ""
}

main "$@"
