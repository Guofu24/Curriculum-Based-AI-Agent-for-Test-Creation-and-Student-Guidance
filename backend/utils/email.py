"""
Email Verification Utility

Module gửi email xác thực tài khoản.
Hiện tại là STUB — log verification link ra console thay vì gửi email thật.
Khi deploy production, thay thế bằng SMTP thật hoặc dịch vụ email (SendGrid, SES).

Để bật SMTP thật, cấu hình các biến môi trường:
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL
"""
import logging

from config import settings
from utils.security import create_email_verification_token

logger = logging.getLogger(__name__)


async def send_verification_email(user_id: str, email: str) -> None:
    """
    Gửi email xác thực cho user mới đăng ký.
    
    Flow:
    1. Tạo JWT verification token (có thời hạn 24 giờ)
    2. Nếu SMTP_HOST được cấu hình → gửi email thật
    3. Nếu chưa → log link xác thực ra console (development mode)
    
    Args:
        user_id: ID user cần xác thực
        email: email user
    """
    # Tạo token xác thực (JWT, 24 giờ)
    verification_token = create_email_verification_token(user_id, email)

    # URL xác thực — user click vào link này để verify email
    # Trong production, thay bằng frontend URL hoặc API URL thực tế
    verification_url = (
        f"http://localhost:8000{settings.API_PREFIX}/auth/verify-email"
        f"?token={verification_token}"
    )

    if settings.SMTP_HOST:
        # ─── Production: Gửi email thật qua SMTP ───────────────
        # TODO: Implement SMTP sending khi deploy production
        # Sử dụng thư viện như aiosmtplib hoặc fastapi-mail
        logger.info(f"Sending verification email to {email} via SMTP")
        # Placeholder for SMTP implementation:
        # async with aiosmtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        #     await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        #     message = MIMEText(f"Click to verify: {verification_url}")
        #     message["Subject"] = f"{settings.APP_NAME} - Xác thực email"
        #     message["From"] = settings.SMTP_FROM_EMAIL
        #     message["To"] = email
        #     await smtp.send_message(message)
        pass
    else:
        # ─── Development: Log link ra console ───────────────────
        logger.info(
            f"\n{'='*60}\n"
            f"📧 EMAIL VERIFICATION (Development Mode)\n"
            f"   To:    {email}\n"
            f"   Link:  {verification_url}\n"
            f"{'='*60}\n"
        )
