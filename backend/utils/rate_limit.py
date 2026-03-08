"""
Rate Limiting Utility

In-memory sliding window rate limiter cho login endpoint.
Giới hạn số lần đăng nhập từ cùng một IP trong khoảng thời gian cố định.

Mục đích: Chống brute-force attack (attacker thử hàng nghìn mật khẩu liên tục).

Lưu ý:
- Sử dụng in-memory dict → reset khi restart server
- Trong production nên dùng Redis để rate limit chính xác hơn
  và hoạt động tốt với multiple worker processes
- Tự động dọn dẹp (cleanup) entries hết hạn
"""
import time
import logging
from collections import defaultdict

from fastapi import HTTPException, Request, status

from config import settings

logger = logging.getLogger(__name__)

# In-memory storage: { ip_address: [timestamp1, timestamp2, ...] }
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _cleanup_old_entries(ip: str) -> None:
    """Xóa các entries đã hết hạn (ngoài sliding window)."""
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    cutoff = time.time() - window
    _login_attempts[ip] = [
        ts for ts in _login_attempts[ip] if ts > cutoff
    ]
    # Xóa key nếu list rỗng (tiết kiệm memory)
    if not _login_attempts[ip]:
        del _login_attempts[ip]


async def check_login_rate_limit(request: Request) -> None:
    """
    FastAPI dependency — kiểm tra rate limit trước khi xử lý login.
    
    Flow:
    1. Lấy IP client từ request
    2. Dọn dẹp entries cũ ngoài sliding window
    3. Đếm số request trong window hiện tại
    4. Nếu vượt quá giới hạn → raise HTTP 429 (Too Many Requests)
    5. Nếu chưa → ghi nhận request này
    
    Bảo mật: Không tiết lộ chính xác bao lâu nữa sẽ được thử lại
    (tránh attacker tính toán thời gian chính xác).
    """
    # Lấy IP thật (hỗ trợ reverse proxy qua X-Forwarded-For)
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    # Dọn dẹp entries cũ
    _cleanup_old_entries(client_ip)

    # Kiểm tra giới hạn
    max_requests = settings.LOGIN_RATE_LIMIT_REQUESTS
    current_count = len(_login_attempts.get(client_ip, []))

    if current_count >= max_requests:
        logger.warning(
            f"Rate limit exceeded for IP {client_ip}: "
            f"{current_count}/{max_requests} attempts in "
            f"{settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS}s window"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Quá nhiều lần thử đăng nhập. Vui lòng thử lại sau.",
        )

    # Ghi nhận lần thử này
    _login_attempts[client_ip].append(time.time())
