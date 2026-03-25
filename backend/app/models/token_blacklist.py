"""
Token Blacklist Model

LÆ°u trá»¯ cÃ¡c JWT Ä‘Ã£ bá»‹ vÃ´ hiá»‡u hÃ³a (logout).
Má»—i record chá»©a JTI (JWT ID) duy nháº¥t cá»§a token bá»‹ blacklist,
cÃ¹ng thá»i Ä‘iá»ƒm háº¿t háº¡n Ä‘á»ƒ cÃ³ thá»ƒ dá»n dáº¹p (cleanup) record cÅ©.

Báº£o máº­t: Khi user logout, cáº£ access token vÃ  refresh token Ä‘á»u
Ä‘Æ°á»£c thÃªm vÃ o blacklist. Má»i request vá»›i token Ä‘Ã£ blacklist sáº½ bá»‹ tá»« chá»‘i.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TokenBlacklist(Base):
    """Báº£ng blacklist token â€” lÆ°u JTI cá»§a token Ä‘Ã£ bá»‹ há»§y."""

    __tablename__ = "token_blacklist"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # JTI (JWT ID) â€” mÃ£ Ä‘á»‹nh danh duy nháº¥t cá»§a má»—i token
    jti: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # Loáº¡i token: "access" hoáº·c "refresh"
    token_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # User ID sá»Ÿ há»¯u token
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    # Thá»i Ä‘iá»ƒm token háº¿t háº¡n tá»± nhiÃªn (dÃ¹ng Ä‘á»ƒ cleanup records cÅ©)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Thá»i Ä‘iá»ƒm token bá»‹ blacklist (logout)
    blacklisted_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Index cho truy váº¥n nhanh khi kiá»ƒm tra blacklist
    __table_args__ = (
        Index("ix_token_blacklist_jti_type", "jti", "token_type"),
    )

