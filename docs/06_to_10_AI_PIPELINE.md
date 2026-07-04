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

## Identity Request Message (per channel)

WhatsApp/Email:
> "Thanks for reaching out. To help you better, could you share your
> email address or mobile number? If you'd prefer to stay anonymous,
> just reply 'anonymous' and we'll still register your complaint."

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
