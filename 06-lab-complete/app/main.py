"""
Production AI Agent — Part 6 Final Project

Chạy:   uvicorn app.main:app --workers 2
Kiểm:   python check_production_ready.py

  GET  /health  liveness  — luôn 200 khi process còn sống (không phụ thuộc Redis)
  GET  /ready   readiness — 200 khi Redis kết nối được, 503 khi không
  POST /ask     X-API-Key (401) → rate limit (429) → budget (402) → LLM → ghi chi phí
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging — mỗi dòng log của app là 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            # Traceback chỉ nằm trong log (1 dòng JSON), không bao giờ trả cho client
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("agent")
    log.handlers = [handler]
    log.setLevel(getattr(logging, settings.log_level, logging.INFO))
    log.propagate = False
    return log


logger = _setup_logging()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


START_TIME = time.time()


# ─────────────────────────────────────────────────────────
# Lifespan — startup / graceful shutdown
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Không chặn khởi động khi Redis chưa sẵn sàng: /health vẫn 200, /ready báo 503
    log_event("startup", environment=settings.environment, version=settings.app_version,
              port=settings.port, redis_ready=redis_healthy())
    yield
    # Uvicorn nhận SIGTERM → ngừng nhận kết nối mới → chờ request đang chạy xong
    # → mới chạy tới đây. Không tự đăng ký handler SIGTERM để khỏi đè handler của uvicorn.
    log_event("shutdown", uptime_seconds=round(time.time() - START_TIME, 1))
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", version=settings.app_version, lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log_event("request_failed", logging.ERROR, method=request.method, path=request.url.path,
                  ms=round((time.perf_counter() - started) * 1000, 1))
        raise
    log_event("request", method=request.method, path=request.url.path,
              status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response


# ─────────────────────────────────────────────────────────
# Xử lý lỗi — mã lỗi rõ ràng, không lộ stack trace
# ─────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"),
               "message": e.get("msg", "invalid")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request body", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc_info=exc, extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


@app.get("/")
def root():
    return {"app": "Production AI Agent", "version": settings.app_version,
            "endpoints": ["GET /health", "GET /ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness: process còn sống là 200 — không kiểm Redis để platform không restart oan."""
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1),
            "version": settings.app_version, "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis (state dùng chung) kết nối được."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "redis": "unavailable"})
    return {"ready": True, "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()                     # 402 khi hết budget — kiểm TRƯỚC khi tốn tiền gọi LLM

    answer = llm_ask(body.question)

    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    log_event("llm_call", question_chars=len(body.question), input_tokens=input_tokens,
              output_tokens=output_tokens, cost_usd=round(cost, 8))

    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }
