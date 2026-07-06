#!/usr/bin/env python
"""One-time setup: create the UniServe OpenAI Assistant (Feature 06).

Creates an Assistant with the identity-gate + info-gathering instructions and
the two function tools (confirm_identity, submit_complaint), then prints its
id. Run once per OpenAI project/environment; the printed asst_... id goes into
OPENAI_ASSISTANT_ID in .env. The running ai-core service never creates or
mutates the Assistant itself — it only opens threads and runs against this id.

Usage (from services/ai-core):
    python scripts/create_assistant.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from app.config import settings  # noqa: E402
from app.conversation.tools import (  # noqa: E402
    ASSISTANT_INSTRUCTIONS,
    ASSISTANT_NAME,
    ASSISTANT_TOOLS,
)


def main() -> None:
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not set (check services/ai-core/.env)")

    client = OpenAI(api_key=settings.openai_api_key)
    assistant = client.beta.assistants.create(
        name=ASSISTANT_NAME,
        instructions=ASSISTANT_INSTRUCTIONS,
        model=settings.openai_model,
        tools=ASSISTANT_TOOLS,
    )

    print(f"Created assistant: {assistant.id}")
    print(f"Model: {assistant.model}")
    print("\nAdd this to services/ai-core/.env (and infrastructure/compose/.env for docker compose):")
    print(f"  OPENAI_ASSISTANT_ID={assistant.id}")


if __name__ == "__main__":
    main()
