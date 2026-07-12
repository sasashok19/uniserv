"""Unit tests for cross-channel identity enrichment and merge (Feature 03)."""

import asyncio
from unittest.mock import AsyncMock

from app.events.publisher import BasePublisher
from app.identity.resolver import ChannelIdentityIn, IdentityResolver, ResolveRequest


def _run(coro):
    return asyncio.run(coro)


def _resolver(db):
    publisher = AsyncMock(spec=BasePublisher)
    publisher.publish = AsyncMock(return_value="1-0")
    return IdentityResolver(db, publisher)


def test_phone_not_found_but_native_email_known_enriches_existing_record():
    """Citizen emailed in before (name on file, no phone yet); now provides a
    mobile via the intake form — should enrich that SAME record, not create
    a second one."""
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value=None)
    db.find_by_email = AsyncMock(return_value={"id": "row-1", "master_id": "m-1", "name": "Jane"})
    db.update_identity = AsyncMock(return_value={})

    req = ResolveRequest(
        tenantId="t1",
        channel="email",
        channelIdentity=ChannelIdentityIn(type="email", value="jane@example.com", verified=False),
        confirmedPhone="+919876543210",
        confirmedName="Jane",
    )
    result = _run(_resolver(db).resolve(req))

    assert result == {"masterId": "m-1", "identityStatus": "confirmed", "isNew": False}
    db.update_identity.assert_awaited_once_with("row-1", {"phone": "+919876543210", "name": "Jane"}, trace_id=None)
    db.create_identity.assert_not_called()


def test_phone_found_and_native_email_points_to_different_record_triggers_merge():
    """Two separate records already exist (one from a phone-based channel,
    one from an email-based one) that turn out to be the same person —
    merge them, keeping the phone-based record."""
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"id": "row-phone", "master_id": "m-phone"})
    db.find_by_email = AsyncMock(return_value={"id": "row-email", "master_id": "m-email"})
    db.merge_identity = AsyncMock(return_value={})

    req = ResolveRequest(
        tenantId="t1",
        channel="email",
        channelIdentity=ChannelIdentityIn(type="email", value="jane@example.com", verified=False),
        confirmedPhone="+919876543210",
    )
    result = _run(_resolver(db).resolve(req))

    assert result["masterId"] == "m-phone"
    db.merge_identity.assert_awaited_once_with("row-phone", "m-email", trace_id=None)


def test_phone_found_same_record_both_ways_does_not_merge():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"id": "row-1", "master_id": "m-1"})
    db.find_by_email = AsyncMock(return_value={"id": "row-1", "master_id": "m-1"})
    db.merge_identity = AsyncMock()

    req = ResolveRequest(
        tenantId="t1",
        channel="email",
        channelIdentity=ChannelIdentityIn(type="email", value="jane@example.com", verified=False),
        confirmedPhone="+919876543210",
    )
    result = _run(_resolver(db).resolve(req))

    assert result["masterId"] == "m-1"
    db.merge_identity.assert_not_called()


def test_phone_not_found_and_no_existing_email_creates_fresh():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value=None)
    db.find_by_email = AsyncMock(return_value=None)
    db.create_identity = AsyncMock(return_value={})

    req = ResolveRequest(
        tenantId="t1",
        channel="email",
        channelIdentity=ChannelIdentityIn(type="email", value="new@example.com", verified=False),
        confirmedPhone="+919876543210",
        confirmedName="New Person",
    )
    result = _run(_resolver(db).resolve(req))

    assert result["isNew"] is True
    payload = db.create_identity.await_args.args[0]
    assert payload["phone"] == "+919876543210"
    assert payload["name"] == "New Person"
    assert payload["email"] == "new@example.com"
