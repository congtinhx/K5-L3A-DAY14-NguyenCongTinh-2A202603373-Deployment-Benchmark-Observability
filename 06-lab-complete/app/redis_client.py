"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config.
  • redis.from_url() KHÔNG mở kết nối lúc import → app vẫn khởi động được khi
    Redis chưa sẵn sàng (vd container chạy một mình, hoặc Redis đang restart).
  • Timeout ngắn để /ready trả 503 nhanh thay vì treo khi Redis chết.
"""
import redis

from app.config import settings

r = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)


def redis_healthy() -> bool:
    """True nếu PING Redis thành công; mọi lỗi kết nối / timeout → False."""
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError):
        return False
