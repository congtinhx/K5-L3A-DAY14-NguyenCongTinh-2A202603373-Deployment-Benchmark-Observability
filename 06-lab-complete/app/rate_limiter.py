"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) để mọi worker / instance dùng chung và
    vẫn còn sau khi restart agent.

Thuật toán (một transaction MULTI/EXEC):
  ZREMRANGEBYSCORE  xoá timestamp cũ hơn 60s
  ZADD              ghi request hiện tại (score = thời điểm)
  ZCARD             đếm số request trong cửa sổ
  EXPIRE            key tự hết hạn khi user ngừng gọi
Nếu đếm > giới hạn thì xoá lại request vừa ghi (request bị từ chối không chiếm
lượt) và trả 429. Ghi trước rồi đếm trong cùng transaction giúp nhiều worker
gọi đồng thời không vượt giới hạn.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key dạng rõ trong Redis — chỉ lưu hash
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:24]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()
    member = f"{now:.6f}-{uuid.uuid4().hex[:8]}"

    try:
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
        pipe.zadd(bucket, {member: now})
        pipe.zcard(bucket)
        pipe.expire(bucket, WINDOW_SECONDS)
        _, _, count, _ = pipe.execute()

        if count <= limit:
            return

        r.zrem(bucket, member)
        oldest = r.zrange(bucket, 0, 0, withscores=True)
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limit store unavailable, try again later")

    retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
    retry_after = max(1, retry_after)
    raise HTTPException(
        status_code=429,
        detail={
            "error": "Rate limit exceeded",
            "limit": limit,
            "window_seconds": WINDOW_SECONDS,
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
        },
    )
