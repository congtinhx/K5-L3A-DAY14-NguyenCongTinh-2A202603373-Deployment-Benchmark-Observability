# ============================================================
# Production Dockerfile — multi-stage
#   Stage 1 (builder): cài dependencies vào /install
#   Stage 2 (runtime): base slim sạch, chỉ copy package đã cài + code,
#                      chạy bằng user non-root, có HEALTHCHECK
# Build:  docker build -t agent .
# Run:    docker run -p 8000:8000 -e AGENT_API_KEY=... -e REDIS_URL=... agent
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
# requirements trước, code sau → sửa code không phải cài lại dependencies (layer cache)
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN groupadd --system agent && useradd --system --gid agent --home-dir /app --shell /usr/sbin/nologin agent

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=agent:agent app/ ./app/
COPY --chown=agent:agent utils/ ./utils/

USER agent

EXPOSE 8000

# python:slim không có curl → kiểm /health bằng urllib
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=3)" || exit 1

# exec → uvicorn là PID 1, nhận thẳng SIGTERM khi `docker stop` / platform redeploy.
# PORT do Railway / Render cấp; số worker lấy từ WEB_CONCURRENCY nếu có (uvicorn tự đọc).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-graceful-shutdown 8"]
