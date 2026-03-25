"""
Email Verification Utility

Module gá»­i email xÃ¡c thá»±c tÃ i khoáº£n.
Hiá»‡n táº¡i lÃ  STUB â€” log verification link ra console thay vÃ¬ gá»­i email tháº­t.
Khi deploy production, thay tháº¿ báº±ng SMTP tháº­t hoáº·c dá»‹ch vá»¥ email (SendGrid, SES).

Äá»ƒ báº­t SMTP tháº­t, cáº¥u hÃ¬nh cÃ¡c biáº¿n mÃ´i trÆ°á»ng:
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL
"""
import logging

from app.core.config import settings
from app.utils.security import create_email_verification_token

logger = logging.getLogger(__name__)


async def send_verification_email(user_id: str, email: str) -> None:
    """
    Gá»­i email xÃ¡c thá»±c cho user má»›i Ä‘Äƒng kÃ½.
    
    Flow:
    1. Táº¡o JWT verification token (cÃ³ thá»i háº¡n 24 giá»)
    2. Náº¿u SMTP_HOST Ä‘Æ°á»£c cáº¥u hÃ¬nh â†’ gá»­i email tháº­t
    3. Náº¿u chÆ°a â†’ log link xÃ¡c thá»±c ra console (development mode)
    
    Args:
        user_id: ID user cáº§n xÃ¡c thá»±c
        email: email user
    """
    # Táº¡o token xÃ¡c thá»±c (JWT, 24 giá»)
    verification_token = create_email_verification_token(user_id, email)

    # URL xÃ¡c thá»±c â€” user click vÃ o link nÃ y Ä‘á»ƒ verify email
    # Trong production, thay báº±ng frontend URL hoáº·c API URL thá»±c táº¿
    verification_url = (
        f"http://localhost:8000{settings.API_PREFIX}/auth/verify-email"
        f"?token={verification_token}"
    )

    if settings.SMTP_HOST:
        # â”€â”€â”€ Production: Gá»­i email tháº­t qua SMTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # TODO: Implement SMTP sending khi deploy production
        # Sá»­ dá»¥ng thÆ° viá»‡n nhÆ° aiosmtplib hoáº·c fastapi-mail
        logger.info(f"Sending verification email to {email} via SMTP")
        # Placeholder for SMTP implementation:
        # async with aiosmtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        #     await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        #     message = MIMEText(f"Click to verify: {verification_url}")
        #     message["Subject"] = f"{settings.APP_NAME} - XÃ¡c thá»±c email"
        #     message["From"] = settings.SMTP_FROM_EMAIL
        #     message["To"] = email
        #     await smtp.send_message(message)
        pass
    else:
        # â”€â”€â”€ Development: Log link ra console â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        logger.info(
            f"\n{'='*60}\n"
            f"ðŸ“§ EMAIL VERIFICATION (Development Mode)\n"
            f"   To:    {email}\n"
            f"   Link:  {verification_url}\n"
            f"{'='*60}\n"
        )

