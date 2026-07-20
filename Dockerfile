# ---- Stage 1: build the React/Vite SPA ----
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# npm can omit Rollup's platform-native optional package when the lockfile was
# produced on another OS. Install the matching Alpine binary after the locked
# dependency set so Vite builds on both Apple Silicon and x86 Docker hosts.
# The native-package versions are read from package-lock.json at build time so
# they always match the JS lockfile (each musl package version-locks to its
# parent: rollup, lightningcss, @tailwindcss/oxide).
RUN npm ci \
    && ROLLUP_V=$(node -p "require('./package-lock.json').packages['node_modules/rollup'].version") \
    && LCSS_V=$(node -p "require('./package-lock.json').packages['node_modules/lightningcss'].version") \
    && OXIDE_V=$(node -p "require('./package-lock.json').packages['node_modules/@tailwindcss/oxide'].version") \
    && case "$(uname -m)" in \
         aarch64) ARCH=arm64 ;; \
         x86_64)  ARCH=x64 ;; \
       esac \
    && npm install --no-save --ignore-scripts \
         "@rollup/rollup-linux-${ARCH}-musl@${ROLLUP_V}" \
         "lightningcss-linux-${ARCH}-musl@${LCSS_V}" \
         "@tailwindcss/oxide-linux-${ARCH}-musl@${OXIDE_V}"
COPY web/ ./
RUN npm run build

# ---- Stage 2: build the pinned, portable CPU speech runtime ----
FROM debian:bookworm-slim AS whisper
ARG WHISPER_CPP_VERSION=1.8.5
ARG WHISPER_CPP_SHA256=cd702189cb5e608c8bc487f4b151db593c4455925b37cc06ef76b44861911db1
ARG WHISPER_MODEL_REVISION=5359861c739e955e79d9a303bcbc70fb988958b1
ARG WHISPER_MODEL_SHA256=60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates cmake curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/whisper.cpp
RUN curl -fsSL "https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v${WHISPER_CPP_VERSION}.tar.gz" -o /tmp/whisper.cpp.tar.gz \
    && echo "${WHISPER_CPP_SHA256}  /tmp/whisper.cpp.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/whisper.cpp.tar.gz --strip-components=1 \
    && cmake -S . -B build \
         -DCMAKE_BUILD_TYPE=Release \
         -DBUILD_SHARED_LIBS=OFF \
         -DGGML_NATIVE=OFF \
         -DWHISPER_BUILD_TESTS=OFF \
         -DWHISPER_BUILD_EXAMPLES=ON \
    && cmake --build build --config Release --target whisper-cli -j "$(nproc)" \
    && install -Dm755 build/bin/whisper-cli /out/bin/whisper-cli \
    && strip /out/bin/whisper-cli \
    && install -d /out/models \
    && curl -fsSL "https://huggingface.co/ggerganov/whisper.cpp/resolve/${WHISPER_MODEL_REVISION}/ggml-base.bin" -o /out/models/ggml-base.bin \
    && echo "${WHISPER_MODEL_SHA256}  /out/models/ggml-base.bin" | sha256sum -c -

# ---- Stage 3: the Python app (FastAPI + downloader core) ----
FROM python:3.12-slim-bookworm

# FFmpeg encodes slideshows and extracts bounded analysis inputs. Tesseract and
# its English data perform local scene-text recognition.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-web.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt -c constraints.txt

COPY core/ ./core/
COPY server/ ./server/
COPY default.mp3 ./default.mp3
COPY --from=web /web/dist ./web/dist
COPY --from=whisper /out/bin/whisper-cli /usr/local/bin/whisper-cli
COPY --from=whisper /out/models/ggml-base.bin /opt/whisper/models/ggml-base.bin

ENV DOWNLOAD_DIR=/app/downloads \
    DB_FILE=/app/data/archive.db \
    APP_PORT=8080 \
    WHISPER_CPP_BIN=/usr/local/bin/whisper-cli \
    WHISPER_MODEL=/opt/whisper/models/ggml-base.bin \
    TESSERACT_BIN=/usr/bin/tesseract

EXPOSE 8080
CMD ["sh", "-c", "uvicorn --factory server.main:create_app --host 0.0.0.0 --port ${APP_PORT:-8080}"]
