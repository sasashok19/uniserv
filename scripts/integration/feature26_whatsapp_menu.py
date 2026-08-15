"""Feature 26 live-stack integration check, scenarios B/C/D (the WhatsApp menu).

Reads the citizen-facing text off a stub standing in for Meta's Graph API,
reached through the adapter's own documented `WHATSAPP_GRAPH_API_BASE_URL` test
seam. So the gateway's real webhook, HMAC check, parser, publisher, Valkey
stream, ai-core consumer, menu state machine and outbound adapter all run for
real; only Meta itself is stubbed.

The consumer group is advanced to the stream tip first: this dev Valkey carries
a large backlog of old seeded email events, each of which makes real (slow)
OpenAI calls, and waiting for it to drain would take longer than the run.
"""

import json
import os
import sys
import time
import uuid

import httpx
import valkey

GATEWAY = "http://127.0.0.1:8080"
DBWRITER = "http://127.0.0.1:8090"
TENANT = "t1"
INTERNAL = {"X-Internal-Key": "local-dev-internal-key"}
SENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent.jsonl")
STREAM = f"{TENANT}:channel.message.received"

vk = valkey.Valkey.from_url("redis://127.0.0.1:6379", decode_responses=True)
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""),
          flush=True)
    return ok


def phone():
    return "+9199" + str(uuid.uuid4().int)[:8]


def send_whatsapp(from_phone, text):
    msg = {"from": from_phone.lstrip("+"), "id": "wamid." + uuid.uuid4().hex,
           "timestamp": str(int(time.time())), "text": {"body": text}, "type": "text"}
    return httpx.post(f"{GATEWAY}/api/v1/webhooks/whatsapp", json={
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {
            "messages": [msg],
            "contacts": [{"profile": {"name": "Integration Test"}}]}}]}],
    }, headers={"X-Hub-Signature-256": "sha256=test_bypass_in_dev"}, timeout=20)


def sent_count():
    if not os.path.exists(SENT):
        return 0
    with open(SENT, encoding="utf-8") as f:
        return sum(1 for _ in f)


def sent_to(from_index, to_phone, timeout=40):
    """Every message body the stub received for this phone since from_index."""
    want = to_phone.lstrip("+")
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = []
        if os.path.exists(SENT):
            with open(SENT, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < from_index:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("body", {}).get("to") == want:
                        out.append(rec["body"].get("text", {}).get("body", ""))
        if out:
            time.sleep(2)   # let a second message of the same turn land
            out = []
            with open(SENT, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < from_index:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("body", {}).get("to") == want:
                        out.append(rec["body"].get("text", {}).get("body", ""))
            return out
        time.sleep(1)
    return []


def turn(from_phone, text):
    """One inbound message; returns everything the citizen gets back."""
    start = sent_count()
    send_whatsapp(from_phone, text)
    return "\n---\n".join(sent_to(start, from_phone))


def session(p):
    raw = vk.get(f"wamenu:{TENANT}:whatsapp:{p}")
    return json.loads(raw) if raw else None


def tenant_config():
    return httpx.get(f"{DBWRITER}/api/v1/db/tenants/{TENANT}", headers=INTERNAL,
                     timeout=20).json().get("config_json") or "{}"


def put_tenant_config(raw):
    httpx.put(f"{DBWRITER}/api/v1/db/tenants/{TENANT}/config",
              json={"configJson": raw}, headers=INTERNAL, timeout=20).raise_for_status()


def create_ticket(**extra):
    body = {"tenantId": TENANT, "channelOrigin": "whatsapp"}
    body.update(extra)
    r = httpx.post(f"{DBWRITER}/api/v1/db/tickets", json=body, headers=INTERNAL, timeout=20)
    r.raise_for_status()
    return r.json()


def messages(ticket_id):
    return httpx.get(f"{DBWRITER}/api/v1/db/tickets/{ticket_id}/messages", headers=INTERNAL,
                     timeout=20).json().get("data", [])


def events(ticket_id):
    return httpx.get(f"{DBWRITER}/api/v1/db/tickets/{ticket_id}/events", headers=INTERNAL,
                     timeout=20).json().get("data", [])


def future(days):
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + days * 86400))


# Skip the stale backlog so the consumer reaches THIS run's messages.
try:
    vk.xgroup_setid(STREAM, "uniserve", "$")
    print("advanced the consumer group past the dev backlog", flush=True)
except Exception as exc:
    print("could not advance the consumer group:", exc, flush=True)

# Absorb the consumer's in-flight blocking XREADGROUP: it was registered against
# the OLD group position, so the first message after a setid waits for that block
# to expire before anything is read. One throwaway turn pays that cost.
print("warming up the consumer...", flush=True)
turn(phone(), "warmup")

original_config = tenant_config()

# Scenarios C and D deliberately mutate the tenant's menu config. Restore it
# from an atexit hook rather than at the end of the script: a run killed
# part-way through Scenario D would otherwise leave the tenant with
# `whatsappMenu.enabled = false` and silently disable the menu for everyone
# afterwards (which is exactly what happened once while writing this).
import atexit


@atexit.register
def _restore_tenant_config():
    try:
        if tenant_config() != original_config:
            put_tenant_config(original_config)
            print("restored the tenant config", flush=True)
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        print("WARNING: could not restore the tenant config:", exc, flush=True)

# ---------------------------------------------------------------------------
print("\n=== Scenario B: the WhatsApp menu, through the real webhook ===", flush=True)

p = phone()
reply = turn(p, "hi")
check("B1 the AI sends the first message", bool(reply), "nothing delivered")
check("B2 it welcomes with the company name", "Welcome to" in reply, reply[:200])
check("B3 it offers all three options",
      all(x in reply for x in ("Press 1", "Press 2", "Press 3")), reply[:200])
check("B4 it mentions the # shortcut", "#" in reply, reply[:200])
check("B5 a menu session exists", (session(p) or {}).get("state") == "menu", str(session(p)))
check("B6 no ticket was created for a greeting",
      httpx.get(f"{DBWRITER}/api/v1/db/tickets", params={"tenantId": TENANT,
                "threadId": f"whatsapp:{p}"}, headers=INTERNAL, timeout=20).json().get("data") == [])

reply = turn(p, "9")
check("B7 an unrecognised key re-shows the options",
      "didn't catch that" in reply and "Press 1" in reply, reply[:200])

reply = turn(p, "1")
check("B8 option 1 asks for the Ticket ID", "Ticket ID" in reply, reply[:200])
check("B9 ...and moves the session", (session(p) or {}).get("state") == "await_ticket_id")

reply = turn(p, "TKT-99999")
check("B10 an unknown ticket ID is reported as not found", "couldn't find" in reply, reply[:200])

other = create_ticket(identityId="somebody-else-entirely")
reply = turn(p, other["ticketNumber"])
check("B11 another citizen's ticket is not readable by guessing its number",
      "couldn't find" in reply, reply[:250])

# A ticket that IS theirs, with a real ETA
mine = create_ticket(threadId=f"whatsapp:{p}")
httpx.post(f"{DBWRITER}/api/v1/db/tickets/{mine['id']}/transition",
           json={"toStatus": "in_progress", "eta": future(4)}, headers=INTERNAL, timeout=20)
reply = turn(p, mine["ticketNumber"])
check("B12 their own ticket returns status, ETA and last updated",
      mine["ticketNumber"] in reply and "Work in progress" in reply
      and time.strftime("%d %b %Y", time.gmtime(time.time() + 4 * 86400)) in reply, reply[:300])
check("B13 ...and invites a note", "add" in reply.lower(), reply[:300])
check("B14 ...and the session waits for one", (session(p) or {}).get("state") == "await_note")

reply = turn(p, "The power is still off after three days")
check("B15 the note is acknowledged and the conversation ends",
      "team will revert" in reply and "main menu will open again" in reply, reply[:300])
check("B16 the session is cleared", session(p) is None)
timeline = [m.get("content") for m in messages(mine["id"])]
check("B17 the note actually landed on the ticket",
      any("still off after three days" in (c or "") for c in timeline), str(timeline)[:250])
check("B18 ...and is auditable as a citizen note",
      any(e.get("event_type") == "ticket.citizen_note" for e in events(mine["id"])))

reply = turn(p, "hello again")
check("B19 a message after the end re-opens the main menu", "Press 1" in reply, reply[:200])

reply = turn(p, "2")
check("B20 option 2 lists the details needed",
      "register a new ticket" in reply.lower() and "1." in reply, reply[:300])
check("B21 ...and hands off to intake", (session(p) or {}).get("state") == "intake")

reply = turn(p, "#")
check("B22 # returns to the main menu", "Press 1" in reply and "Welcome" not in reply, reply[:200])
check("B23 ...and resets the state", (session(p) or {}).get("state") == "menu")

reply = turn(p, "3")
check("B24 option 3 says goodbye", "Thanks for reaching out" in reply, reply[:200])
check("B25 ...with no menu hint attached", "#" not in reply, reply[:200])
check("B26 ...and clears the session", session(p) is None)

# Carry-over
p2 = phone()
reply = turn(p2, "Power cut in Madambakkam since yesterday")
check("B27 a complaint sent first still gets the menu", "Press 1" in reply, reply[:200])
check("B28 ...and is carried over, not discarded",
      "Madambakkam" in ((session(p2) or {}).get("carryOver") or ""), str(session(p2)))

# ---------------------------------------------------------------------------
print("\n=== Scenario C: tenant-configurable copy reaches the citizen ===", flush=True)

try:
    parsed = json.loads(original_config)
except json.JSONDecodeError:
    parsed = {}

branded = dict(parsed)
branded["whatsappMenu"] = {"companyName": "TNEB Integration",
                           "farewell": "Nandri, have a great day"}
put_tenant_config(json.dumps(branded))

p3 = phone()
reply = turn(p3, "hi")
check("C1 the configured company name reaches the welcome",
      "Welcome to TNEB Integration" in reply, reply[:200])
reply = turn(p3, "3")
check("C2 the configured farewell reaches the citizen", "Nandri" in reply, reply[:200])

# ---------------------------------------------------------------------------
print("\n=== Scenario D: the menu can be switched off per tenant ===", flush=True)

off = dict(parsed)
off["whatsappMenu"] = {"enabled": False}
put_tenant_config(json.dumps(off))

p4 = phone()
start = sent_count()
send_whatsapp(p4, "hi")
time.sleep(12)
check("D1 a disabled menu creates no session", session(p4) is None)
check("D2 ...and sends no welcome",
      not any("Press 1" in m for m in sent_to(start, p4, timeout=1)))

put_tenant_config(original_config)
check("D3 the tenant config was restored", tenant_config() == original_config)

# ---------------------------------------------------------------------------
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n===== {passed}/{total} checks passed =====")
if passed != total:
    print("\nFAILURES:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}   {detail}")
sys.exit(0 if passed == total else 1)
