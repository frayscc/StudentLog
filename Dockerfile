# syntax=docker/dockerfile:1

# Build the React production bundle first. Node.js is only present in this stage.
FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Runtime image: FastAPI serves both the API and the built React application.
FROM python:3.11-slim AS runtime
ARG INSTALL_ASR=1
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STUDENTLOG_PORT=8765 \
    DATA_DIR=/app/data \
    MODELS_DIR=/app/models \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

COPY backend/requirements.txt backend/requirements-asr.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && if [ "$INSTALL_ASR" = "1" ]; then pip install --no-cache-dir -r /tmp/requirements-asr.txt; fi

COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=frontend-build /frontend/dist ./frontend/dist

# These directories are deliberately outside the image lifecycle. Mount them
# as volumes so student data and downloaded ASR models survive upgrades.
RUN mkdir -p /app/data/avatars /app/data/attachments /app/data/backups /app/data/temp_audio \
    /app/models/paraformer /app/models/sensevoice
VOLUME ["/app/data", "/app/models"]

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8765"]
