"""UniServe ai-core — FastAPI application entrypoint.

Phase 1 scaffold: boots the app and exposes health checks only. The AI
pipeline (identity gate, info gathering, classification, dedup, priority)
is implemented in features 06–10.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.classify.router import router as classify_router
from app.config import settings
from app.conversation.router import router as conversation_router
from app.dedup.router import router as dedup_router
from app.events.client import get_valkey
from app.events.dispatcher import (
    run_ai_reply_send_consumer,
    run_channel_message_consumer,
    run_complaint_ready_consumer,
)
from app.health import router as health_router
from app.identity.router import router as identity_router
from app.pii.router import router as pii_router
from app.priority.router import router as priority_router

# Structured-ish logging (ORCHESTRATOR convention: JSON enforced in Phase 2).
# LOG_LEVEL (env, default INFO) controls verbosity — INFO shows info/warning/
# error/critical (i.e. "log everything" for Phase 1 purposes); set to ERROR
# in production to silence routine info/warning traffic.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"level":"%(levelname)s","service":"ai-core","message":"%(message)s"}',
)
logger = logging.getLogger("ai-core")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("ai-core starting (env=%s, provider=%s)", settings.app_env, settings.default_llm_provider)
    # Feature 01 x 06: channel.message.received -> ConversationAgent.
    # Feature 01 x 09 x 10: complaint.ready -> dedup + priority + ticket.
    # Feature 01 x 14: ai.reply.send -> actually deliver the reply (email today).
    stop_event = asyncio.Event()
    consumer_runners = [run_channel_message_consumer, run_complaint_ready_consumer, run_ai_reply_send_consumer]
    consumer_tasks = [
        asyncio.create_task(runner(get_valkey(), settings.tenant_id, stop_event))
        for runner in consumer_runners
    ]
    try:
        yield
    finally:
        stop_event.set()
        for task in consumer_tasks:
            task.cancel()
        for task in consumer_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="UniServe ai-core", version=__version__, lifespan=lifespan)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(conversation_router)
app.include_router(pii_router)
app.include_router(classify_router)
app.include_router(dedup_router)
app.include_router(priority_router)


@app.get("/")
async def root() -> dict:
    return {"service": "ai-core", "version": __version__, "status": "UP"}
