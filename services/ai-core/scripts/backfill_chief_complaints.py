#!/usr/bin/env python
"""One-shot backfill: give every pre-existing ticket a chief complaint (Feature 23).

`tickets.chief_complaint` (migration V12) is written by the live pipeline as
citizen messages arrive, so a ticket created before the field existed stays
blank until its next citizen reply — and for a resolved or closed ticket, that
reply never comes. This walks the tenant's tickets and derives the line from
each one's own inbound message history.

Deliberately a script rather than a migration or a service hook:

- It spends LLM requests (one per ticket), which is not something a Flyway
  migration should do, and not something that should happen implicitly on a
  deploy.
- It is **idempotent**: a ticket that already has a chief complaint is skipped,
  never re-derived. So an interrupted run is resumed by simply running it again,
  and a second run after new tickets arrive costs only the new ones.
- It reads and writes exclusively through db-writer's HTTP API, the same as
  every other ai-core write — no direct database access, so it works
  identically against local dev and a deployed db-writer.

Usage (from services/ai-core, inside the venv):

    python scripts/backfill_chief_complaints.py --dry-run      # look first
    python scripts/backfill_chief_complaints.py                # apply
    python scripts/backfill_chief_complaints.py --limit 20     # trial a few

Options:
    --dry-run             derive and print, write nothing
    --limit N             stop after N tickets that NEEDED a backfill
    --concurrency N       tickets in flight at once (default 4)
    --include-archived    also backfill soft-deleted tickets (default: skip)
    --tenant-id ID        override settings.tenant_id

Environment: reads the same `.env`/`.env.local` as the service, so
`DB_WRITER_URL`, `DB_WRITER_INTERNAL_API_KEY`, `OPENAI_API_KEY` and `TENANT_ID`
all come from there. Point `DB_WRITER_URL` at the deployed db-writer to backfill
a deployed environment. Without an `OPENAI_API_KEY` the run still works — every
line then comes from the deterministic `condense` fallback.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.identity.db_client import DbWriterClient  # noqa: E402
from app.tickets import chief_complaint  # noqa: E402

logger = logging.getLogger("backfill")

# db-writer's own maximum per request; paging at it keeps memory flat and
# matches what the gateway's export does for the same reason.
PAGE_SIZE = 100


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill tickets.chief_complaint (Feature 23)")
    p.add_argument("--dry-run", action="store_true", help="derive and print, write nothing")
    p.add_argument("--limit", type=int, default=None, help="stop after N tickets needing a backfill")
    p.add_argument("--concurrency", type=int, default=4, help="tickets in flight at once (default 4)")
    p.add_argument("--include-archived", action="store_true", help="also backfill soft-deleted tickets")
    p.add_argument("--tenant-id", default=None, help="override settings.tenant_id")
    return p.parse_args()


async def _all_tickets(db: DbWriterClient, tenant_id: str, include_archived: bool) -> list[dict]:
    """Every ticket in the tenant, oldest first, paged at db-writer's maximum.

    Collected up front rather than streamed so the run can report a real total
    ("47 of 312") and so paging is not disturbed by our own writes — we PATCH
    the rows we are iterating, and `sortBy=createdAt` on a live table is not a
    stable cursor while that happens.
    """
    out: list[dict] = []
    page = 1
    while True:
        filters = {"page": page, "pageSize": PAGE_SIZE, "sortBy": "createdAt", "sortDir": "asc"}
        if include_archived:
            filters["includeArchived"] = "true"
        batch = await db.list_tickets(tenant_id, **filters)
        out.extend(batch)
        if len(batch) < PAGE_SIZE:
            return out
        page += 1


async def _backfill_one(db: DbWriterClient, ticket: dict, dry_run: bool) -> tuple[str, str]:
    """Derive and (unless dry-run) store one ticket's chief complaint.

    Returns `(outcome, detail)` where outcome is "written" | "no-text" |
    "failed" — never raises, so one unreadable ticket cannot end the run.
    """
    ticket_id, number = ticket["id"], ticket.get("ticket_number") or ticket["id"]
    try:
        messages = await db.get_messages(ticket_id)
        inbound = [m.get("content") or "" for m in messages if m.get("direction") == "inbound"]
        line = await chief_complaint.derive_from_history(inbound, trace_id=f"backfill:{number}")
        if not line:
            # A ticket whose only inbound messages were intake answers, or one
            # with no inbound message at all (a stub whose citizen never wrote
            # again). Nothing to derive from, and inventing something would be
            # worse than the blank the UI already handles.
            return "no-text", f"{number}: no usable inbound text"
        if not dry_run:
            await db.update_ticket(ticket_id, {"chiefComplaint": line})
        return "written", f"{number}: {line}"
    except Exception as exc:  # noqa: BLE001 - one bad ticket must not end the run
        return "failed", f"{number}: {type(exc).__name__}: {exc}"


async def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tenant_id = args.tenant_id or settings.tenant_id

    print(f"db-writer:  {settings.db_writer_url}")
    print(f"tenant:     {tenant_id}")
    print(f"LLM:        {'yes (' + settings.openai_model + ')' if chief_complaint.available() else 'NO — deterministic fallback only'}")
    print(f"mode:       {'DRY RUN (no writes)' if args.dry_run else 'APPLY'}\n")

    db = DbWriterClient()
    try:
        tickets = await _all_tickets(db, tenant_id, args.include_archived)
    except Exception as exc:  # noqa: BLE001 - a clear message beats a traceback
        print(f"Could not list tickets from {settings.db_writer_url}: {exc}")
        print("Is db-writer running, and is DB_WRITER_URL correct?")
        return 1

    todo = [t for t in tickets if not (t.get("chief_complaint") or "").strip()]
    already = len(tickets) - len(todo)
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"{len(tickets)} tickets, {already} already have a chief complaint, "
          f"{len(todo)} to backfill" + (f" (limited to {args.limit})" if args.limit else "") + "\n")
    if not todo:
        return 0

    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    async def run(ticket: dict) -> tuple[str, str]:
        async with semaphore:
            return await _backfill_one(db, ticket, args.dry_run)

    counts = {"written": 0, "no-text": 0, "failed": 0}
    for coro in asyncio.as_completed([run(t) for t in todo]):
        outcome, detail = await coro
        counts[outcome] += 1
        prefix = {"written": "  ok  ", "no-text": " skip ", "failed": " FAIL "}[outcome]
        print(prefix + detail)

    verb = "would write" if args.dry_run else "written"
    print(f"\n{verb}: {counts['written']}   skipped (no usable text): {counts['no-text']}   "
          f"failed: {counts['failed']}")
    # A non-zero exit on failures so this is safe to run from a deploy script.
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
