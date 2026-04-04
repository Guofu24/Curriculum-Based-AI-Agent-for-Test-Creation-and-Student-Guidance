"""
Reset database: drop all tables và tạo lại theo schema hiện tại.
Chạy: python reset_db.py
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Import tất cả models để Base.metadata biết các table
from app.models.user import User
from app.models.document import Document
from app.models.exam import Exam
from app.models.refresh_token import RefreshToken
from app.models.teacher_preference import TeacherPreference
from app.core.database import Base
from app.core.config import get_settings

settings = get_settings()


async def reset():
    print(f"Connecting to: {settings.DATABASE_URL}")
    engine = create_async_engine(settings.DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        print("Dropping all tables via CASCADE...")
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        print("Creating all tables with current schema...")
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print("\n✅ Done! Database reset successfully.")
    print("Tables created:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    asyncio.run(reset())
