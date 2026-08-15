# Session handoff — WhatsApp menu + ETA + duplicate confirmation (F26)
#                   and the OpenAI Responses API migration (F27), 2026-08-15

> Previous handoff (Feature 25, configurable landing page) is DONE and pushed.
> `main` is in sync with `origin/main` as of the start of this session.

## Task (verbatim intent from the user)

1. **Menu-driven WhatsApp conversation.** AI sends the first message: a welcome
   naming the company — **configurable per tenant/team**, not a string literal.
   Menu:
   - `1` → status, **ETA**, last-updated of an existing ticket
   - `2` → register a new ticket
   - `3` → end chat
   Every message must mention **press `#` to return to the main menu**.
2. **Option 1 flow.** Ask for the Ticket ID. On receipt, return details for
   **that one ticket only** (not every ticket linked to the citizen). Invite a
   note/question against that ticket. If the citizen sends one, append it to the
   ticket conversation, confirm "note added, team will revert", then state the
   conversation is ending and ask them to message again to re-open the menu.
3. **New `ETA` field on the ticket**, **mandatory as part of the first transition**.
4. **Option 2 flow.** Reply listing the details needed to register a ticket, then
   run the existing intake/creation flow. On creation, return the ticket details,
   end the conversation, invite any message to re-open the menu.
5. **Option 3** → "Thanks for reaching out. Have a great time".
6. **Stronger duplicate detection.** All duplicates must merge appropriately, and
   the AI must **ask a confirming/disambiguating question before creating** when a
   plausible duplicate exists. Example: an open "Power Cut in Madambakkam"; a new
   "Power cut" must NOT create a ticket until the AI asks which area and the
   citizen answers.
7. Update existing tests + add new ones. **Push only if the integration tests for
   all scenarios pass.**
8. Refine the AI assistant prompt so no edge cases are missed.

## Decisions the user locked in (asked explicitly, 2026-08-15)

1. **Strict menu only** on WhatsApp — not a gate that free text bypasses.
2. **ETA: the agent must set it to move the ticket.** Blocking, enforced server-side.
3. **WhatsApp only** for the menu (ETA + dedup are ticket-domain, so all channels).
4. **A confirmed duplicate attaches as a note to the existing ticket** — no new row.

Assumptions I stated where the user did not specify:
- "Strict" is strict **at the top level**. The menu routes you into a flow; inside
  a flow (awaiting ticket ID / awaiting note / intake form) your text is that
  flow's input. Only `#` pulls you out. Unrecognised input *at the menu* re-shows
  the menu.
- **The first message is never discarded.** Someone opening with "power cut in
  Madambakkam" gets the welcome menu AND that text is stashed; pressing `2`
  reuses it rather than making them retype.
- **Session TTL tenant-configurable, default 12h**, hard-capped at 24h (Meta's
  free-form reply window — a longer session could never be answered).
- **Dashboard is in scope.** The ETA 422 would otherwise break the agent
  transition button.

## Status: STAGES 1-7 DONE AND VERIFIED — unit + live-stack integration green

**Unit suites:**

| Service | Before | Now | Command |
|---|---|---|---|
| db-writer | 23 | **52** | `mvn -o test -Dquarkus.http.test-port=8099` |
| api-gateway | 115 | **154** | `mvn -o test` |
| ai-core | 314 | **410** | `./.venv/Scripts/python.exe -m pytest -q` |
| dashboard | — | tsc + `next build` clean | `npx tsc --noEmit && npx next build` |

`export JAVA_HOME="/c/Program Files/Java/jdk-21.0.10"` first — the machine's is
stale (points at `...\bin`).

**Live-stack integration: 46/46.** New harnesses under `scripts/integration/`
(see its README): `feature26_eta.py` **13/13** and
`feature26_whatsapp_menu.py` **33/33**, run against a real
Valkey + db-writer + api-gateway + ai-core, with `meta_stub.py` standing in for
Meta's Graph API via the adapter's documented `WHATSAPP_GRAPH_API_BASE_URL`
seam. That covers the real webhook, HMAC, parser, event stream, consumer, menu
state machine, V14 migration and outbound adapter.

Three things that cost time and are written up in `scripts/integration/README.md`:
the dev Valkey carries a large replayed-seed backlog (the harness advances the
consumer group past it); the first message after that advance is swallowed by
the consumer's in-flight blocking read (hence a warm-up turn); and an
interrupted run once left `whatsappMenu.enabled = false` on the tenant, so the
config restore is now an `atexit` hook.

**Plus 6/6 live OpenAI checks** for the Feature 27 migration (below).

**Remaining:** nothing in the working tree. The one open decision is whether to
merge `feature-26-whatsapp-menu` into `main` — see "Deploying this" at the end.

| Stage | What | State |
|---|---|---|
| 1 | db-writer — ETA field, migration, transition gate | **DONE, 39/39 green** (was 23, +16) |
| 2 | api-gateway — ETA passthrough, `/tenant/whatsapp-menu` | **DONE, 144/144 green** (was 115, +29) |
| 3 | ai-core — menu state machine, single-ticket status, citizen note | **DONE** |
| 4 | ai-core — duplicate confirm-before-create | **DONE** — ai-core **387/387 green** (was 314, +73) |
| 5 | ai-core — assistant prompt refresh | **DONE** |
| 6 | dashboard — ETA in transition dialog + detail, menu admin panel | **DONE** |
| 7 | docs (README + `docs/*.md`), full re-run, **push** | **DONE** (pushed to `feature-26-whatsapp-menu`) |
| 8 | **Assistants API → Responses API migration (F27)** | **DONE** |

## Feature 27 — Responses API migration (URGENT: Assistants sunsets 2026-08-26)

Eleven days before the deadline at time of writing. `/v1/assistants`,
`/v1/threads` and `/v1/threads/runs` all stop answering on that date, which
would have taken the whole live AI path down.

- `app/conversation/openai_gateway.py` — rewritten as `OpenAIResponsesGateway`
  (old name kept as an alias). Threads → **Conversations**; polling +
  `requires_action` → read `function_call` items from `response.output`, send
  `function_call_output` back, repeat; reply from `response.output_text`.
- **The prompt came home.** Instructions now ship with every request from
  `tools.py` instead of living on a remote Assistant object, so editing the
  prompt no longer needs a push script. `scripts/create_assistant.py` and
  `scripts/update_assistant.py` are **deleted**. The official guide's
  dashboard-managed "Prompts" were deliberately NOT used — that would put the
  prompt back outside git.
- `tools.py` gained `responses_tools()` (nested → flat shape). `strict` is
  deliberately off; these schemas are mostly-optional by design.
- **Valkey prefix changed** `openai:thread:` → `openai:conv:` and had to — an
  old thread id handed to `conversation=` fails every turn until its TTL runs out.
- `is_available()` now needs only `OPENAI_API_KEY`. A deployment with a key but
  no assistant id used to fall back to rule-based and will now use the model.
- `OPENAI_ASSISTANT_ID` is deprecated-but-accepted everywhere (config, `.env`
  examples, compose, `render.yaml`) so existing envs still load.
- A test fails the build if anything under `app/` reaches for the retired
  client attributes again.

**Verified live: 6/6** via `scripts/integration/feature27_responses_smoke.py`
against the real OpenAI API, including the full `function_call` →
`function_call_output` round trip (`check_complaint_status` and
`confirm_identity` both fired).

### Stage 3 — the menu (ai-core)
- `app/conversation/menu_content.py` (NEW) — Python mirror of the Java defaults.
- `app/conversation/menu.py` (NEW) — the state machine. States: `menu`,
  `await_ticket_id`, `await_note`, `intake`. Session in Valkey at
  `wamenu:{tenant}:{thread_key}`.
- `app/conversation/intake_fields.py` — extracted `render_field_form` out of
  `build_identity_request_message` so option 2's "here's what I need" list and
  the AI intake can never ask for different fields.
- `app/events/dispatcher.py` — `_run_menu` runs BEFORE `ensure_ticket_stub` for
  WhatsApp; `finish_registration` closes the conversation on `complaint.ready`
  and REPLACES the ordinary `send_ticket_ack` (two "registered" messages read as
  broken).

### Stage 4 — duplicate confirm-before-create (ai-core)
- `app/classify/message_quality.py` — `match_open_ticket` now also returns
  `question` (the disambiguating question), with `FALLBACK_DUPLICATE_QUESTION`.
  Prompt tells the model to ask for the missing detail, never "is this a
  duplicate?" — a citizen doesn't know what we hold.
- `app/dedup/confirmation.py` (NEW) — pending state at
  `dupconfirm:{tenant}:{thread_key}`, TTL 24h. Deterministic yes/no first
  (incl. Tamil "aama"/"illai"), otherwise re-judge original+answer combined.
- `app/tickets/intake.py` — **rung -1** (a pending answer outranks the whole
  ladder, because "Madambakkam" routes nowhere else) and the `unclear` branch
  now ASKS instead of creating. `_create_flagged_stub` extracted for the
  second-round fallback.

## ⚠️ Deliberate consequence of "strict menu only" — flag to the user

With no live session, a WhatsApp **swipe-reply** and a typed **`TKT-00042`** now
get the welcome menu instead of routing straight to their ticket (Features
19/24 rungs 0-1). That is what strict mode means and the user chose it twice
when asked. It is reversible per tenant via `whatsappMenu.enabled = false`, and
the behaviour is pinned by
`test_a_whatsapp_first_contact_gets_the_welcome_menu_and_creates_no_ticket`.
If the user wants the middle ground, the change is a strong-signal bypass in
`menu.handle_inbound`'s no-session branch.

## Test-infrastructure change worth knowing about

`tests/conftest.py` gained an autouse **`fake_valkey`** fixture (in-memory
client, patches `app.events.client.Valkey` + clears the `lru_cache`). Before it,
every routing test attempted a real Valkey connection and logged a failure;
Feature 26 put real state behind Valkey, so tests need to set it up and assert
on it. Side effect: the ai-core suite went from **116s to 66s**.
`test_event_bus_integration.py` is unaffected (builds its own client, skips when
no broker).

### Stage 1 — db-writer (committed to working tree, not yet git-committed)
- `db/migration/V14__ticket_eta.sql` — adds `eta_at` + `first_transition_at`,
  **backfills `first_transition_at`** from `ticket_events` `status.%` so existing
  tickets don't all demand an ETA on their next touch. Plain additive ALTERs, no
  CHECK change, so no 12-step table rebuild (unlike V9/V11).
- `model/Ticket.java` — two fields + `toMap` entries.
- `tickets/TicketEta.java` (NEW) — pure-function parse/validate. Bare date →
  **23:59:59** of that day (an agent typing `2026-08-18` promises "by the 18th";
  00:00:00 would mark it overdue all day). Rejects free text, ambiguous
  `03/04/2027`, past dates, and >5y (the realistic `2226` typo).
- `tickets/TicketService.java` — `eta` accepted on create/update/transition;
  `ticket.eta_changed` audit event on revision; **the gate**: first transition
  (`first_transition_at is null`) with no ETA → **422 `ETA_REQUIRED`**.
  `cancelled` is exempt. `first_transition_at` is stamped only after every check
  passes, so a rejected transition doesn't burn the one chance to demand an ETA.
- Tests: `TicketEtaTest.java` (NEW, 16).
- **Also fixed an unrelated pre-existing failure**: `UnroutedMessageServiceTest.
  theAskCountLookupIsWhatStopsTheClarifyLoop` hardcoded a contact and
  `@QuarkusTest` writes to a persistent gitignored `uniserve.db`, so the count
  went 1→2→3 on successive runs. Now randomised like the file's own `park`
  helper. Needed because the push gate requires a genuinely re-runnable suite.

### Stage 2 — api-gateway
- `auth/WhatsAppMenuContent.java` (NEW) — defaults/resolve/normalise, same
  single-owner shape as `LandingPageContent`. `companyName` **cascades** to
  `landingPage.brandName` then `"UniServe"`. TTL clamped on READ as well as write
  (`TenantConfigResource` replaces the whole blob, bypassing normalise).
  Rejects a `menuPrompt` that has lost an option number, and a
  `ticketDetails`/`ticketCreated` without `{ticket}`.
- `auth/WhatsAppMenuResource.java` (NEW) — `GET|PUT /api/v1/tenant/whatsapp-menu`,
  admin-only, read-merge-write of `config_json.whatsappMenu`. No public
  counterpart (ai-core reads the blob internally). Already behind `AuthFilter`
  via the existing `api/v1/tenant` prefix — asserted in the test.
- `auth/TicketsResource.java` — forwards `eta` on transition (only when the key
  is present; a null would read as "clear it"); NEW `PATCH /api/v1/tickets/{id}/eta`
  for later revisions, `ticket.edit` permission.
- Tests: `WhatsAppMenuResourceTest.java` (NEW, 20).

## Facts already confirmed by direct reads

**Repo layout.** `services/{ai-core,api-gateway,db-writer}`, `apps/dashboard`,
`packages/{event-contracts,test-stubs}`, `docs/`, `infrastructure/`, `scripts/`.
`render.yaml` at root. ai-core is **Python**; api-gateway is **Java**; dashboard is
**Next.js**.

**ai-core packages:** `app/{classify,conversation,dedup,events,identity,
notifications,pii,priority,tickets}` — note there is ALREADY a `conversation`
package and a `dedup` package. Reuse these; do not add parallel mechanisms.
`app/tickets/` = `chief_complaint.py`, `intake.py`, `service.py`.

**From `docs/02b_ADAPTER_WHATSAPP.md` (read in full):**
- Inbound `POST /api/v1/webhooks/whatsapp` in api-gateway; HMAC-SHA256; dev bypass
  header value `sha256=test_bypass_in_dev` accepted only when `APP_ENV=development`.
  `WhatsAppParser` → publishes `channel.message.received`.
- **Interactive button replies are already parsed** (button title → `rawText`) —
  directly useful for the 1/2/3 menu.
- Outbound: `WhatsAppAdapter.sendReply(toPhone, body, contextMessageId)` behind
  `POST /api/v1/internal/adapters/whatsapp/send`; callers are `TicketNotifier`,
  `TicketsResource`, and ai-core `app/notifications/sender.py`.
- **Meta 24-hour customer-service window is NOT worked around.** Free-form text is
  only allowed within 24h of the citizen's last inbound message. A menu greeting is
  always a reply to an inbound message → safe. Anything proactive is not.
- Existing inbound routing ladder in ai-core `app/tickets/intake.py ::
  ensure_ticket_stub`, in order: (1) `inReplyTo` wamid vs ticket
  `origin_message_id` (F19), (2) explicit `TKT-XXXXX` in text, (3)
  `looks_like_intake_answer` deterministic check → the citizen's in-intake stub
  (F20), (4) identity + same-topic heuristic (F18). **The menu state machine has to
  slot into this ladder, not bypass it.**

**Tenant config precedent (use this, don't invent).** The `config_json`
merge-one-key pattern in api-gateway: `GeneralSettingsResource`,
`PublicNewsConfigResource`, and `LandingPageContent.java` + `LandingPageResource`
(`GET|PUT /api/v1/tenant/landing-page`, admin-only, read-merge-write of
`config_json.landingPage`). The configurable company name / menu copy belongs here
as another key, with a `resolve`(defaults under stored) + `normalise`(validate)
owner class.

## Open design questions (must be settled before/while building)

1. Does the deterministic menu **replace** free-text AI intake on WhatsApp, or sit
   in front of it as a first-contact gate that free text can still bypass?
   (Leaning: gate on first contact / after idle, with free text still understood —
   otherwise F19/F20/F24 routing regresses.)
2. "ETA mandatory as part of first transition" — does it block the **agent's**
   first status transition in the dashboard, or is it AI-estimated at creation?
3. Scope: WhatsApp only, or every channel (email included)?

## Next steps

- [ ] Collect the 3 Explore reports
- [ ] Settle the open questions with the user
- [ ] Implement: tenant menu config → conversation state machine → ETA field +
      migration → dedup confirmation turn → prompt refresh
- [ ] Tests (unit + integration), then docs (`README.md` + `docs/*.md` — MANDATORY
      for this repo), then push only on green integration tests

## Feature 28 — three fixes reported from live use

1. **A citizen answering an agent's follow-up got the welcome menu**, so the
   answer never reached the ticket. The agent's reply is sent by the GATEWAY, so
   ai-core never saw it and no menu session existed. `menu.awaiting_our_reply`
   now checks for a swipe-reply to one of our messages, or a recent unanswered
   outbound on one of their tickets, and hands those to the routing ladder
   instead of greeting them. This is the strict-menu consequence flagged above,
   now closed for the case that actually mattered.
2. **The menu is tappable buttons**, not "Press 1". Meta interactive
   reply-buttons: 3 max, 20-char titles, and it rejects the WHOLE send if a cap
   is exceeded — so caps are truncated in `buildPayload`, rejected on the admin
   screen, and clamped on read. A tap arrives as the button TITLE, so
   `_match_option` matches the tenant's configured labels. A failed interactive
   send retries as plain text. `useInteractiveButtons: false` opts out.
3. **The reply now names the chief complaint** (`{complaint}` in
   `ticketDetails`/`ticketCreated`/`duplicateMerged`), because a status alone
   means nothing to someone holding three open tickets.

New config keys: `menuIntro`, `option1Label`/`option2Label`/`option3Label`,
`complaintUnknown`, `useInteractiveButtons`. All mirrored in Java + Python and
covered by the drift guard — whose own key regex was `[A-Za-z]+` and could not
match `option1Label`; now `[A-Za-z][A-Za-z0-9]*`.

### F28 follow-up: the first cut of fix (1) did not fire in production

Reported still broken after deploy. The ai-core log gave it away — between the
tenant-config read and the send there was **no `find_by_phone` and no
`find_message_by_channel_id`**, so `awaiting_our_reply` never ran at all.

Cause: it was only checked on the **no-session** branch. The citizen had used the
menu earlier, so a session was still live (12h TTL); their answer arrived at the
idle `MENU` state, matched no option, and fell straight to "Sorry, I didn't catch
that". The empty case was covered and the common one was not.

Now checked at `MENU` too, after option matching and before the mis-key
fallback, and a match **clears the session** (the agent has taken the
conversation over). Candidate cap raised 3 -> 5. Two new log lines make the next
one diagnosable without sending logs to anyone:
`whatsapp menu inbound ... state=... option=... replyTo=...` and
`nothing is awaiting this citizen's reply ... rejected=[TKT-x:citizen-spoke-last, ...]`.

Pinned by `test_an_answer_reaches_the_ticket_even_with_a_live_menu_session`.

Note on the gateway log: three consecutive `WhatsApp webhook processed,
published=0` right after an outbound send are Meta's sent/delivered/read status
callbacks, which carry no `messages` array. Normal, not a dropped message.

### F28 follow-up 2: the awaiting check swallowed menu keypresses

Reported as "I selected New ticket and it filed my water-logging complaint onto
TKT-00014". Three compounding bugs, one root:

1. **A chosen option was tested as an answer.** In the no-session branch
   `awaiting_our_reply` ran BEFORE the option match. An agent had an unanswered
   "Is this resolved?" on TKT-00014, so it returned True for everything from
   that citizen — their "3", their "New ticket" tap, and then the complaint they
   typed all bypassed the menu into the routing ladder. They could not escape.
   (`_at_menu` already had the order right; the no-session branch did not.)
2. **`_match_option` matched the FIRST WORD.** "new water logging problem..."
   starts with "new" -> option 2. The first-word rule existed for button titles,
   which are matched against the configured labels now, so it is gone: a menu key
   is the whole message or it is not a menu key.
3. **Rung 2 hijacked an explicitly-new complaint.** Even reaching intake
   properly, `assess_inbound` matched the outstanding "Is this resolved?" and
   filed the new complaint on the old ticket. `MenuOutcome.explicit_new_complaint`
   now flows to `ensure_ticket_stub(explicit_new_complaint=True)`, which skips
   rung 2 only. Rungs 0/1 and the rung-4 duplicate check are untouched.

Also: ETA column added to the ticket queue (sortable, amber when overdue or
never set — `first_transition_at` distinguishes "never picked up" from
"cleared").

Counts after F28: db-writer **52**, api-gateway **171**, ai-core **432**,
dashboard tsc + build clean.

## Deploying this

**Deploy order matters.** db-writer carries migration **V14**, and api-gateway
starts returning `422 ETA_REQUIRED` paths that only make sense once the columns
exist:

1. **db-writer first** (applies V14, backfills `first_transition_at`).
2. api-gateway (ETA passthrough, `/tenant/whatsapp-menu`, `/tickets/{id}/eta`).
3. ai-core (the menu, the duplicate gate, the Responses API migration).
4. dashboard (the ETA picker and the WhatsApp Menu admin tab).

Deploying api-gateway or the dashboard **before** db-writer means an agent
clicking a transition gets a 500 from a missing column rather than a clean 422.

**No new environment variables are required.** `OPENAI_ASSISTANT_ID` can be
deleted from every environment whenever convenient — nothing reads it.

**In-flight WhatsApp conversations reset once**, on the ai-core deploy: the
Valkey key prefix for the OpenAI conversation changed (`openai:thread:` →
`openai:conv:`), so the first message after deploy starts a fresh model context.
The existing `original_complaint` carry-forward already covers this.

**Branch, not main.** This work sits on `feature-26-whatsapp-menu`, pushed. It
was deliberately not merged to `main`: this repo auto-deploys all four services
from `main` with no ordering control, and the V14 migration needs db-writer to
land first. Merge when someone can watch the deploy order.
