# Live-stack integration checks

Scripts that drive a **running** UniServe stack end to end, covering the seams
the unit suites necessarily mock: the real Meta-shaped webhook, HMAC validation,
the parser, the Valkey stream, ai-core's consumer, the menu state machine, the
real Flyway migrations and SQLite CHECK constraints, and the outbound adapter.

They are plain scripts rather than pytest cases on purpose — they need a stack,
they mutate the dev database, and the existing `pytest` suites are deliberately
hermetic (see `services/ai-core/tests/conftest.py`).

## Running them

```bash
./scripts/dev.sh                    # db-writer 8090, api-gateway 8080, ai-core 8001, Valkey 6379

# The ETA rule — needs db-writer only
cd services/ai-core && ./.venv/Scripts/python.exe ../../scripts/integration/feature26_eta.py

# The WhatsApp menu — needs the whole stack plus the Meta stub below
python scripts/integration/meta_stub.py &        # listens on 9099
# restart api-gateway with:
#   WHATSAPP_ACCESS_TOKEN=integration-test-token \
#   WHATSAPP_PHONE_NUMBER_ID=1234567890 \
#   WHATSAPP_GRAPH_API_BASE_URL=http://127.0.0.1:9099
cd services/ai-core && ./.venv/Scripts/python.exe ../../scripts/integration/feature26_whatsapp_menu.py
```

Each script prints one PASS/FAIL line per check and exits non-zero if any fail.

## Why the Meta stub

`meta_stub.py` stands in for Meta's Graph API, reached through the adapter's own
documented `WHATSAPP_GRAPH_API_BASE_URL` test seam — the same seam
`WhatsAppAdapterTest` already uses. Everything up to and including
`WhatsAppAdapter.sendReply` runs for real; only Meta is replaced. It records each
send to `sent.jsonl`, which is how the menu script reads the exact text a citizen
would have received. Without it, a dev box with no `WHATSAPP_ACCESS_TOKEN` fails
every outbound send and the replies are invisible.

## Things that will bite you

- **The dev Valkey accumulates a backlog.** Seeded email events are replayed on
  every gateway start and each one makes real (slow) OpenAI calls, so ai-core's
  consumer can be hundreds of messages behind. The menu script advances the
  consumer group to the stream tip (`XGROUP SETID ... $`) before it starts.
  That **discards** the pending backlog — fine for a dev box, not something to
  run anywhere you care about those messages.
- **After a `SETID`, the first message is slow.** The consumer is already parked
  in a blocking `XREADGROUP` registered against the old position, so it does not
  see the new one until that block expires. The script sends one throwaway
  warm-up message to absorb it.
- **`X-Internal-Key`** is required by db-writer whenever
  `DB_WRITER_INTERNAL_API_KEY` is set; the scripts use the seeded dev value.
- The scripts **write to the dev database** (tickets, tenant config). Tenant
  config is saved and restored; the tickets they create are left behind.

## Results at the time of writing (Feature 26)

`feature26_eta.py` 13/13, `feature26_whatsapp_menu.py` 33/33.
