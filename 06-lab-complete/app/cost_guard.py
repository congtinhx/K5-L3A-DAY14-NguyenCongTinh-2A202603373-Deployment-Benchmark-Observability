"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày và theo tháng (UTC)
  • Tổng chi phí đã vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402

Key Redis:
  cost:daily:YYYY-MM-DD   hết hạn sau 2 ngày   → tự reset mỗi ngày
  cost:monthly:YYYY-MM    hết hạn sau 32 ngày  → tự reset mỗi tháng
Budget tính cho toàn dịch vụ (bảo vệ tiền của chủ agent), dùng chung giữa mọi
worker / instance vì nằm trong Redis.
"""
import logging
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

logger = logging.getLogger("agent")


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:daily:{now:%Y-%m-%d}", f"cost:monthly:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """Ước lượng thô ~4 ký tự / token (mock LLM không trả usage thật)."""
    return max(1, len(text) // 4)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _keys()
    try:
        daily_raw, monthly_raw = r.mget(daily_key, monthly_key)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Budget store unavailable, try again later")

    daily = float(daily_raw or 0)
    monthly = float(monthly_raw or 0)

    if daily >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "spent_usd": round(daily, 6),
                "budget_usd": settings.daily_budget_usd,
                "resets": "00:00 UTC",
            },
        )
    if monthly >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "spent_usd": round(monthly, 6),
                "budget_usd": settings.monthly_budget_usd,
                "resets": "first day of next month (UTC)",
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _keys()
    try:
        pipe = r.pipeline(transaction=True)
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, 2 * 24 * 3600)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, 32 * 24 * 3600)
        pipe.execute()
    except redis.RedisError:
        # LLM đã trả lời rồi: không làm hỏng response, chỉ ghi cảnh báo
        logger.warning("cost_record_failed", extra={"fields": {"cost_usd": cost}})
    return cost
