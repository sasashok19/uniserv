"""UniServe ai-core — FastAPI application entrypoint.

Phase 1 scaffold: boots the app and exposes health checks only. The AI
pipeline (identity gate, info gathering, classification, dedup, priority)
is implemented in features 06–10.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.health import router as health_router

# Structured-ish logging (ORCHESTRATOR convention: JSON enforced in Phase 2).
logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","service":"ai-core","message":"%(message)s"}',
)
logger = logging.getLogger("ai-core")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("ai-core starting (env=%s, provider=%s)", settings.app_env, settings.default_llm_provider)
    if settings.app_env == "development":
        # PHASE_1: mock-data seeding for the AI pipeline is wired in 06_AI_CONVERSATION.
        # Nothing to seed at scaffold stage.
        logger.info("development mode: mock-data seed hook is a no-op until feature 06")
    yield


app = FastAPI(title="UniServe ai-core", version=__version__, lifespan=lifespan)
app.include_router(health_router)


@app.get("/")
async def root() -> dict:
    return {"service": "ai-core", "version": __version__, "status": "UP"}
