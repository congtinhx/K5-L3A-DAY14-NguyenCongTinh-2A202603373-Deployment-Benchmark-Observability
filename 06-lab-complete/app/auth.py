"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401 (không phải 403 hay 422)
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

# auto_error=False: tự trả 401 thay vì để FastAPI trả 403 khi thiếu header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho /ask. Trả về API key hợp lệ (dùng làm khoá rate limit)."""
    expected = settings.agent_api_key
    # Chưa cấu hình AGENT_API_KEY → từ chối hết (fail closed), không mở cửa tự do.
    # compare_digest so sánh thời gian hằng, tránh dò key qua timing.
    if not expected or not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
