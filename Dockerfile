# syntax=docker/dockerfile:1
#
# SolarWise DZ in one image: the API and the web interface, served by the same process on port 8000.
#
#   docker build -t solarwise-dz .
#   docker run --rm -p 8000:8000 -v solarwise-data:/data \
#       -e SOLARWISE_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
#       -e SOLARWISE_DEMO_MODE=true solarwise-dz
#
# Without DATABASE_URL the data go to a SQLite file in the /data volume. docker-compose.yml runs the same image
# against PostgreSQL.

# ---- 1. build the web interface ----------------------------------------------------------------------------------
FROM node:22-slim AS interface
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. the application ------------------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# An unprivileged account; /data is the only place it writes to.
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin solarwise \
    && mkdir -p /app /data \
    && chown solarwise:solarwise /app /data

COPY backend/pyproject.toml backend/README.md /build/
COPY backend/solarwise /build/solarwise
RUN pip install "/build[postgres]" && rm -rf /build

COPY --from=interface /src/frontend/dist /app/interface

ENV SOLARWISE_ENVIRONMENT=production \
    SOLARWISE_FRONTEND_DIST=/app/interface \
    DATABASE_URL=sqlite:////data/solarwise.db

WORKDIR /app
USER solarwise
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"]

# The schema is created or upgraded when the server starts.
CMD ["solarwise", "serve", "--host", "0.0.0.0", "--port", "8000"]
