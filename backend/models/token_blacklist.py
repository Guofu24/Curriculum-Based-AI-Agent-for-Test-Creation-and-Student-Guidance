"""
Token Blacklist Model

Lưu trữ các JWT đã bị vô hiệu hóa (logout).
Mỗi record chứa JTI (JWT ID) duy nhất của token bị blacklist,
cùng thời điểm hết hạn để có thể dọn dẹp (cleanup) record cũ.

Bảo mật: Khi user logout, cả access token và refresh token đều
được thêm vào blacklist. Mọi request với token đã blacklist sẽ bị từ chối.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class TokenBlacklist(Base):
    """Bảng blacklist token — lưu JTI của token đã bị hủy."""

    __tablename__ = "token_blacklist"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # JTI (JWT ID) — mã định danh duy nhất của mỗi token
    jti: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # Loại token: "access" hoặc "refresh"
    token_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # User ID sở hữu token
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    # Thời điểm token hết hạn tự nhiên (dùng để cleanup records cũ)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Thời điểm token bị blacklist (logout)
    blacklisted_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Index cho truy vấn nhanh khi kiểm tra blacklist
    __table_args__ = (
        Index("ix_token_blacklist_jti_type", "jti", "token_type"),
    )
