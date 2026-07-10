# ---- Stage 1: build the React/Vite SPA ----
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# npm can omit Rollup's platform-native optional package when the lockfile was
# produced on another OS. Install the matching Alpine binary after the locked
# dependency set so Vite builds on both Apple Silicon and x86 Docker hosts.
RUN npm ci \
    && case "$(uname -m)" in \
         aarch64) npm install --no-save --ignore-scripts @rollup/rollup-linux-arm64-musl@4.62.2 lightningcss-linux-arm64-musl@1.32.0 @tailwindcss/oxide-linux-arm64-musl@4.3.2 ;; \
         x86_64) npm install --no-save --ignore-scripts @rollup/rollup-linux-x64-musl@4.62.2 lightningcss-linux-x64-musl@1.32.0 @tailwindcss/oxide-linux-x64-musl@4.3.2 ;; \
       esac
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
