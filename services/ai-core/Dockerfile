# ============================================================
# UniServe :: ai-core (Python 3.11 / FastAPI)
# ============================================================
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps (presidio/spaCy build needs gcc for some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
# PHASE_1: the spaCy model for presidio is downloaded in 07_PII_SCRUBBER:
#   RUN python -m spacy download en_core_web_lg

COPY app ./app
COPY tests ./tests

EXPOSE 8001
ENV AI_CORE_PORT=8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
