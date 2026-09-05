#!/usr/bin/env bash
# 安防综合管理平台 —— 统一启停脚本
#
# 用法:
#   ./start.sh            # 启动前后端（等同 start）
#   ./start.sh start      # 启动前后端
#   ./start.sh stop       # 停止前后端
#   ./start.sh restart    # 重启前后端
#   ./start.sh status     # 查看运行状态
#   ./start.sh logs       # 实时查看后端+前端日志
#
# 说明:
#   - 后端从 backend/ 内以 `python3 main.py` 运行(本机无 `python`,固定用 python3),监听 0.0.0.0:8000
#   - 前端以 vite 运行,监听 0.0.0.0:5173(vite.config.js 已配 host)
#   - 日志写入 logs/backend.log 与 logs/frontend.log,PID 写入 logs/*.pid

set -u

# ── 路径与常量 ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
LOG_DIR="$SCRIPT_DIR/logs"

BACKEND_PORT=8000
FRONTEND_PORT=5173

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID="$LOG_DIR/backend.pid"
FRONTEND_PID="$LOG_DIR/frontend.pid"

# ── 颜色输出 ────────────────────────────────────────────────
c_info()  { printf "\033[36m[INFO]\033[0m  %s\n" "$*"; }
c_ok()    { printf "\033[32m[ OK ]\033[0m  %s\n" "$*"; }
c_warn()  { printf "\033[33m[WARN]\033[0m  %s\n" "$*"; }
c_err()   { printf "\033[31m[FAIL]\033[0m  %s\n" "$*"; }

# ── 工具函数 ────────────────────────────────────────────────
# 释放指定端口上正在监听的进程
kill_port() {
    local port="$1"
    local pids
    pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$pids" ]; then
        c_warn "端口 $port 被占用(PID: $pids),正在结束旧进程…"
        # shellcheck disable=SC2086
        kill $pids 2>/dev/null || true
        sleep 1
        pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
        if [ -n "$pids" ]; then
            # shellcheck disable=SC2086
            kill -9 $pids 2>/dev/null || true
        fi
    fi
}

# 端口是否有服务在监听
port_listening() {
    lsof -ti "tcp:$1" -sTCP:LISTEN >/dev/null 2>&1
}

# 定位 vite 可执行方式:优先 npm，其次 node_modules 里的 vite.js
frontend_cmd() {
    if command -v npm >/dev/null 2>&1; then
        echo "npm run dev -- --host 0.0.0.0 --port $FRONTEND_PORT"
    elif [ -f "$FRONTEND_DIR/node_modules/vite/bin/vite.js" ]; then
        echo "node node_modules/vite/bin/vite.js --host 0.0.0.0 --port $FRONTEND_PORT"
    else
        echo ""
    fi
}

# ── 依赖预检 ────────────────────────────────────────────────
preflight() {
    local ok=1
    if ! command -v python3 >/dev/null 2>&1; then
        c_err "未找到 python3,请先安装 Python 3。"; ok=0
    fi
    if ! command -v node >/dev/null 2>&1; then
        c_err "未找到 node,请先安装 Node.js。"; ok=0
    fi
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        c_warn "前端依赖未安装,正在执行 npm install …"
        ( cd "$FRONTEND_DIR" && npm install ) || { c_err "npm install 失败。"; ok=0; }
    fi
    [ "$ok" = 1 ]
}

# ── 启动 ────────────────────────────────────────────────────
start_backend() {
    if port_listening "$BACKEND_PORT"; then
        c_warn "后端端口 $BACKEND_PORT 已在监听,跳过启动(如需重启用 restart)。"
        return 0
    fi
    c_info "启动后端(python3 main.py)…"
    ( cd "$BACKEND_DIR" && nohup python3 main.py > "$BACKEND_LOG" 2>&1 & echo $! > "$BACKEND_PID" )
    sleep 3
    if port_listening "$BACKEND_PORT"; then
        c_ok "后端已启动 → http://localhost:$BACKEND_PORT  (PID $(cat "$BACKEND_PID" 2>/dev/null))"
    else
        c_err "后端启动失败,请查看日志:$BACKEND_LOG"
        tail -n 15 "$BACKEND_LOG" 2>/dev/null
        return 1
    fi
}

start_frontend() {
    if port_listening "$FRONTEND_PORT"; then
        c_warn "前端端口 $FRONTEND_PORT 已在监听,跳过启动(如需重启用 restart)。"
        return 0
    fi
    local cmd; cmd="$(frontend_cmd)"
    if [ -z "$cmd" ]; then
        c_err "找不到 npm 或前端未安装 vite,无法启动前端。"
        return 1
    fi
    c_info "启动前端($cmd)…"
    ( cd "$FRONTEND_DIR" && nohup $cmd > "$FRONTEND_LOG" 2>&1 & echo $! > "$FRONTEND_PID" )
    sleep 4
    if port_listening "$FRONTEND_PORT"; then
        c_ok "前端已启动 → http://localhost:$FRONTEND_PORT  (PID $(cat "$FRONTEND_PID" 2>/dev/null))"
    else
        c_err "前端启动失败,请查看日志:$FRONTEND_LOG"
        tail -n 15 "$FRONTEND_LOG" 2>/dev/null
        return 1
    fi
}

do_start() {
    mkdir -p "$LOG_DIR"
    preflight || { c_err "依赖预检未通过,已中止。"; exit 1; }
    start_backend
    start_frontend
    echo
    c_info "本机访问:前端 http://localhost:$FRONTEND_PORT  |  后端 API 文档 http://localhost:$BACKEND_PORT/docs"
    local ip; ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
    [ -n "$ip" ] && c_info "同网段访问:http://$ip:$FRONTEND_PORT"
}

# ── 停止 ────────────────────────────────────────────────────
do_stop() {
    c_info "停止前端与后端…"
    kill_port "$FRONTEND_PORT"
    kill_port "$BACKEND_PORT"
    rm -f "$BACKEND_PID" "$FRONTEND_PID"
    c_ok "已停止。"
}

# ── 状态 ────────────────────────────────────────────────────
do_status() {
    if port_listening "$BACKEND_PORT"; then
        c_ok "后端  运行中  :$BACKEND_PORT  (PID $(lsof -ti tcp:$BACKEND_PORT -sTCP:LISTEN 2>/dev/null | tr '\n' ' '))"
    else
        c_warn "后端  未运行  :$BACKEND_PORT"
    fi
    if port_listening "$FRONTEND_PORT"; then
        c_ok "前端  运行中  :$FRONTEND_PORT  (PID $(lsof -ti tcp:$FRONTEND_PORT -sTCP:LISTEN 2>/dev/null | tr '\n' ' '))"
    else
        c_warn "前端  未运行  :$FRONTEND_PORT"
    fi
}

# ── 日志 ────────────────────────────────────────────────────
do_logs() {
    c_info "实时日志(Ctrl-C 退出)… backend.log + frontend.log"
    touch "$BACKEND_LOG" "$FRONTEND_LOG"
    tail -n 30 -f "$BACKEND_LOG" "$FRONTEND_LOG"
}

# ── 入口 ────────────────────────────────────────────────────
case "${1:-start}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; echo; do_start ;;
    status)  do_status ;;
    logs)    do_logs ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
