"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

  • Không có secret nào trong code: AGENT_API_KEY phải được đặt qua env
    (file .env khi chạy local, Variables trên Railway / Render khi deploy).
  • Khi chạy local, file .env (nếu có) được nạp tự động nhưng KHÔNG ghi đè
    biến môi trường đã đặt sẵn (platform / script chấm luôn được ưu tiên).
  • Danh sách biến xem .env.example.
"""
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # python-dotenv là tuỳ chọn
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "1.0.0"))

    # Security — không có giá trị mặc định: thiếu key thì /ask từ chối mọi request (fail closed)
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # State dùng chung (rate limit, cost) — Redis
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Giới hạn
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))


settings = Settings()
