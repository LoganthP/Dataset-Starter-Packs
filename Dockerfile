# One image: the FastAPI API serves the built React app on port 8000.
#   docker compose up -d --build      (see compose.yaml)

# ---- frontend build
FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- API + starter-pack runtime
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DSP_REPO_ROOT=/app \
    DSP_STATE_DIR=/data/state \
    DSP_CORS_ORIGINS=
WORKDIR /app

COPY backend/requirements-api.txt backend/requirements-packs.txt backend/
RUN pip install -r backend/requirements-api.txt -r backend/requirements-packs.txt

COPY backend/app backend/app
COPY catalog catalog
COPY packs packs
COPY --from=web /src/frontend/dist frontend/dist
COPY docker/entrypoint.sh /usr/local/bin/dsp-entrypoint

# Non-root user; everything that must persist is under /data (a named volume in compose.yaml):
#   /data/state      SQLite: analysis runs, saved comparisons, curated records, pack-run history, uploads
#   /data/pack-data  downloaded real data for the starter packs (packs/<slug>/data links here)
RUN useradd --uid 10001 --create-home dsp \
 && mkdir -p /data/state /data/pack-data \
 && for p in packs/*/; do s=$(basename "$p"); rm -rf "packs/$s/data"; ln -s "/data/pack-data/$s" "packs/$s/data"; done \
 && chmod +x /usr/local/bin/dsp-entrypoint \
 && chown -R dsp:dsp /data /app/packs
USER dsp
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1
ENTRYPOINT ["dsp-entrypoint"]
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
