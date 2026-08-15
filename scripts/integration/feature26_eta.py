"""Feature 26 live-stack integration check: the ticket ETA rule.

Runs against a real dev stack, so this exercises what the unit suites cannot:
migration V14 actually applied, the real SQLite CHECK constraints, and the 422s
arriving over HTTP rather than as thrown exceptions.

The WhatsApp menu half lives in `feature26_whatsapp_menu.py`.

    ./scripts/dev.sh                 # or start db-writer on 8090 yourself
    python scripts/integration/feature26_eta.py
"""

import sys
import time
import uuid

import httpx

DBWRITER = "http://127.0.0.1:8090"
TENANT = "t1"
# Empty in dev means the header is not enforced; this is the seeded dev value.
INTERNAL = {"X-Internal-Key": "local-dev-internal-key"}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""),
          flush=True)
    return ok


def create_ticket(**extra):
    body = {"tenantId": TENANT, "channelOrigin": "whatsapp"}
    body.update(extra)
    r = httpx.post(f"{DBWRITER}/api/v1/db/tickets", json=body, headers=INTERNAL, timeout=20)
    r.raise_for_status()
    return r.json()


def transition(ticket_id, **body):
    return httpx.post(f"{DBWRITER}/api/v1/db/tickets/{ticket_id}/transition",
                      json=body, headers=INTERNAL, timeout=20)


def get_ticket(ticket_id):
    return httpx.get(f"{DBWRITER}/api/v1/db/tickets/{ticket_id}",
                     headers=INTERNAL, timeout=20).json()


def events(ticket_id):
    return httpx.get(f"{DBWRITER}/api/v1/db/tickets/{ticket_id}/events",
                     headers=INTERNAL, timeout=20).json().get("data", [])


def future(days):
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + days * 86400))


def code_of(response):
    try:
        return response.json().get("error", {}).get("code")
    except Exception:  # noqa: BLE001 - a non-JSON body is itself the failure detail
        return None


print("=== The ETA rule, against the real V14 migration ===", flush=True)

t = create_ticket()
tid = t["id"]
check("A1 a new ticket starts open with no ETA", t.get("status") == "open")

r = transition(tid, toStatus="assigned")
check("A2 the first transition is refused without an ETA",
      r.status_code == 422 and code_of(r) == "ETA_REQUIRED", f"{r.status_code} {r.text[:200]}")
check("A3 the refused transition did not move the ticket", get_ticket(tid)["status"] == "open")
check("A4 ...and did not stamp first_transition_at",
      get_ticket(tid)["first_transition_at"] is None)

r = transition(tid, toStatus="assigned", eta="not a date")
check("A5 free text is rejected", r.status_code == 422 and code_of(r) == "ETA_INVALID",
      f"{r.status_code} {r.text[:200]}")

r = transition(tid, toStatus="assigned", eta="2020-01-01")
check("A6 a past ETA is rejected", r.status_code == 422 and code_of(r) == "ETA_IN_PAST",
      f"{r.status_code} {r.text[:200]}")

r = transition(tid, toStatus="assigned", eta=future(3))
check("A7 the first transition succeeds with an ETA", r.status_code == 200,
      f"{r.status_code} {r.text[:200]}")
row = get_ticket(tid)
check("A8 a bare date is stored as end-of-day UTC",
      row["eta_at"] == future(3) + " 23:59:59", str(row.get("eta_at")))
check("A9 first_transition_at is now stamped", bool(row["first_transition_at"]))

r = transition(tid, toStatus="in_progress")
check("A10 later transitions do not re-demand the ETA", r.status_code == 200,
      f"{r.status_code} {r.text[:200]}")

r = httpx.patch(f"{DBWRITER}/api/v1/db/tickets/{tid}",
                json={"eta": future(10), "actorAgentId": "agent-1"},
                headers=INTERNAL, timeout=20)
check("A11 the ETA can be revised",
      r.status_code == 200 and get_ticket(tid)["eta_at"] == future(10) + " 23:59:59")
check("A12 the revision is audited as ticket.eta_changed",
      any(e.get("event_type") == "ticket.eta_changed" for e in events(tid)))

t2 = create_ticket()
r = transition(t2["id"], toStatus="cancelled",
               noteContent="Cancelled during the Feature 26 integration run, no work promised.",
               agentId="agent-1")
check("A13 cancelling needs no ETA", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n===== {passed}/{total} ETA integration checks passed =====")
if passed != total:
    print("\nFAILURES:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}   {detail}")
sys.exit(0 if passed == total else 1)
