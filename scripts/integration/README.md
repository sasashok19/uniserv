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
# restart api-gateway ALONE, exporting AFTER its .env.local is sourced (that
# file sets WHATSAPP_ACCESS_TOKEN= empty and would otherwise win):
#   cd services/api-gateway && bash -c 'set -a; source .env.local; set +a; \
#     export WHATSAPP_ACCESS_TOKEN=integration-test-token \
#            WHATSAPP_PHONE_NUMBER_ID=1234567890 \
#            WHATSAPP_GRAPH_API_BASE_URL=http://127.0.0.1:9099; exec mvn -o quarkus:dev'
cd services/ai-core && ./.venv/Scripts/python.exe ../../scripts/integration/feature26_whatsapp_menu.py
```

```bash
# The Responses API migration (Feature 27) - needs a real OPENAI_API_KEY and Valkey.
# Makes a handful of real API calls; costs a few thousand tokens.
cd services/ai-core && ./.venv/Scripts/python.exe ../../scripts/integration/feature27_responses_smoke.py
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

## Reading interactive messages

`feature26_whatsapp_menu.py` originally read only `text.body` out of each
recorded send. Features 28 and 29 made the menu an **interactive** message,
whose words live in `interactive.body.text` and whose options are the part that
matters most — so `readable()` now flattens body, footer and every button/row
title into one string the checks assert on. Without it every menu check reads an
empty string and "passes" nothing.

The Feature 29 scenarios also need an **identity** behind the test phone number:
the ticket list is looked up by identity, so a ticket created straight through
the db API has to carry one (`identity_for()`), and the profile checks assert
the name and email actually landed on that row.

Anything a check writes to an identity must be **unique per run** — the email
collision guard (409 `EMAIL_IN_USE`) will correctly refuse a fixed address on
every run after the first, which looks like a bug in the feature and is not.

## Things that will bite you

- **`.env.local` beats your shell.** `dev-local.sh` sources each service's
  `.env.local` with `set -a` *inside* the service subshell, and the gateway's
  sets `WHATSAPP_ACCESS_TOKEN=` (empty). Exporting the integration values before
  `./scripts/dev.sh` therefore does nothing: every send fails with
  `WHATSAPP_ACCESS_TOKEN is not set` and the stub records nothing. Restart the
  gateway on its own with the exports applied **after** the source, as the
  snippet above does.
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

## Why a live smoke test for the Responses API

`feature27_responses_smoke.py` exists because a mocked test cannot catch a
wrong parameter name, a tool schema OpenAI rejects, or a conversation id passed
in the wrong field. The Assistants API it replaced stops answering on
2026-08-26, so "the unit tests pass" was not a good enough answer. It forces a
status enquiry specifically, because that is the one case the instructions tell
the model to answer by calling a tool immediately — the cheapest reliable way to
exercise `function_call` -> `function_call_output` against the real API.

## Results at the time of writing

`feature26_eta.py` 13/13, `feature26_whatsapp_menu.py` 33/33,
`feature27_responses_smoke.py` 6/6.
