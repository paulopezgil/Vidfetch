# ---- Stage 1: build the React frontend --------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build

# Install dependencies first for better layer caching.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build


# ---- Stage 2: backend + runtime ---------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# FFmpeg (merging/audio conversion), plus Node.js 22 LTS. yt-dlp may require a
# JavaScript runtime for some YouTube operations, so Node must be on PATH for
# the backend process.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates curl gnupg gosu \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend-dist/

ENV FRONTEND_DIST=/app/frontend-dist \
    DOWNLOAD_DIR=/app/downloads \
    DATA_DIR=/app/data \
    MAX_CONCURRENT_DOWNLOADS=2

# Persistent directories, owned by a non-root user.
RUN mkdir -p /app/downloads /app/data \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app/downloads /app/data

# Entrypoint fixes bind-mount permissions, verifies runtimes, then drops to the
# non-root user before starting the server.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
