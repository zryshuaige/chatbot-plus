#!/usr/bin/env bash
# chatbot-plus 一键启动 / 刷新最新：杀掉旧进程后重新拉起后端 + 前端。
# 用法：
#   ./run.sh         启动（已运行则先停再起 = 刷新最新代码）
#   ./stop.sh        停止
#   tail -f logs/backend.log logs/frontend.log   查看日志
set -eo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "${LOG_DIR}"

# ---- 从 .env 读端口（没有 .env 就用默认值）----
BACKEND_PORT="8002"
FRONTEND_PORT="8502"
if [[ -f "${ROOT}/.env" ]]; then
  BACKEND_PORT="$(grep -E '^BACKEND_PORT=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d "'\" \r" || true)"
  FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d "'\" \r" || true)"
  BACKEND_PORT="${BACKEND_PORT:-8002}"
  FRONTEND_PORT="${FRONTEND_PORT:-8502}"
fi

# ---- 杀掉占用这两个端口的旧进程（= 刷新到最新）----
echo "🧹 清理旧进程（端口 ${BACKEND_PORT} / ${FRONTEND_PORT}）…"
for port in "${BACKEND_PORT}" "${FRONTEND_PORT}"; do
  pids="$(lsof -ti tcp:"${port}" 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "${pids}" | xargs kill -9 2>/dev/null || true
  fi
done
# 兜底：按 PID 文件清
if [[ -f "${LOG_DIR}/run.pid" ]]; then
  while read -r pid; do
    [[ -n "${pid}" ]] && kill -9 "${pid}" 2>/dev/null || true
  done < "${LOG_DIR}/run.pid"
fi
sleep 1

# ---- 启动后端（在 backend/ 目录运行，日志写 logs/backend.log）----
echo "🚀 启动后端（uvicorn，端口 ${BACKEND_PORT}）…"
BACKEND_LOG="${LOG_DIR}/backend.log"
nohup bash -c "cd '${ROOT}/backend' && exec python3 -m uvicorn main:app \
    --host 127.0.0.1 --port '${BACKEND_PORT}'" \
    > "${BACKEND_LOG}" 2>&1 &
BACKEND_PID=$!
echo "${BACKEND_PID}" > "${LOG_DIR}/backend.pid"

# ---- 启动前端（在 frontend/ 目录运行，日志写 logs/frontend.log）----
echo "🎨 启动前端（streamlit，端口 ${FRONTEND_PORT}）…"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
nohup bash -c "cd '${ROOT}/frontend' && exec streamlit run app.py \
    --server.port '${FRONTEND_PORT}' \
    --server.headless true --browser.gatherUsageStats false" \
    > "${FRONTEND_LOG}" 2>&1 &
FRONTEND_PID=$!
echo "${FRONTEND_PID}" > "${LOG_DIR}/frontend.pid"

# 合并 PID 供 stop.sh
printf '%s\n%s\n' "${BACKEND_PID}" "${FRONTEND_PID}" > "${LOG_DIR}/run.pid"

# ---- 等后端就绪 ----
echo "⏳ 等待后端就绪…"
ok=0
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 1
done

echo
echo "=============================================="
if [[ "${ok}" == "1" ]]; then
  echo "✅ 启动成功！"
else
  echo "⚠️  后端 30s 内未响应，请查日志：tail -f ${BACKEND_LOG}"
fi
echo "👉 前端：http://localhost:${FRONTEND_PORT}"
echo "👉 后端：http://127.0.0.1:${BACKEND_PORT}"
echo "📝 日志： ${LOG_DIR}/backend.log / frontend.log"
echo "🛑 停止： ./stop.sh"
echo "🔄 刷新： 再次运行 ./run.sh"
echo "=============================================="
