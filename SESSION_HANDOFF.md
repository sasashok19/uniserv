# Session handoff — WhatsApp intake-answer bug (Feature 20), 2026-08-03

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

## ACTION REQUIRED AFTER DEPLOY
`ASSISTANT_INSTRUCTIONS` changed, so from `services/ai-core` run once:
`python scripts/update_assistant.py`
against the live `OPENAI_ASSISTANT_ID`. Without it the deployed Assistant
keeps the old instructions (the code-side gates still work; only the model's
phrasing/behaviour guidance is stale).

## Test command
`cd services/ai-core && ./.venv/Scripts/python.exe -m pytest -q`

## Untracked files at repo root
`Big_Fix_Prompt.md`, `Gateway.log`, `ai-core.log` — inputs for this task,
deliberately NOT committed.
