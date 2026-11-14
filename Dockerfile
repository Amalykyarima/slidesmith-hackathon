# SlideSmith: one container serving the API and the Angular app.
# Built for Render's free plan (512 MB): see render.yaml and docs/HOSTING.md.

# ---- 1. Build the Angular app -------------------------------------------- #
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build

# ---- 2. Python API + LibreOffice for slide previews ---------------------- #
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STORAGE_DIR=/tmp/slidesmith \
    FRONTEND_DIST=/app/frontend/browser

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-impress fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core fontconfig \
 && rm -rf /var/lib/apt/lists/*
COPY deploy/fonts.conf /etc/fonts/local.conf
RUN fc-cache -f

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY backend/pictos ./pictos
COPY --from=web /web/dist/frontend/browser /app/frontend/browser

RUN useradd --create-home slidesmith && mkdir -p /tmp/slidesmith && chown slidesmith /tmp/slidesmith
USER slidesmith

# Render sets PORT (10000 by default) and terminates HTTPS in front of the app.
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips '*'"]
