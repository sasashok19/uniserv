# Feature 03 — Identity Resolver

## Phase Scope
- **Phase 1:** Email + WhatsApp identity matching, anonymous flow, timeout job
- **Phase 2:** Extend matching to Twitter handle, IVR caller ID, WebChat session.
  Replace plain text matching with HMAC blind index matching.

## What This Module Does
Python FastAPI service that resolves channel identities to a canonical
`identity_profile`. Detects same person across channels and merges.
Handles anonymous identity tokens and pending identity queue.

---

## Phase 1 Matching Flow

```
WhatsApp (verified=true):
  Normalise phone → E.164
  Lookup by phone in identity_profiles via db-writer API
  Found → return master_id
  Not found → create new profile

Email (verified=false):
  Store in identity_pending_queue
  Signal AI: identity confirmation needed
  On user reply with email:
    Lookup by email in identity_profiles
    Found → merge if needed
    Not found → create new profile

Anonymous declared:
  Create profile with is_anonymous=true
  Generate anon_ref_id (e.g. "ANON-7X3K")
  Return master_id

# PHASE_2: Replace direct field lookup with HMAC blind index lookup
# PHASE_2: phone lookup → phone_idx lookup
# PHASE_2: email lookup → email_idx lookup
```

---

## Normalisation

```python
# PHASE_1: plain text normalisation
def normalise_phone(raw: str) -> str:
    # Strip spaces, dashes → E.164 using phonenumbers library
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)

def normalise_email(raw: str) -> str:
    # Lowercase, strip + aliases for Gmail
    local, domain = raw.lower().split("@")
    local = local.split("+")[0]
    return f"{local}@{domain}"

# PHASE_2: ADD blind index generation
# def blind_index(value: str, pepper: bytes) -> str:
#     return base64.b64encode(hmac.new(pepper, value.encode(), sha256).digest()).decode()
```

---

## Merge Logic

When same person contacts via different channels:
- Keep older profile as canonical
- Move all tickets from newer to older
- Append newer profile's channel_ids to older
- Mark newer as `merged_into: older_master_id`
- Confidence ≥ 0.85 → auto-merge
- Confidence 0.60–0.84 → flag for lead review

---

## Anonymous Identity

```python
def generate_anon_ref() -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=4))
    return f"ANON-{suffix}"
    # Collision-checked against existing anon_ref_ids per tenant
```

---

## Pending Queue Timeout

Background job (runs every 15 min):
- Query `identity_pending_queue` where `timeout_at < now()`
- Update ticket `identity_status = 'timeout'`
- Timeout duration: configurable per tenant (default 48 hours)

---

## Events Consumed
- `{tenant}:channel.message.received`

## Events Emitted
- `{tenant}:identity.resolved` → `{ master_id, identity_status, is_anonymous, anon_ref_id }`
- `{tenant}:identity.pending` → triggers AI identity request
- `{tenant}:identity.merged` → `{ kept_master_id, merged_master_id }`

---

## Environment Variables

```env
IDENTITY_MERGE_CONFIDENCE_THRESHOLD=0.85
IDENTITY_PENDING_TIMEOUT_HOURS=48
IDENTITY_ANON_REF_PREFIX=ANON
DB_WRITER_URL=http://db-writer:8081
VALKEY_URL=redis://valkey:6379
```

---

## Test Stubs

```http
### Resolve identity — WhatsApp (auto-confirmed)
POST http://localhost:8001/api/v1/identity/resolve
Content-Type: application/json

{
  "tenantId": "t1",
  "channel": "whatsapp",
  "channelIdentity": { "type": "phone", "value": "+919876543210", "verified": true },
  "threadId": "thread-wa-001"
}

### Expected
HTTP/1.1 200 OK
{ "masterId": "uuid", "identityStatus": "confirmed", "isNew": true }

### Declare anonymous
POST http://localhost:8001/api/v1/identity/resolve
Content-Type: application/json

{
  "tenantId": "t1",
  "channel": "email",
  "channelIdentity": { "type": "email", "value": null, "verified": false },
  "declaredAnonymous": true,
  "threadId": "thread-em-002"
}

### Expected
HTTP/1.1 200 OK
{ "masterId": "uuid", "identityStatus": "anonymous", "anonRefId": "ANON-7X3K" }

### Same person — email matches existing WhatsApp profile
POST http://localhost:8001/api/v1/identity/resolve
Content-Type: application/json

{
  "tenantId": "t1",
  "channel": "email",
  "channelIdentity": { "type": "email", "value": "rajesh@example.com", "verified": false },
  "confirmedEmail": "rajesh@example.com",
  "threadId": "thread-em-003"
}

### Expected (profile already existed from WhatsApp)
HTTP/1.1 200 OK
{ "masterId": "existing-uuid", "identityStatus": "confirmed", "merged": false }
```

---

## Mock Data Seed

```python
# packages/test-stubs/seed/identity_seed.py
# Creates 5 identity profiles:
# - 2 confirmed via WhatsApp (phone)
# - 1 confirmed via email
# - 1 anonymous (ANON-TEST)
# - 1 pending (timeout not yet reached)
# Runs only when APP_ENV=development
```

---

## Testing
- WhatsApp phone → confirmed, profile created
- Same phone second time → existing profile returned, not duplicated
- Anonymous declared → ANON-XXXX generated, unique per tenant
- Pending queue → 48hr timeout marks ticket as timeout status

---

## Phase 1 Implementation Notes (deviations & corrections)
- `DB_WRITER_URL` is **http://db-writer:8090** (doc says 8081); db-writer runs on 8090 across the stack.
- Anon-ref uniqueness is checked via db-writer `GET /api/v1/db/identities/anon-check`.
- Pending-queue timeout job is **partial**: enqueue + timed-out query exist, but the ticket-status timeout sweep is deferred (tickets don't link to pending entries until later features).
- **Cross-channel merge via citizen-provided email.** `_resolve_phone()`
  previously derived an "email to check for a cross-channel merge" only from
  an address *native* to the channel (i.e. `channel == "email"`). A WhatsApp
  citizen's phone was treated as sufficient identity on its own, so any email
  they later supplied was never fed into the resolver — the same person on
  both channels ended up as two identities. `_resolve_phone()` now also
  honours a citizen-*provided* `confirmedEmail`, so a WhatsApp-solicited email
  actually enriches/merges the identity. This is driven by the intake gate now
  asking WhatsApp users for their email by default (see Feature 15/16,
  *Configurable per-channel intake fields* — `app/conversation/intake_fields.py`
  and the README). Covered by `tests/test_resolver_enrichment.py`.
- **Configurable intake fields.** Which fields the resolver's upstream intake
  gate collects (and which are mandatory) is now tenant-configurable per
  channel, read via `DbWriterClient.get_tenant_config()`. The resolver only
  trusts values whose `source` is `native` or `extracted` (not `known`,
  already-on-file) when deciding what to merge on. See the README's
  *Configurable per-channel intake fields* section.
