"""Feature 27 live smoke test: the Responses API request shape is actually valid.

A mocked test cannot catch a wrong parameter name, a tool schema OpenAI
rejects, or a conversation id passed in the wrong field — and the Assistants
API this replaced sunsets on 2026-08-26, so "it compiles" is not good enough.
This makes a small number of real API calls with the real instructions and the
real tool schemas.

Needs OPENAI_API_KEY (read from ai-core's own settings, i.e. .env.local) and
Valkey on 6379 for the conversation mapping. Costs a few thousand tokens.

    cd services/ai-core
    ./.venv/Scripts/python.exe ../../scripts/integration/feature27_responses_smoke.py
"""

import asyncio
import os
import sys
import uuid

# Importable from anywhere: this script lives outside the service it exercises.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "services", "ai-core"))

from app.config import settings
from app.conversation.openai_gateway import OpenAIResponsesGateway
from app.conversation.tools import responses_tools

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""),
          flush=True)
    return ok


async def main():
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set — cannot smoke-test the live API.")
        return 2

    gateway = OpenAIResponsesGateway()
    check("S1 the gateway reports available with a key alone", gateway.is_available() is True)

    tools = responses_tools()
    check("S2 tools are flat, as the Responses API requires",
          all("function" not in t and "name" in t for t in tools), str(tools)[:200])

    thread = f"smoke:{uuid.uuid4().hex[:8]}"
    calls = []

    async def execute_tool(name, args):
        calls.append((name, args))
        # Refuse, the way the real handler does when intake is incomplete, so
        # the model is forced to reply in words and we exercise a second round.
        return {"error": "intake_incomplete", "missingFields": ["Name", "Email"]}

    # A plain conversational turn.
    reply = await gateway.run_turn(
        "t1", thread, "channel: whatsapp\nmessage: hello",
        execute_tool, additional_instructions="company=TNEB Smoke Test; identity_status=confirmed")
    check("S3 a live turn returns text", bool(reply and reply.strip()), repr(reply)[:200])

    # Second turn on the SAME conversation — proves the conversation id round-trips.
    reply2 = await gateway.run_turn(
        "t1", thread,
        "channel: whatsapp\nmessage: there has been no water supply in Madambakkam for two days",
        execute_tool, additional_instructions="company=TNEB Smoke Test; identity_status=confirmed")
    check("S4 a second turn on the same conversation returns text",
          bool(reply2 and reply2.strip()), repr(reply2)[:200])

    # The tool loop, forced. A status enquiry is the one case the instructions
    # tell the model to answer by calling a tool immediately, so it is the
    # cheapest reliable way to exercise function_call -> function_call_output
    # against the real API — the half of the request shape a mock cannot check.
    status_calls = []

    async def status_tool(name, args):
        status_calls.append((name, args))
        return {"summary": "TKT-00042 (power) - in progress. ETA 18 Aug 2026."}

    reply3 = await gateway.run_turn(
        "t1", f"smoke-status:{uuid.uuid4().hex[:8]}",
        "channel: whatsapp\nchannel_identity_verified: true\n"
        "message: what is the status of my complaint?",
        status_tool, additional_instructions="company=TNEB Smoke Test; identity_status=confirmed")

    check("S5 the model calls our tools over the live API",
          bool(status_calls), "no tool call was made on a status enquiry")
    check("S6 the tool result reaches the model and comes back as text",
          bool(reply3 and reply3.strip()), repr(reply3)[:200])
    if status_calls:
        print(f"         (tools called: {[c[0] for c in status_calls]})")
    if calls:
        print(f"         (intake tools called: {[c[0] for c in calls]})")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n===== {passed}/{total} live Responses API checks passed =====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
