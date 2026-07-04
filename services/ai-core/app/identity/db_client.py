"""Async HTTP client for the db-writer identity API (Feature 03 → 04)."""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("ai-core")


class DbWriterClient:
    """Thin wrapper over the db-writer REST API for identity operations."""

    def __init__(self, base_url: str | None = None, internal_key: str | None = None):
        self._base = (base_url or settings.db_writer_url).rstrip("/")
        self._key = internal_key if internal_key is not None else settings.db_writer_internal_api_key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["X-Internal-Key"] = self._key
        return headers

    async def find_by_phone(self, tenant_id: str, phone: str) -> Optional[dict]:
        return await self._find(tenant_id, {"phone": phone})

    async def find_by_email(self, tenant_id: str, email: str) -> Optional[dict]:
        return await self._find(tenant_id, {"email": email})

    async def _find(self, tenant_id: str, params: dict) -> Optional[dict]:
        params = {"tenantId": tenant_id, **params}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/api/v1/db/identities",
                                    params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return data[0] if data else None

    async def create_identity(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{self._base}/api/v1/db/identities",
                                     json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def anon_ref_exists(self, tenant_id: str, anon_ref_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/api/v1/db/identities/anon-check",
                                    params={"tenantId": tenant_id, "anonRefId": anon_ref_id},
                                    headers=self._headers())
            resp.raise_for_status()
            return bool(resp.json().get("exists", False))

    async def enqueue_pending(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{self._base}/api/v1/db/identities/pending",
                                     json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def list_tickets(self, tenant_id: str, **filters) -> list[dict]:
        params = {"tenantId": tenant_id, **{k: v for k, v in filters.items() if v is not None}}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self._base}/api/v1/db/tickets",
                                    params=params, headers=self._headers())
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def create_ticket(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{self._base}/api/v1/db/tickets",
                                     json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
