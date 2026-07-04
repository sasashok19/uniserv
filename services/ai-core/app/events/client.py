"""Shared async Valkey client for ai-core.

A single lazily-created connection pool is reused across the app (health checks,
publishers, consumers). Valkey is Redis-compatible, so the ``valkey`` client
mirrors ``redis-py``.
"""

import logging
from functools import lru_cache

from valkey.asyncio import Valkey

from app.config import settings

logger = logging.getLogger("ai-core")


@lru_cache(maxsize=1)
def get_valkey() -> Valkey:
    """Return the shared async Valkey client (created on first use)."""
    return Valkey.from_url(settings.valkey_url, decode_responses=True)


async def valkey_ping() -> bool:
    """Return True if Valkey answers PING, False on any connection error.

    Used as the ai-core readiness dependency (Feature 01).
    """
    try:
        return bool(await get_valkey().ping())
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        logger.warning("valkey ping failed: %s", exc)
        return False
