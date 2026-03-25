"""
Rate Limiting Utility

In-memory sliding window rate limiter cho login endpoint.
Giá»›i háº¡n sá»‘ láº§n Ä‘Äƒng nháº­p tá»« cÃ¹ng má»™t IP trong khoáº£ng thá»i gian cá»‘ Ä‘á»‹nh.

Má»¥c Ä‘Ã­ch: Chá»‘ng brute-force attack (attacker thá»­ hÃ ng nghÃ¬n máº­t kháº©u liÃªn tá»¥c).

LÆ°u Ã½:
- Sá»­ dá»¥ng in-memory dict â†’ reset khi restart server
- Trong production nÃªn dÃ¹ng Redis Ä‘á»ƒ rate limit chÃ­nh xÃ¡c hÆ¡n
  vÃ  hoáº¡t Ä‘á»™ng tá»‘t vá»›i multiple worker processes
- Tá»± Ä‘á»™ng dá»n dáº¹p (cleanup) entries háº¿t háº¡n
"""
import time
import logging
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# In-memory storage: { ip_address: [timestamp1, timestamp2, ...] }
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _cleanup_old_entries(ip: str) -> None:
    """XÃ³a cÃ¡c entries Ä‘Ã£ háº¿t háº¡n (ngoÃ i sliding window)."""
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    cutoff = time.time() - window
    _login_attempts[ip] = [
        ts for ts in _login_attempts[ip] if ts > cutoff
    ]
    # XÃ³a key náº¿u list rá»—ng (tiáº¿t kiá»‡m memory)
    if not _login_attempts[ip]:
        del _login_attempts[ip]


async def check_login_rate_limit(request: Request) -> None:
    """
    FastAPI dependency â€” kiá»ƒm tra rate limit trÆ°á»›c khi xá»­ lÃ½ login.
    
    Flow:
    1. Láº¥y IP client tá»« request
    2. Dá»n dáº¹p entries cÅ© ngoÃ i sliding window
    3. Äáº¿m sá»‘ request trong window hiá»‡n táº¡i
    4. Náº¿u vÆ°á»£t quÃ¡ giá»›i háº¡n â†’ raise HTTP 429 (Too Many Requests)
    5. Náº¿u chÆ°a â†’ ghi nháº­n request nÃ y
    
    Báº£o máº­t: KhÃ´ng tiáº¿t lá»™ chÃ­nh xÃ¡c bao lÃ¢u ná»¯a sáº½ Ä‘Æ°á»£c thá»­ láº¡i
    (trÃ¡nh attacker tÃ­nh toÃ¡n thá»i gian chÃ­nh xÃ¡c).
    """
    # Láº¥y IP tháº­t (há»— trá»£ reverse proxy qua X-Forwarded-For)
    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()

    # Dá»n dáº¹p entries cÅ©
    _cleanup_old_entries(client_ip)

    # Kiá»ƒm tra giá»›i háº¡n
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
            detail="QuÃ¡ nhiá»u láº§n thá»­ Ä‘Äƒng nháº­p. Vui lÃ²ng thá»­ láº¡i sau.",
        )

    # Ghi nháº­n láº§n thá»­ nÃ y
    _login_attempts[client_ip].append(time.time())

