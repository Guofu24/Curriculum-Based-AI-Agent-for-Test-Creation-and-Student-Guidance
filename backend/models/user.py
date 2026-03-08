"""
User Model

Mô hình người dùng với các trường bảo mật:
- hashed_password: mật khẩu được hash bằng bcrypt (không bao giờ lưu plaintext)
- is_email_verified: trạng thái xác thực email (phải verify trước khi login)
- totp_secret: khóa bí mật cho 2FA (Google Authenticator), nullable cho tùy chọn
- failed_login_attempts / last_failed_login: theo dõi brute-force attempts
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    university: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Bảo mật: Xác thực email ---
    # User phải xác thực email trước khi được phép đăng nhập
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Bảo mật: 2FA (Two-Factor Authentication) ---
    # Khóa TOTP cho Google Authenticator (nullable = chưa bật 2FA)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # --- Bảo mật: Tracking brute-force ---
    # Đếm số lần đăng nhập thất bại liên tiếp
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Thời điểm lần đăng nhập thất bại gần nhất
    last_failed_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    textbooks = relationship("Textbook", back_populates="owner")
    exams = relationship("Exam", back_populates="owner")
