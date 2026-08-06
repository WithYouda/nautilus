#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${NAUTILUS_E2E_BACKEND_PORT:-8012}"
FRONTEND_PORT="${NAUTILUS_E2E_FRONTEND_PORT:-5186}"
MOCK_PROVIDER_PORT="${NAUTILUS_E2E_MOCK_PROVIDER_PORT:-8013}"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [[ -n "${NAUTILUS_E2E_DATA_DIR:-}" ]]; then
  E2E_DATA_DIR="$(realpath -m -- "$NAUTILUS_E2E_DATA_DIR")"
  E2E_DATA_WAS_CREATED=0
else
  E2E_DATA_DIR="$(mktemp -d /tmp/nautilus-playwright.XXXXXX)"
  E2E_DATA_WAS_CREATED=1
fi
E2E_DATA_PARENT="$(dirname -- "$E2E_DATA_DIR")"
E2E_DATA_NAME="$(basename -- "$E2E_DATA_DIR")"
if [[ "$E2E_DATA_PARENT" != "/tmp" ]] || [[ "$E2E_DATA_NAME" != nautilus-playwright.* ]]; then
  printf '%s\n' "Playwright 数据目录必须是 /tmp/nautilus-playwright.*，拒绝启动。" >&2
  exit 1
fi
if [[ -L "$E2E_DATA_DIR" ]]; then
  printf '%s\n' "Playwright 数据目录不能是符号链接，拒绝启动。" >&2
  exit 1
fi
if [[ "$E2E_DATA_WAS_CREATED" == 0 ]] && [[ -e "$E2E_DATA_DIR" ]] && [[ ! -d "$E2E_DATA_DIR" ]]; then
  printf '%s\n' "Playwright 数据目录目标不是目录，拒绝启动。" >&2
  exit 1
fi
if [[ "$E2E_DATA_WAS_CREATED" == 0 ]] && [[ -e "$E2E_DATA_DIR" ]]; then
  printf '%s\n' "Playwright 数据目录已经存在，拒绝复用已有数据。" >&2
  exit 1
fi
if [[ "$E2E_DATA_WAS_CREATED" == 0 ]]; then
  mkdir -m 0700 -p -- "$E2E_DATA_DIR"
  E2E_DATA_WAS_CREATED=1
fi
E2E_DATA_DIR="$(realpath -- "$E2E_DATA_DIR")"
if [[ "$(dirname -- "$E2E_DATA_DIR")" != "/tmp" ]] || [[ "$(basename -- "$E2E_DATA_DIR")" != nautilus-playwright.* ]]; then
  printf '%s\n' "Playwright 数据目录真实路径越界，拒绝启动。" >&2
  exit 1
fi
BACKEND_PID=""
FRONTEND_PID=""
MOCK_PROVIDER_PID=""

cleanup() {
  for process_id in "$BACKEND_PID" "$FRONTEND_PID" "$MOCK_PROVIDER_PID"; do
    if [[ -n "$process_id" ]]; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  for process_id in "$BACKEND_PID" "$FRONTEND_PID" "$MOCK_PROVIDER_PID"; do
    if [[ -n "$process_id" ]]; then
      wait "$process_id" 2>/dev/null || true
    fi
  done
  if [[ "$E2E_DATA_WAS_CREATED" == 1 ]]; then
    rm -rf -- "$E2E_DATA_DIR"
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -x "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c "import fastapi, uvicorn, cryptography" >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi
if ! "$PYTHON_BIN" -c "import fastapi, uvicorn, cryptography" >/dev/null 2>&1; then
  printf '%s\n' "Playwright 后端缺少 fastapi、uvicorn 或 cryptography 依赖。" >&2
  exit 1
fi

if [[ ! -f "$ROOT_DIR/frontend/dist/index.html" ]]; then
  printf '%s\n' "Playwright 需要现有生产构建，请先运行 npm --prefix frontend run build。" >&2
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" "$ROOT_DIR/scripts/mock-openai-provider.py" \
  --host 0.0.0.0 \
  --port "$MOCK_PROVIDER_PORT" \
  >"$E2E_DATA_DIR/mock-provider.log" 2>&1 &
MOCK_PROVIDER_PID=$!

for _ in {1..100}; do
  if curl -fsS "http://127.0.0.1:$MOCK_PROVIDER_PORT/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$MOCK_PROVIDER_PID" 2>/dev/null; then
    printf '%s\n' "Playwright Mock provider 启动失败。" >&2
    sed -n '1,120p' "$E2E_DATA_DIR/mock-provider.log" >&2
    exit 1
  fi
  sleep 0.1
done
if ! curl -fsS "http://127.0.0.1:$MOCK_PROVIDER_PORT/health" >/dev/null 2>&1; then
  printf '%s\n' "Playwright Mock provider 未在限定时间内就绪。" >&2
  sed -n '1,120p' "$E2E_DATA_DIR/mock-provider.log" >&2
  exit 1
fi

NAUTILUS_DATA_DIR="$E2E_DATA_DIR" \
NAUTILUS_RUNTIME_TOKEN_FILE="$E2E_DATA_DIR/runtime/access-token" \
NAUTILUS_BACKEND_PORT="$BACKEND_PORT" \
"$PYTHON_BIN" -m uvicorn app.main:app \
  --app-dir "$ROOT_DIR/backend" \
  --host 0.0.0.0 \
  --port "$BACKEND_PORT" \
  --no-access-log \
  >"$E2E_DATA_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

for _ in {1..100}; do
  if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    printf '%s\n' "Playwright 隔离后端启动失败。" >&2
    sed -n '1,120p' "$E2E_DATA_DIR/backend.log" >&2
    exit 1
  fi
  sleep 0.1
done

if ! curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
  printf '%s\n' "Playwright 隔离后端未在限定时间内就绪。" >&2
  sed -n '1,120p' "$E2E_DATA_DIR/backend.log" >&2
  exit 1
fi

(cd "$ROOT_DIR/frontend" && \
  NAUTILUS_API_TARGET="http://127.0.0.1:$BACKEND_PORT" \
  exec "$ROOT_DIR/frontend/node_modules/.bin/vite" preview \
    --host 0.0.0.0 \
    --port "$FRONTEND_PORT" \
    --strictPort \
    --logLevel silent) \
  >"$E2E_DATA_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

wait -n "$MOCK_PROVIDER_PID" "$BACKEND_PID" "$FRONTEND_PID"
