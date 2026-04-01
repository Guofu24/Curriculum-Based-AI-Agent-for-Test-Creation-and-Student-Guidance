FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# - build-essential: gcc for compiling Python packages
# - libpq-dev: PostgreSQL client libs for psycopg2/asyncpg
# - libffi-dev: for cffi (used by cryptography)
# WeasyPrint/GTK3 deps: cairo, pango, gdk-pixbuf, fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    libffi-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
   woff2 \
    fonts-noto-core \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security (optional)
RUN useradd -m -u 1000 appuser 2>/dev/null || true
USER 1000

# Expose port
EXPOSE 8000

# Default: run API server
# Override with: docker-compose run celery celery -A app.tasks.celery_app worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
