FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-render.txt ./requirements-render.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-render.txt

COPY pyproject.toml ./pyproject.toml
COPY src ./src
COPY scripts/migrate_voice.py ./scripts/migrate_voice.py
COPY data/memory-root ./data/memory-root

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl --fail http://127.0.0.1:${PORT:-10000}/health || exit 1

CMD ["sh", "-c", "if [ \"${REALTIME_VOICE_ENABLED:-false}\" = \"true\" ]; then python scripts/migrate_voice.py; fi; exec python -m uvicorn telesale_agent.entrypoints.api.chat:app --host 0.0.0.0 --port ${PORT:-10000}"]
