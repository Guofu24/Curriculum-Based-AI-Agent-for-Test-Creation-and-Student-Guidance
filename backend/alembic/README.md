# ExamAI — Alembic Database Migrations

This directory will be created when you run:
```bash
alembic init alembic
```

Then configure `alembic.ini` with your DATABASE_URL and run:
```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```
