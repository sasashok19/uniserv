# Session handoff — Features 20/21/22, 2026-08-03

## Task
Fix the bug described in `Big_Fix_Prompt.md` (repo root), with `Gateway.log`
and `ai-core.log` as the live evidence. Then commit and push. User stepped
away and authorised finishing without stage-by-stage confirmation, and
authorised OpenAI-Assistant-side changes too.

## Status: fix implemented, 240/240 ai-core tests pass, docs updated
Two review agents (code review + solution review) ran against the diff; every
defect they raised is fixed and covered by a test — see "Review findings"
below.

## The bug
WhatsApp `+918939014142`, three messages, three tickets:
1. "No power in my area" → stub TKT-00016 (correct)
2. "Nithya" / "Nithya@gmaill.com" / "56784567" → NEW ticket TKT-00017, and
   the `gmaill.com` typo was accepted onto the identity profile
3. "dharshini.s.raj@gmail.com" → NEW ticket TKT-00018, whose recorded
   "complaint" was the citizen's own email address

## Root cause
`ensure_ticket_stub` (`services/ai-core/app/tickets/intake.py`) routes a
WhatsApp message by identity + open-ticket count, and (Feature 18) asks
`is_same_topic` when exactly one ticket is open. An intake-form ANSWER names
no problem, so `is_same_topic` answers "different topic" — correctly by its
own definition — and each answer became its own ticket. Cascade: conversation
state and the OpenAI thread are keyed on the ticket (`_conv_key` →
`ticket:<id>`), so every split also wiped the assistant's memory of the
original complaint, which is why message 3's ticket recorded an email address
as the complaint text. Separately, the `email` field's validator was literally
`lambda v: bool(v)`.

## Changes (all in services/ai-core)
- `app/tickets/intake.py` — new deterministic `looks_like_intake_answer()`
  (structural signal + statement-word rejection, no LLM); new branch in
  `ensure_ticket_stub` routing an intake answer to the citizen's one
  still-in-intake stub (no `category`) BEFORE the same-topic check, working
  even when several tickets are open so already-split threads self-heal;
  `update_ticket_identity(..., extra_fields=)`.
- `app/conversation/intake_fields.py` — `validate_email`,
  `is_email_syntax_valid`, `suggest_email_correction` (Damerau distance 1 vs
  `KNOWN_EMAIL_DOMAINS` — transposition matters: `gmial`/`hotmial` are
  distance 2 under plain Levenshtein), optional `hint(value)` on a catalog
  spec, surfaced by `missing_fields`.
- `app/conversation/agent.py` — `_ticket_fields_from_intake` (stamps a
  validated Service/Customer ID onto the stub on the turn it's given, both
  paths); `_tool_confirm_identity` refuses to pass an unvalidated email to the
  resolver and falls back to the merged intake state for a valid one;
  `_accept_values_the_citizen_reaffirmed` / `_remember_queried_values` so
  "confirm or correct" actually allows confirming (no infinite re-ask for a
  real-but-unusual domain).
- `app/conversation/tools.py` — `ASSISTANT_INSTRUCTIONS`: intake answers are
  never new complaints; relay the email-correction question verbatim with
  both spellings and never substitute the suggestion.
- Tests: `test_tickets_intake.py` (+13, incl. a 3-message end-to-end
  simulation asserting one ticket), `test_intake_fields.py` (+9),
  `test_conversation.py` (+3).
- Docs: README "Subject-line ticket threading & dedup" (Feature 20 section +
  updated resolution order), `docs/06_to_10_AI_PIPELINE.md`,
  `docs/02b_ADAPTER_WHATSAPP.md`, `docs/03_IDENTITY_RESOLVER.md`.

## Review findings (all fixed)
1. **"Yes" meant the wrong thing.** The question names the suggestion, so
   "yes" must TAKE it; the first cut kept the typo — re-introducing the bug on
   the likeliest reply. Now: yes -> suggestion, resend -> keep theirs.
2. **The correction turn spawned a duplicate.** "no, it's x@gmail.com" and a
   bare "Yes"/"No" were rejected by `looks_like_intake_answer`. Negation is
   now forgiven alongside a concrete value, and a pure yes/no routes home.
3. **A refused `identityValue` email was never recorded**, so the citizen saw
   only "we still need: Email" and retyped the same typo. Both tool routes now
   merge identically.
4. **Ordering hole (found while fixing 1–3):** the model resends every value
   each turn, so a settled correction was undone mid-turn; and an
   extracts-nothing turn erased the refused value entirely. Decisions are now
   remembered and re-applied, and an empty extraction no longer clobbers.
5. **Real domains flagged** (`email.com`, `mailo.com`): added to the known
   set; suggestion ranking now prefers longest-prefix then the common majors.
6. **Trailing whitespace** made `x@gmail.com\n` "a typo of" `x@gmail.com` —
   an unanswerable question. `suggest_email_correction` strips first.
7. **Non-ASCII names, emoji, spaced identifiers** ("சித்ரா", "Thanks 🙏 Nithya",
   "600 042", "Ravi Kumar Sharma", 14-word replies) were all rejected — each
   would have reproduced the original bug. Fixed; word cap raised to 25.
8. **Terse one-word complaints** ("Transformer", "Sewage overflow") read as
   bare names. Utility/service nouns added to the statement-word list; the
   residual risk is documented in the README as a deliberate one-sided trade.

## Constraints honoured
No schema/Flyway change (db-writer's ticket PATCH already accepts
`serviceId`, `TicketService.java:322`; `category` is already in the list
projection, `LIST_COLUMNS`). Email adapter threading, cross-channel merge,
dashboard, RBAC, status transitions and Phase 2 stubs untouched. All 204
pre-existing tests still pass.

## Assistant sync — DONE (2026-08-03)
`scripts/update_assistant.py` was run against the live
`asst_FX75qlIQVJohreLhh2ugyFKm` ("UniServe Complaint Intake Agent",
gpt-4o-mini). Verified by re-fetching it: instructions byte-identical to
`ASSISTANT_INSTRUCTIONS` (6149 chars), tools = confirm_identity,
submit_complaint, check_complaint_status. Re-run this script whenever
`app/conversation/tools.py` changes — the deployed Assistant object does not
pick changes up on its own. `tests/test_tools.py` guards the Feature 20
clauses against a silent revert.

## Test command
`cd services/ai-core && ./.venv/Scripts/python.exe -m pytest -q`

## Untracked files at repo root
`Big_Fix_Prompt.md`, `Gateway.log`, `ai-core.log` — inputs for this task,
deliberately NOT committed.


---

# Features 21 & 22 (same session, later)

## Feature 22 — cross-ticket duplicate detection on EVERY channel
Reported: one sender, two emails 13s apart, both "water logging in my area"
-> TKT-00020 + TKT-00021, on top of a stale TKT-00019. Traced against the real
code: `find_by_email` called 0 times for routing, `is_same_topic` never
reached. Two causes: (a) email skipped the identity branch entirely
(`if channel != "email"`), (b) the count-based rules could only reason about
ONE open ticket — "2+ open -> don't guess -> new ticket" is a refusal to
decide, and a stale stub was open alongside the real one.

- `is_same_topic` (boolean, one ticket) -> `match_open_ticket` (ALL open
  tickets in ONE call, returns index + same/different/unclear).
- `unclear` = the message omits the detail that would settle it -> create the
  ticket, flag `suspectedDuplicateOf`, and have the AI ASK. Nothing merges
  until the citizen answers (`resolve_duplicate` tool).
- Confirmed merge: message appended to the ORIGINAL, this ticket takes the
  existing isDuplicate/parentTicketId/closed treatment, existing
  duplicate-aware citizen ack, plus a `ticket.duplicate_merged` audit event on
  the original (needs the new POST /api/v1/db/tickets/{id}/events).
- LLM unavailable -> per-channel default unchanged (WhatsApp appends, email
  creates). An outage must never start merging separate emails.
- Verified the 3-way prompt against the LIVE model on the user's own scenarios
  (Madambakkam vs Tambaram; water logging vs no power; bare "water logging")
  at temp 0, 3 runs each — all stable and correct.

## Feature 21 — admin-only Cancel + CSV export
- **V11 migration** adds `cancelled` to the status CHECK (SQLite table
  rebuild, same shape as V9). `closed_at` stamped, `resolved_at` left NULL,
  and the SLA query excludes cancelled — otherwise a cancelled ticket with a
  past due date counts as a breach forever.
- Admin only (`ticket.status.to_cancelled`); any non-terminal status; always a
  >=20 char note; dashboard gates on server-provided `canCancel`.
- `GET /api/v1/tickets/export.csv` — same filters as the queue, paged at 100
  internally, capped at 50k with `X-Export-Truncated`, RFC 4180 + CSV-injection
  escaping (citizen-controlled text lands in these cells).
- `ticket.export` already existed in RbacPolicy since Feature 11 with no
  endpoint behind it.

## Tests
ai-core 260, api-gateway 57, db-writer 8 — all pass.
Note: ai-core tests load `.env`, so an unmocked LLM call in a test hits the
network for real. One test was doing that and now patches `match_open_ticket`.

## Deployment for Features 21/22
ALL FOUR: ai-core, db-writer (V11 migration + events endpoint), api-gateway
(cancel/export), dashboard (cancel button, export button). Unlike Feature 20
this is not ai-core-only.

## Still outstanding / not done
- `api.log` shows `auto-close-unconfirmed call failed: status=502
  DB_WRITER_UNAVAILABLE` repeatedly — the stale-stub sweeper is broken in
  production (looks like a Railway cold-start timeout). Not addressed.
- TKT-00019/20/21 already exist; none of this merges them retroactively.
- Suspected-duplicate flag has no dashboard affordance yet: if the citizen
  never answers the question, an agent cannot confirm/dismiss it in the UI.

## Assistant sync for Feature 22 — DONE
`scripts/update_assistant.py` re-run against `asst_FX75qlIQVJohreLhh2ugyFKm`
and verified by re-fetching: 4 tools registered (confirm_identity,
submit_complaint, check_complaint_status, **resolve_duplicate**) and
instructions byte-identical to the repo (7018 chars). `tests/test_tools.py`
guards the duplicate clauses against a silent revert.

---

# Follow-ups (Feature 22b) — both items I had flagged as outstanding

## 1. Auto-close sweep had NEVER run — and it was not db-writer being down
User pushed back on the cold-start theory; they were right. Timestamps from
`api.log` settle it:
  started 14:56:19.999 -> failed 14:56:23.697  (3.7s)
  started 15:07:46.231 -> failed 15:07:52.229  (6.0s)
Quarkus fires an `every="1h"` trigger IMMEDIATELY at startup. This app boots in
~23s, so the first tick ran before the instance was really up and the outbound
connect timed out at 5s. Instances restart often, so that boot tick was in
practice the ONLY tick that ever ran => the sweep had never succeeded.

Fixes: `@Scheduled(delayed="{ticket.auto-close.startup-delay}")` default 2m;
connect timeout 5s -> 20s; retry ONLY connect-phase failures (they prove the
request never arrived, so replaying a POST can't double-apply — a read timeout
deliberately gets no retry).

**Second bug found in the same path:** `DbWriterClient` built its error body
with `Map.of("message", e.getMessage())`, and `Map.of` throws on a null value.
`ConnectException` often has no message, so the handler for an unreachable
db-writer threw an NPE instead of returning 502. That is the NPE that was
escaping the scheduler in the test logs. Covered by
`DbWriterClientRetryTest`.

## 2. Suspected duplicates are now settleable by an agent
The `unclear` flag lived only in Valkey conv state (2h TTL), so if the citizen
never answered, nobody could clear it. Now recorded as a
`ticket.possible_duplicate` event with the target in `meta_json` (no schema
change); the ticket page derives an amber banner from the audit trail
(`outstandingDuplicate`) and Yes/No post to
`POST /api/v1/tickets/{id}/duplicate` (`ticket.edit`), which reuses the exact
same merge treatment as the conversation path. Both trails written.

## Tests after these follow-ups
ai-core 262, api-gateway 59, db-writer 8. Dashboard `tsc --noEmit` clean.

## OpenAI Assistant
NOT re-synced for 22b, and correctly so — `app/conversation/tools.py` is
byte-identical to the version already pushed to
`asst_FX75qlIQVJohreLhh2ugyFKm` (verified with `git diff HEAD`). Re-run
`scripts/update_assistant.py` only when that file changes.

## Deployment for 22b
ai-core, db-writer, api-gateway, dashboard — all four again.
