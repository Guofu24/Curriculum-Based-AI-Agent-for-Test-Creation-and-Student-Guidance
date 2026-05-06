"""Script to create an admin account.

Run from any directory:
    python scripts/create_admin.py
    (or from backend/: python -m scripts.create_admin)
"""

import asyncio
import os
import sys

# ── Resolve paths ──────────────────────────────────────────────────────────────
# This file lives at backend/scripts/create_admin.py.
# The backend root is one level up.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)

# Change CWD to backend root so pydantic-settings finds .env there.
os.chdir(BACKEND_DIR)

# Add backend root to sys.path so `app.*` imports resolve.
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ── Import app modules AFTER path/CWD are set ──────────────────────────────────
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.user import User, UserRole
from app.dependencies import get_password_hash


async def create_admin():
    print("=== Create Admin Account ===")

    email = input("Email: ").strip()
    if not email:
        print("Error: Email cannot be empty.")
        return

    import getpass
    password = getpass.getpass("Password: ").strip()
    if len(password) < 8:
        print("Error: Password must be at least 8 characters.")
        return

    full_name = input("Full Name (optional): ").strip() or None

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print(f"User '{email}' already exists (role: {existing_user.role}).")
            answer = input("Promote this user to admin? (y/n): ").strip().lower()
            if answer == "y":
                existing_user.role = UserRole.ADMIN.value
                if full_name:
                    existing_user.full_name = full_name
                await session.commit()
                print(f"✅ User '{email}' promoted to admin.")
            else:
                print("Aborted.")
            return

        new_admin = User(
            email=email,
            password_hash=get_password_hash(password),
            full_name=full_name,
            role=UserRole.ADMIN.value,
        )
        session.add(new_admin)
        await session.commit()
        print(f"✅ Admin account '{email}' created successfully!")


if __name__ == "__main__":
    asyncio.run(create_admin())
