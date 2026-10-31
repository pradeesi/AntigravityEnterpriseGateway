# ==============================================================================
# FILE HEADER: Hardened Container Image — Antigravity Admin Policy Studio
# ==============================================================================
# Purpose:
#   Builds a minimal, non-root production container image serving the stateless
#   Antigravity Admin Policy Studio via Gunicorn on Google Cloud Run or GKE.
#
# Architecture / Context:
#   Packages `app.py`, `studio_engine.py`, `validator_engine.py`, `templates/`,
#   and `static/`. Uses `/health` for readiness probing (avoiding `/*z` paths
#   reserved by Google Front End on Cloud Run).
#
# Dependencies / Side Effects:
#   Reads runtime configuration exclusively from environment variables (`PORT`,
#   `LOG_LEVEL`, `MAX_UPLOAD_MB`, `DEFAULT_DEV_USER`). Zero embedded secrets.
# ==============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8090 \
    FLASK_HOST=0.0.0.0 \
    LOG_LEVEL=INFO \
    MAX_UPLOAD_MB=16 \
    DEFAULT_DEV_USER=alice

WORKDIR /app

# Create unprivileged runtime user
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --shell /usr/sbin/nologin --create-home appuser

COPY requirements.txt ./
COPY vendor ./vendor
RUN pip install --no-cache-dir --no-index --find-links=./vendor/wheels -r requirements.txt || \
    pip install --no-cache-dir -r requirements.txt

COPY app.py studio_engine.py validator_engine.py ./
COPY templates ./templates
COPY static ./static

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import os, urllib.request; p = os.getenv('PORT', '8090'); urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=3)" || exit 1

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8090} --workers 2 --threads 4 --timeout 120 app:app"]
