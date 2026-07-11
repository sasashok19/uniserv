# ============================================================
# UniServe :: ai-core (Python 3.11 / FastAPI)
# ============================================================
FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps (presidio/spaCy build needs gcc for some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm \
    && find /usr -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && rm -rf /root/.cache/pip

COPY app ./app

EXPOSE 8001
ENV AI_CORE_PORT=8001
USER nobody
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
