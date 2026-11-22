# Backend-only image for the split deployment.
#
# The build context is this directory (``./backend``), so nothing from the
# repository root or the React frontend can leak into the image:
#
#   docker build -t vidfetch-backend ./backend
#
# The UI is built and served separately (Vite locally, Vercel in production)
# and talks to this container over the JSON API.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# FFmpeg merges streams and converts audio. Node.js 22 (NodeSource) is the
# JavaScript runtime some yt-dlp extractors require. curl backs HEALTHCHECK;
# ca-certificates and gnupg are needed to trust/verify the NodeSource repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies live next to the package now, so the backend directory is
# self-contained as a build context.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Only the runtime package: no repository root, no tests, no frontend.
COPY __init__.py version.py ./backend/
COPY app/ ./backend/app/

# MEDIA storage lives on a volume owned by the runtime user.
ENV DOWNLOAD_DIR=/app/downloads \
    MAX_CONCURRENT_DOWNLOADS=2

RUN mkdir -p /app/downloads \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app/downloads

USER appuser

EXPOSE 8000

# The health endpoint stays public and returns 200 even while degraded, so it
# is a liveness probe rather than a readiness gate.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
