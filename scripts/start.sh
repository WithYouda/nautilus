#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WSL_IP="$("$ROOT_DIR/scripts/wsl-ip.sh")"
BACKEND_PORT="${NAUTILUS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${NAUTILUS_FRONTEND_PORT:-5173}"
API_TARGET="${NAUTILUS_API_TARGET:-http://127.0.0.1:$BACKEND_PORT}"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "$WSL_IP" ]]; then
  printf '%s\n' "无法解析 WSL2 实际 IP，服务未启动。" >&2
  exit 1
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  printf '%s\n' "frontend/node_modules 不存在，请先运行 npm --prefix frontend install。" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/tmp"
TOKEN_FILE="$ROOT_DIR/tmp/access-token"
FRONTEND_BUILD_LOG="$ROOT_DIR/tmp/frontend-build.log"

if ! npm --prefix "$ROOT_DIR/frontend" run build >"$FRONTEND_BUILD_LOG" 2>&1; then
  printf '%s\n' "前端生产构建失败，请检查 $FRONTEND_BUILD_LOG。" >&2
  exit 1
fi

NAUTILUS_RUNTIME_TOKEN_FILE="$TOKEN_FILE" "$PYTHON_BIN" -m uvicorn app.main:app \
  --app-dir "$ROOT_DIR/backend" \
  --host 0.0.0.0 \
  --port "$BACKEND_PORT" \
  --no-access-log \
  >"$ROOT_DIR/tmp/backend.log" 2>&1 &
BACKEND_PID=$!

(cd "$ROOT_DIR/frontend" && NAUTILUS_API_TARGET="$API_TARGET" exec "$ROOT_DIR/frontend/node_modules/.bin/vite" preview \
  --host 0.0.0.0 \
  --port "$FRONTEND_PORT" \
  --strictPort \
  --logLevel silent) \
  >"$ROOT_DIR/tmp/frontend.log" 2>&1 &
FRONTEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -f "$TOKEN_FILE"
}
trap cleanup EXIT INT TERM

for _ in {1..50}; do
  if [[ -s "$TOKEN_FILE" ]]; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if [[ ! -s "$TOKEN_FILE" ]]; then
  printf '%s\n' "后端未能生成访问令牌，请检查 $ROOT_DIR/tmp/backend.log。" >&2
  exit 1
fi

FRONTEND_HTML=""
for _ in {1..50}; do
  FRONTEND_HTML="$(curl -fsS "http://127.0.0.1:$FRONTEND_PORT/" 2>/dev/null || true)"
  if [[ -n "$FRONTEND_HTML" ]]; then
    break
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if [[ -z "$FRONTEND_HTML" ]]; then
  printf '%s\n' "前端生产预览未能启动，请检查 $ROOT_DIR/tmp/frontend.log。" >&2
  exit 1
fi
if [[ "$FRONTEND_HTML" == *"/@vite/client"* ]]; then
  printf '%s\n' "检测到 Vite 开发客户端，拒绝以会自动刷新的开发模式交付。" >&2
  exit 1
fi

printf '%s\n' ""
printf '%s\n' "学海无涯（Nautilus）已启动"
printf '%s\n' "前端模式: 生产预览（无 HMR 自动刷新）"
printf '%s\n' "Web: http://$WSL_IP:$FRONTEND_PORT"
printf '%s\n' "API: http://$WSL_IP:$BACKEND_PORT"
printf '%s\n' "后端日志: $ROOT_DIR/tmp/backend.log"
printf '%s\n' "前端构建日志: $FRONTEND_BUILD_LOG"
printf '%s\n' "前端日志: $ROOT_DIR/tmp/frontend.log"
printf '%s\n' "首次授权请在 Web 页面使用当前进程授权码。"
printf '%s\n' ""

wait -n "$BACKEND_PID" "$FRONTEND_PID"
