#!/usr/bin/env python
"""One-time sync: push this repo's current tool schema/instructions onto the
ALREADY-CREATED OpenAI Assistant (Feature 06/17).

create_assistant.py only ever creates a brand-new Assistant; it never touches
an existing one. Whenever ASSISTANT_TOOLS/ASSISTANT_INSTRUCTIONS change in
app/conversation/tools.py (e.g. the Feature 17 check_complaint_status tool),
the LIVE Assistant object on OpenAI's platform — identified by
OPENAI_ASSISTANT_ID — does NOT pick up the change on its own; this script is
what applies it, via `client.beta.assistants.update(...)`.

Usage (from services/ai-core):
    python scripts/update_assistant.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from app.config import settings  # noqa: E402
from app.conversation.tools import (  # noqa: E402
    ASSISTANT_INSTRUCTIONS,
    ASSISTANT_TOOLS,
)


def main() -> None:
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not set (check services/ai-core/.env)")
    if not settings.openai_assistant_id:
        raise SystemExit(
            "OPENAI_ASSISTANT_ID is not set — there's no existing Assistant to update. "
            "Run create_assistant.py first."
        )

    client = OpenAI(api_key=settings.openai_api_key)
    assistant = client.beta.assistants.update(
        settings.openai_assistant_id,
        instructions=ASSISTANT_INSTRUCTIONS,
        tools=ASSISTANT_TOOLS,
    )

    print(f"Updated assistant: {assistant.id}")
    print(f"Tools now registered: {[t['function']['name'] for t in ASSISTANT_TOOLS]}")


if __name__ == "__main__":
    main()
