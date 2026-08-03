# Feature 06 — AI Conversation Agent

## Phase Scope
- **Phase 1:** Full implementation — identity gate, info gathering, LLM gateway
- **Phase 2:** No structural changes. PHASE_2 comments mark encryption points.

## What This Module Does
Core AI agent loop (Python FastAPI). Runs the identity gate first,
then gathers missing complaint details via LLM follow-up questions.

---

## Identity Gate Decision Tree

```
channel.message.received consumed
  │
  ├─ channelIdentity.verified = true? (WhatsApp)
  │     └─ YES → Skip identity gate. Proceed to info gathering.
  │
  ├─ Thread already confirmed? (returning user)
  │     └─ YES → Proceed to info gathering.
  │
  ├─ Thread in pending state?
  │     └─ Did user provide identity in this message?
  │           ├─ YES → Confirm identity, proceed.
  │           └─ Did user say "anonymous"?
  │                 ├─ YES → Create anonymous profile, proceed.
  │                 └─ NO  → Re-send identity request.
  │
  └─ New thread, identity unknown:
        → Store in identity_pending_queue
        → Send identity request on same channel
        → STOP
```

### Intake answers never start a new ticket (Feature 20)

Every branch above that says "proceed" assumes the message is *about* the
complaint. The reply to the identity request is not — it is a name, an email,
a service ID, a pin code, and nothing else. Ticket routing has to know that
before it reasons about topics at all, or each answer becomes its own ticket
(live-tested: one citizen, three messages, tickets TKT-00016/17/18).

`ensure_ticket_stub` (`app/tickets/intake.py`) therefore checks, ahead of the
content-level duplicate judgment (Feature 18, since replaced by Feature 22's
`match_open_ticket` — see the end of this document):

```
message is purely intake-form data  (looks_like_intake_answer, deterministic — no LLM)
  AND the citizen has exactly ONE open ticket with no category set
      (i.e. one stub still mid-intake, whatever else is open)
        → route to that stub; no LLM judgment runs at all
```

`looks_like_intake_answer` requires a structural signal (an email address, a
form label, a bare 4+ digit identifier, or a one-to-two-word bare name) and
rejects the message if ANY token is a statement/complaint word — which is
what keeps "my phone is not working" from reading as a Mobile-field answer.
It is deliberately LLM-free: it gates whether the LLM check runs, so it must
not itself depend on the LLM being reachable.

## Identity Request Message (per channel)

WhatsApp/Email:
> "Thanks for reaching out. To help you better, could you share your
> email address or mobile number? If you'd prefer to stay anonymous,
> just reply 'anonymous' and we'll still register your complaint."

### Field validation and correction (Feature 20)

Each catalog field (`app/conversation/intake_fields.py`) carries
`extract`/`validate`, and optionally `hint(value)` — what to tell the citizen
when a value is refused. Email uses all three:

- `is_email_syntax_valid` — permissive RFC-lite shape check.
- `suggest_email_correction` — Damerau-Levenshtein-distance-1 match against
  `KNOWN_EMAIL_DOMAINS` (transposition included: `gmial.com`/`hotmial.com`
  are distance **two** under plain Levenshtein and would otherwise pass). A
  domain in the set is always accepted; a domain unlike any of them is never
  second-guessed, so corporate/`.gov.in` addresses pass untouched.
- `hint` → `a confirmed Email — did you mean "x@gmail.com" rather than
  "x@gmaill.com"?`, surfaced through `missing_fields` so the gate stays
  blocked and the assistant asks the citizen to confirm or correct. The
  suggestion is never substituted automatically.

A refused address is also kept out of `IdentityResolver`
(`_tool_confirm_identity`), so a typo never lands on the identity profile
while the correction is pending. Partial intake that IS valid is not held
hostage to it: `update_ticket_identity(..., extra_fields=...)` stamps the
Service/Customer ID onto the stub on the turn it's given, rather than only at
ticket-creation time.

The round-trip, in the order it actually happens:

```
citizen: nithya@gmaill.com
  -> validate_email False, recorded in state["intake"] as invalid
  -> state["queried_intake"]["email"] = "nithya@gmaill.com"
  -> missing_fields emits the hint; the assistant relays it verbatim
citizen: "yes"            -> take the SUGGESTION  (nithya@gmail.com)
citizen: "nithya@gmaill.com" (again) -> keep THEIRS; validator overruled
anything else                        -> still outstanding, ask again
```

"Yes" meaning *the suggestion* is the whole point: the question names the
suggestion, so the opposite reading would re-introduce the typo on the most
likely reply of all. The affirmation check is narrow and only consulted on a
short message — "right"/"same"/"it is" are everywhere in complaint prose — and
`queried_intake` is cleared as soon as the value is settled. A bare resend by
the model never counts; it is told to resend everything it knows on every
call, so only the citizen's own words decide.

`looks_like_intake_answer` correspondingly accepts a pure yes/no message, and
forgives a leading "no"/"yes" **when the message also carries a concrete
value**, so the correction turn itself routes back to the same stub.

Both ways the model can state an email — `identityValue` and
`providedFields` — merge into the intake state identically. Previously only
the latter did, so an address refused on the `identityValue` path vanished
without the citizen ever being told what was wrong with it.

Two ordering rules keep the round-trip intact across a turn:
- A turn that extracts NOTHING for a field no longer overwrites what the
  citizen sent on an earlier turn. Otherwise the refused address is erased at
  the top of the very next turn and the ask degrades to a bare "we still need:
  Email", with nothing for their answer to attach to.
- Each decision is stored (`{"asked": ..., "resolved": ...}`) and re-applied,
  because the model resends every value it knows on every `confirm_identity`
  call — without that, a correction settled at the top of the turn is quietly
  undone when the resent original is merged back in a few lines later. A
  record for a different value is stale and gets replaced, so a second bad
  address is queried in its own right.

---

## Info Gathering

Required before classification:
- `complaint_summary` — what happened (1–3 sentences)
- `category_hint` — billing / service / product / technical / other

Agent asks at most **2 follow-up questions**. After 2 questions or
once `complaint_summary` present → emit `complaint.ready`.

---

## LLM Gateway

```python
class LLMGateway:
    async def complete(self, system_prompt: str,
                       messages: list[dict],
                       max_tokens: int = 500) -> str:
        # Routes to configured provider per tenant
        # Wraps with PII scrubber (07_PII_SCRUBBER)
        # Logs token usage (no PII in logs)
        # PHASE_2: decrypts content before sending, re-encrypts after
        ...
```

Supported: `anthropic`, `openai`, `gemini`, `ollama`.

---

## Conversation State (Valkey, TTL 2h)

```json
{
  "identity_status": "confirmed | anonymous | pending",
  "master_id": "uuid | null",
  "messages": [{"role": "user|assistant", "content": "..."}],
  "extracted_fields": { "complaint_summary": "...", "category_hint": "..." },
  "questions_asked": 0
}
```

---

## Events Consumed
- `{tenant}:channel.message.received`
- `{tenant}:identity.resolved`

## Events Emitted
- `{tenant}:ai.reply.send`
- `{tenant}:complaint.ready`

---

## Environment Variables

```env
AI_CORE_PORT=8001
CONVERSATION_STATE_TTL_HOURS=2
AI_MAX_FOLLOWUP_QUESTIONS=2
DEFAULT_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
VALKEY_URL=redis://valkey:6379
DB_WRITER_URL=http://db-writer:8081
```

---

## Test Stubs

```http
### Trigger AI processing for a test event (dev only)
POST http://localhost:8001/api/v1/internal/process-test-event
Content-Type: application/json

{
  "tenantId": "t1",
  "channel": "whatsapp",
  "channelIdentity": { "type": "phone", "value": "+919876543210", "verified": true },
  "rawText": "My electricity bill for March is double the usual amount",
  "threadId": "thread-test-001"
}

### Expected — complaint clear enough, no follow-up needed
HTTP/1.1 200 OK
{
  "identityStatus": "confirmed",
  "questionsAsked": 0,
  "complaintReady": true,
  "extractedFields": { "complaint_summary": "...", "category_hint": "billing" }
}

### Test identity gate — unknown email sender
POST http://localhost:8001/api/v1/internal/process-test-event
Content-Type: application/json

{
  "tenantId": "t1",
  "channel": "email",
  "channelIdentity": { "type": "email", "value": "unknown@test.com", "verified": false },
  "rawText": "I have a complaint about my bill",
  "threadId": "thread-test-002"
}

### Expected — identity gate triggered
HTTP/1.1 200 OK
{
  "identityStatus": "pending",
  "identityRequestSent": true,
  "complaintReady": false
}

### Test AI unavailable graceful degradation
POST http://localhost:8001/api/v1/internal/test-llm-health
### Expected when LLM down
HTTP/1.1 200 OK
{ "llmAvailable": false, "fallback": "rule_based_classification" }
```

---

## Testing
- WhatsApp verified → identity gate skipped, complaint.ready emitted
- Email unverified → identity request sent, processing stopped
- User replies "anonymous" → anonymous profile, processing continues
- Vague complaint → exactly 1 follow-up question sent
- After 2 questions → complaint.ready emitted regardless

---

# Feature 07 — PII Scrubber

## Phase Scope
- **Phase 1:** Strip PII before LLM calls, token store, rehydration
- **Phase 2:** Full field-level encryption using PiiEncryptionService (see 15)

## What This Module Does
Detects and removes PII from text before any LLM API call.
After LLM responds, rehydrates original values back.

---

## Phase 1 — Scrub/Rehydrate

```python
# PHASE_1: token replacement before LLM
class PIIScrubber:
    async def scrub(self, text: str, trace_id: str) -> ScrubResult:
        # Presidio detects: PERSON, PHONE, EMAIL, LOCATION
        # India-specific: IN_AADHAAR, IN_PAN, IN_MOBILE
        # Replace with [PERSON_1], [PHONE_1], etc.
        # Store token map in Valkey (TTL 10 min)
        ...

    async def rehydrate(self, text: str, trace_id: str) -> str:
        # Fetch token map from Valkey
        # Replace tokens with original values
        ...

# PHASE_2: ADD field-level encryption
# PiiEncryptionService.encrypt(plaintext) called in DB Writer
# PiiEncryptionService.decrypt(ciphertext) called before display
```

---

## Environment Variables

```env
PII_SCRUBBER_ENABLED=true   # false for local dev only
PII_TOKEN_TTL_MINUTES=10
PRESIDIO_LANGUAGE=en
```

---

## Test Stubs

```http
### Test PII scrubbing
POST http://localhost:8001/api/v1/internal/pii/scrub
Content-Type: application/json

{
  "text": "My name is Rajesh Kumar, phone +91 98765 43210, Aadhaar 1234 5678 9012",
  "traceId": "test-trace-001"
}

### Expected
HTTP/1.1 200 OK
{
  "scrubbed": "My name is [PERSON_1], phone [PHONE_1], Aadhaar [IN_AADHAAR_1]",
  "entitiesFound": ["PERSON", "PHONE_NUMBER", "IN_AADHAAR"],
  "tokenCount": 3
}

### Test rehydration
POST http://localhost:8001/api/v1/internal/pii/rehydrate
Content-Type: application/json

{
  "text": "Thank you [PERSON_1], your complaint has been registered.",
  "traceId": "test-trace-001"
}

### Expected
HTTP/1.1 200 OK
{ "rehydrated": "Thank you Rajesh Kumar, your complaint has been registered." }
```

---

# Feature 08 — Classification

## Phase Scope
- **Phase 1:** Full implementation
- **Phase 2:** No changes

## What This Module Does
Classifies complaint into category/subcategory. Detects intent and sentiment.

---

## Classification Prompt Strategy

```
System: You are a complaint classifier for {tenant_name}.
Classify into exactly one category from: {category_list_from_tenant_config}
Return JSON only:
{
  "intent": "complaint|feedback|query|compliment",
  "category": "...",
  "subcategory": "...",
  "confidence": 0.0-1.0,
  "sentiment_score": -1.0 to 1.0,
  "keywords": ["..."]
}
If confidence < 0.5: set category="other"

User: {scrubbed_complaint_text}
```

## Events Consumed: `{tenant}:complaint.ready`
## Events Emitted: `{tenant}:complaint.classified`

---

## Test Stubs

```http
### Classify a complaint
POST http://localhost:8001/api/v1/internal/classify
Content-Type: application/json

{
  "tenantId": "t1",
  "text": "My electricity bill for March is double the usual amount. This is the second time this has happened.",
  "traceId": "test-trace-003"
}

### Expected
HTTP/1.1 200 OK
{
  "intent": "complaint",
  "category": "billing",
  "subcategory": "incorrect_amount",
  "confidence": 0.91,
  "sentimentScore": -0.72,
  "keywords": ["bill", "double", "March"]
}

### Classify ambiguous complaint
POST http://localhost:8001/api/v1/internal/classify
Content-Type: application/json

{ "tenantId": "t1", "text": "Something is wrong", "traceId": "test-trace-004" }

### Expected (low confidence → other)
HTTP/1.1 200 OK
{ "intent": "complaint", "category": "other", "confidence": 0.31 }
```

---

# Feature 09 — Deduplication

## Phase Scope
- **Phase 1:** Email + WhatsApp dedup
- **Phase 2:** Extend to Twitter, IVR, WebChat

## What This Module Does
Detects if incoming classified complaint is duplicate of existing open ticket.
If duplicate: appends. If new: creates.

---

## Detection Levels

1. **Same identity, same category, last 30 days** → HIGH confidence → auto-append
2. **Same identity, different channel** → HIGH → auto-append, log new channel
3. **3+ different identities, same category, within 60 min** → cluster ticket
4. **Exact text match 3x in 10 min, different identities** → spam flag

## Events Consumed: `{tenant}:complaint.classified`
## Events Emitted: `{tenant}:ticket.action.resolved`

---

## Test Stubs

```http
### Test deduplication — same identity, same category
POST http://localhost:8001/api/v1/internal/deduplicate
Content-Type: application/json

{
  "tenantId": "t1",
  "masterId": "i1",
  "category": "billing",
  "subcategory": "incorrect_amount",
  "traceId": "test-trace-005"
}

### Expected (existing open billing ticket for i1)
HTTP/1.1 200 OK
{
  "action": "append_to_existing",
  "existingTicketId": "ticket-uuid",
  "confidence": "high",
  "reason": "Same identity, same category, ticket open 2 days ago"
}

### Expected (no existing ticket)
HTTP/1.1 200 OK
{ "action": "new_ticket", "confidence": "high" }
```

---

# Feature 10 — Priority Engine

## Phase Scope
- **Phase 1:** Full implementation
- **Phase 2:** Twitter urgency factor added (public ministerial mention = +3 boost)

## What This Module Does
Calculates priority score 0–10 for every ticket.

---

## Scoring Factors (Phase 1)

| Factor | Weight |
|---|---|
| Sentiment severity | 25% |
| SLA urgency | 25% |
| Repeat contact | 20% |
| Category severity (tenant config) | 15% |
| Channel severity | 10% |
| Vulnerability signal (keywords) | 5% |

## Channel Severity Scores (Phase 1)
- WhatsApp: 5
- Email: 4
- **PHASE_2:** Twitter public: 8, IVR: 7, WebChat: 4

## Priority Labels
- 8.0–10.0: `critical`
- 6.0–7.9: `high`
- 4.0–5.9: `medium`
- 0.0–3.9: `low`

## Events Consumed: `{tenant}:ticket.action.resolved`
## Events Emitted: `{tenant}:ticket.prioritised`

---

## Test Stubs

```http
### Score a ticket
POST http://localhost:8001/api/v1/internal/priority/score
Content-Type: application/json

{
  "tenantId": "t1",
  "sentimentScore": -0.85,
  "slaHoursRemaining": 1.5,
  "slaHoursTotal": 48,
  "repeatContactCount": 2,
  "categoryLabel": "outage",
  "channel": "whatsapp",
  "vulnerabilityKeywordsFound": ["emergency"]
}

### Expected
HTTP/1.1 200 OK
{ "score": 8.7, "label": "critical" }
```

---

## Phase 1 Implementation Notes (deviations & corrections)
- **No LLM API key in dev**, so classification (08) and info-gathering/summary (06) use the documented **rule-based fallback**; `test-llm-health` reports `{llmAvailable:false, fallback:"rule_based_classification"}`.
- **07 PII scrubber** uses **regex + a "name is" heuristic + a Valkey token store** (TTL) rather than Presidio — Presidio needs a spaCy model not shipped in the image. Entity labels/token format match the spec (PERSON, PHONE_NUMBER, IN_AADHAAR, ...).
- `DB_WRITER_URL` is `http://db-writer:8090` (doc says 8081).
- **09 dedup** matches on the identity reference passed as `masterId` against `tickets.identity_id`.
- **Priority scoring can use a tenant AI rubric (Feature 3).** `create_ticket_from_complaint` calls `_score_priority` (`app/tickets/service.py`), which reads the tenant's `priorityRubric` config key: when it's non-empty AND an OpenAI key is set, `app/priority/llm_scorer.py:score_with_rubric` asks the LLM to apply the rubric and return strict JSON `{score, label}` (score clamped to 0–10, label derived from `engine.label_for` when absent/invalid). Any missing rubric/key or LLM error/timeout falls back to the deterministic engine (`app/priority/engine.py`) — ticket creation never breaks. Admin authoring via `GET|PUT /api/v1/tenant/priority-rubric` (gateway); the GET default is a prose writeup of the current engine. Covered by `tests/test_llm_scorer.py` and rubric-path cases in `tests/test_tickets_service.py`.
- **Per-turn intake instructions are DIRECTIVE, not a passive hint.** The
  assistant's base instructions ("ask for an email or phone number") used to
  win over the tenant's configured intake fields — e.g. a tenant requiring
  Name + Service/Customer ID on email saw the bot ask for a mobile number
  instead. `_render_additional_instructions` now tells the model explicitly:
  the sender's email address is already known (never ask for it), ask for ALL
  the tenant's required fields in one message and nothing else, and pass the
  citizen's stated name in `confirm_identity`'s `name` argument. Still
  best-effort relative to the rule-based gate, but behaviourally aligned.
- **Follow-up-question budget is tenant-configurable (Feature 4).** `_effective_max_followups(tenant_config)` (`app/conversation/agent.py`) reads `generalSettings.maxFollowupQuestions` (valid int 0–5) with the `AI_MAX_FOLLOWUP_QUESTIONS` env value as fallback; both the rule-based path and the assistant path's `_render_additional_instructions` use it. Admin authoring via `GET|PUT /api/v1/tenant/general-settings`.
- **Fixed: a citizen's reply and the AI's own reply on an already-open ticket didn't appear in the dashboard's Conversation panel.** Root cause was two independent gaps, not a wrong table — `ticket_messages` (the table backing Conversation) was only ever written from two places: `TicketsResource.reply()` (an agent's own reply, api-gateway) and `create_ticket_from_complaint()` (`app/tickets/service.py`), which only runs when a turn actually publishes `complaint.ready`. (1) Any turn judged "vague" or otherwise not complaint-ready — including a routine follow-up reply on a ticket that's already been created, e.g. one moved to `pending_customer` — published no `complaint.ready` and so was never persisted anywhere, even though the AI still processed it and replied. (2) Every AI-generated reply (`ConversationAgent._send_reply`, → `ai.reply.send` → `app/notifications/sender.py`) was only ever emailed out, with no code path writing it to `ticket_messages` at all — 100% of AI replies were invisible in Conversation, not just this case.

  Fixed with two additions in `app/conversation/agent.py`, both best-effort (a persistence failure logs a warning and never blocks the reply the citizen is waiting on): `_persist_inbound()` writes the citizen's raw message (`authorType=user, direction=inbound`) from every turn that does NOT itself publish `complaint.ready` this turn — the rule-based path checks its own `complaint_ready` local; the assistant path tracks whether `execute_tool` was called with `"submit_complaint"` this turn via a `submitted_this_turn` flag, since that's the assistant-path equivalent signal. `_persist_outbound_ai_reply()` writes every AI reply (`authorType=ai, direction=outbound, isAiGenerated=1`) unconditionally from `_send_reply`, the single choke point both the rule-based and assistant paths already funnel through. Turns that DO publish `complaint.ready` deliberately skip the inbound persist here, since `create_ticket_from_complaint` persists that same turn's message itself (with its richer intake-augmented content) — persisting both would double the citizen's message in Conversation. Covered by tests in `services/ai-core/tests/test_conversation.py` (identity-gate turn, vague-followup turn, complaint-ready turn — regression guard against the double-persist — and both assistant-path branches).
- **Conversation memory is keyed by the ticket, not the email thread (re-ask fix).** `ConversationAgent._conv_key()` (`app/conversation/agent.py`) keys both the Valkey conversation state and the OpenAI thread on `ticket:<ticketId>` when a ticket exists, falling back to the per-message `_thread_key` only for direct/test calls. Previously memory was keyed by `_thread_key`, which changes with every inbound Message-ID/In-Reply-To — a citizen's reply threads off *our* identity-request email, so each turn landed on a fresh key and the assistant lost the original complaint and re-asked for it. The assistant path also now stores the citizen's first message as `original_complaint` in state and injects it into the per-turn `additional_instructions` ("treat this as the complaint_summary; do not ask them to repeat it"), so the complaint survives even if the OpenAI thread is reset (e.g. state TTL). Covered by `tests/test_thread_key.py` (`_conv_key` cases).

---

## Cross-ticket duplicate detection (Feature 22)

Routing asks ONE question per inbound message, covering every open ticket the
citizen has:

```
match_open_ticket(candidates, new_text)   # app/classify/message_quality.py
  -> {"index": <position|None>, "verdict": "same"|"different"|"unclear"}
```

The citizen's open complaints are presented as a numbered list and the model
names which one this message concerns. One call regardless of how many are
open — per-ticket calls would cost N requests per message and leave the caller
reconciling N independent verdicts, including two saying "same".

`ensure_ticket_stub` resolution order (`app/tickets/intake.py`):

```
1. in_reply_to matches a ticket's origin_message_id          (Feature 19)
2. explicit TKT-XXXXX in the subject or body                 (Feature 15/17)
3. the citizen's ONE in-intake stub, if this is form data    (Feature 20)
4. match_open_ticket over every open ticket                  (Feature 22)
     same      -> that ticket
     unclear   -> new stub + suspectedDuplicateOf, and ASK
     different -> fall through
5. thread_key, if still open
6. a fresh stub
```

Steps 1–3 are structural and cost nothing; step 4 is the only LLM call.

**Same problem AND same place.** "Water logging in Madambakkam" and "water
logging in Tambaram" are different complaints; so are "water logging" and "no
power" in one locality. `unclear` exists for the case the boolean check could
not express: the new message omits the detail (usually the location) the open
one specifies, so any answer would be a guess.

**`unclear` asks rather than guesses.** The stub carries
`suspectedDuplicateOf` → `TestEventRequest` → `_render_additional_instructions`,
which hands the model the other complaint's own words so it can ask a specific
question. `resolve_duplicate(isDuplicate)` then acts on the citizen's answer:
on `true` their message is appended to the ORIGINAL, this ticket takes the
existing duplicate treatment (`isDuplicate`/`parentTicketId`/closed), and a
`ticket.duplicate_merged` event is written to the original's audit trail; on
`false` the suspicion is dropped and this ticket stands alone. The tool refuses
outright if routing never raised a suspicion, so the model cannot merge tickets
on its own initiative.

**Failure direction is per-channel, on purpose.** `match_open_ticket` returning
`None` is a network condition, not a verdict, so each channel keeps its
long-standing default: WhatsApp appends to a sole open ticket, email creates a
new one. An LLM outage must never start merging a citizen's separate emails.
