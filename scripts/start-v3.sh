#!/bin/bash
# CAD3Dify V3 启动脚本
# 使用 uv 虚拟环境启动后端 + 前端开发服务器
#
# 用法:
#   ./scripts/start-v3.sh          # 启动后端 + 前端
#   ./scripts/start-v3.sh backend  # 仅启动后端
#   ./scripts/start-v3.sh frontend # 仅启动前端
#   ./scripts/start-v3.sh stop     # 停止所有服务

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

BACKEND_PORT=8780
FRONTEND_PORT=3001
BACKEND_PID_FILE="$PROJECT_ROOT/.backend.pid"
FRONTEND_PID_FILE="$PROJECT_ROOT/.frontend.pid"

stop_services() {
    echo "⏹ 停止服务..."
    if [ -f "$BACKEND_PID_FILE" ]; then
        kill "$(cat "$BACKEND_PID_FILE")" 2>/dev/null && echo "  后端已停止" || echo "  后端未在运行"
        rm -f "$BACKEND_PID_FILE"
    fi
    if [ -f "$FRONTEND_PID_FILE" ]; then
        kill "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null && echo "  前端已停止" || echo "  前端未在运行"
        rm -f "$FRONTEND_PID_FILE"
    fi
    # 清理残留进程
    pkill -f "uvicorn backend.main:app.*$BACKEND_PORT" 2>/dev/null || true
    pkill -f "vite.*$FRONTEND_PORT" 2>/dev/null || true
}

start_backend() {
    echo "🚀 启动后端 (uv + uvicorn :$BACKEND_PORT)..."
    uv run python -m uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
    echo $! > "$BACKEND_PID_FILE"
    echo "  后端 PID: $(cat "$BACKEND_PID_FILE")"
}

start_frontend() {
    echo "🚀 启动前端 (vite :$FRONTEND_PORT)..."
    cd "$PROJECT_ROOT/frontend"
    npm run dev &
    echo $! > "$FRONTEND_PID_FILE"
    echo "  前端 PID: $(cat "$FRONTEND_PID_FILE")"
    cd "$PROJECT_ROOT"
}

wait_for_backend() {
    echo -n "  等待后端就绪"
    for i in $(seq 1 30); do
        if curl -s "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
            echo " ✓"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    echo " ✗ (超时)"
    return 1
}

MODE="${1:-all}"

case "$MODE" in
    stop)
        stop_services
        ;;
    backend)
        stop_services
        start_backend
        wait_for_backend
        echo ""
        echo "✅ 后端: http://localhost:$BACKEND_PORT"
        ;;
    frontend)
        stop_services
        start_frontend
        echo ""
        echo "✅ 前端: http://localhost:$FRONTEND_PORT"
        ;;
    all|*)
        stop_services
        start_backend
        wait_for_backend
        start_frontend
        echo ""
        echo "✅ 后端: http://localhost:$BACKEND_PORT"
        echo "✅ 前端: http://localhost:$FRONTEND_PORT"
        echo ""
        echo "按 Ctrl+C 停止，或运行 ./scripts/start-v3.sh stop"
        wait
        ;;
esac
