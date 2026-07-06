"""OpenAI Assistants API gateway (Feature 06): threads, runs, tool-call loop.

Replaces the Phase-1 rule-based-only conversation path when
``OPENAI_API_KEY``/``OPENAI_ASSISTANT_ID`` are configured. The Assistant object
itself (instructions + tool schemas) is created once via
``scripts/create_assistant.py``; this module only drives per-turn thread/run
state and dispatches tool calls back to the caller.
"""

import json
import logging
from typing import Awaitable, Callable, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.events.client import get_valkey

logger = logging.getLogger("ai-core")

ToolExecutor = Callable[[str, dict], Awaitable[dict]]

TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "expired"}


class OpenAIAssistantGateway:
    """Thin wrapper over ``client.beta.threads`` / ``client.beta.threads.runs``."""

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    def is_available(self) -> bool:
        return bool(settings.openai_api_key and settings.openai_assistant_id)

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    @staticmethod
    def _thread_map_key(tenant_id: str, our_thread_id: str) -> str:
        return f"openai:thread:{tenant_id}:{our_thread_id}"

    async def get_or_create_thread(self, tenant_id: str, our_thread_id: str) -> str:
        """Return the OpenAI thread id mapped to our internal thread id.

        Creates and stores a new OpenAI thread on first use; TTL matches
        ``CONVERSATION_STATE_TTL_HOURS`` so the mapping expires with the rest
        of the conversation state.
        """
        valkey = get_valkey()
        key = self._thread_map_key(tenant_id, our_thread_id)
        existing = await valkey.get(key)
        if existing:
            return existing

        thread = await self.client.beta.threads.create()
        ttl = settings.conversation_state_ttl_hours * 3600
        await valkey.set(key, thread.id, ex=ttl)
        logger.info("created openai thread=%s for threadId=%s", thread.id, our_thread_id)
        return thread.id

    async def run_turn(
        self,
        tenant_id: str,
        our_thread_id: str,
        user_message: str,
        execute_tool: ToolExecutor,
        additional_instructions: Optional[str] = None,
    ) -> str:
        """Post a user message, run the assistant, resolve tool calls, return the reply text."""
        openai_thread_id = await self.get_or_create_thread(tenant_id, our_thread_id)

        await self.client.beta.threads.messages.create(
            thread_id=openai_thread_id, role="user", content=user_message,
        )

        run = await self.client.beta.threads.runs.create_and_poll(
            thread_id=openai_thread_id,
            assistant_id=settings.openai_assistant_id,
            additional_instructions=additional_instructions,
        )

        while run.status == "requires_action":
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            outputs = []
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = await execute_tool(call.function.name, args)
                except Exception as exc:  # noqa: BLE001 - surface to the model, don't crash the run
                    logger.exception("tool call %s failed", call.function.name)
                    result = {"error": str(exc)}
                outputs.append({"tool_call_id": call.id, "output": json.dumps(result)})

            run = await self.client.beta.threads.runs.submit_tool_outputs_and_poll(
                thread_id=openai_thread_id, run_id=run.id, tool_outputs=outputs,
            )

        if run.status != "completed":
            raise RuntimeError(f"assistant run ended in status={run.status}")

        messages = await self.client.beta.threads.messages.list(
            thread_id=openai_thread_id, order="desc", limit=1,
        )
        if not messages.data:
            return ""
        text_parts = [part.text.value for part in messages.data[0].content if part.type == "text"]
        return "\n".join(text_parts).strip()
