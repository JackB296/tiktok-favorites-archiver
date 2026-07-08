# ---- Stage 1: build the React/Vite SPA ----
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

# ---- Stage 2: the Python app (FastAPI + downloader core) ----
FROM python:3.12-slim

# ffmpeg is required by moviepy to encode slideshows.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

COPY core/ ./core/
COPY server/ ./server/
COPY default.mp3 ./default.mp3
COPY --from=web /web/dist ./web/dist

ENV DOWNLOAD_DIR=/app/downloads \
    DB_FILE=/app/data/archive.db \
    APP_PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${APP_PORT:-8080}"]
