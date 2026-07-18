#!/usr/bin/env bash
# 停止 chatbot-plus 后端 + 前端。
set -o pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "${LOG_DIR}"

BACKEND_PORT="8002"
FRONTEND_PORT="8502"
if [[ -f "${ROOT}/.env" ]]; then
  BACKEND_PORT="$(grep -E '^BACKEND_PORT=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d "'\" \r" || true)"
  FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d "'\" \r" || true)"
  BACKEND_PORT="${BACKEND_PORT:-8002}"
  FRONTEND_PORT="${FRONTEND_PORT:-8502}"
fi

echo "🛑 停止服务（端口 ${BACKEND_PORT} / ${FRONTEND_PORT}）…"
for port in "${BACKEND_PORT}" "${FRONTEND_PORT}"; do
  pids="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "${pids}" | xargs kill -9 2>/dev/null || true
  fi
done
# PID 文件兜底
for f in "${LOG_DIR}/run.pid" "${LOG_DIR}/backend.pid" "${LOG_DIR}/frontend.pid"; do
  [[ -f "${f}" ]] || continue
  while read -r pid; do
    [[ -n "${pid}" ]] && kill -9 "${pid}" 2>/dev/null || true
  done < "${f}"
  rm -f "${f}"
done
echo "✅ 已停止。"
