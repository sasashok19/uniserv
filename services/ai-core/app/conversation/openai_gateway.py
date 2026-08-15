"""OpenAI Responses API gateway (Feature 06, migrated in Feature 27).

Replaces the Phase-1 rule-based-only conversation path when ``OPENAI_API_KEY``
is configured. Drives per-turn conversation state and dispatches tool calls
back to the caller.

**Why this was rewritten.** It previously used the Assistants beta endpoints,
which OpenAI sunsets on **26 August 2026** — after that date `/v1/assistants`,
`/v1/threads` and `/v1/threads/runs` all stop answering, which would have taken
the entire live AI path down with them. (``test_conversation.py`` asserts no
module under ``app/`` reaches for those client attributes again, so the literal
names are deliberately not spelled out here.)

Three things changed in the port, and the second is an improvement rather than
a like-for-like swap:

1. **Threads became Conversations.** Same idea — server-side state, one id per
   citizen conversation, mapped in Valkey with the same TTL.
2. **The prompt came home.** The instructions used to live on a remote Assistant
   object that ``scripts/update_assistant.py`` had to push; editing
   ``tools.py`` changed nothing until somebody remembered to run it. Now they
   are sent with every request, straight from git, so that whole class of drift
   is gone and the two sync scripts are deleted. (The official migration guide
   suggests dashboard-managed "Prompts" referenced by id — deliberately not
   used here, because it recreates exactly the problem this fixes.)
3. **No more run polling.** Responses are synchronous. The
   ``requires_action`` / ``submit_tool_outputs_and_poll`` dance becomes: read
   ``function_call`` items out of ``response.output``, execute them, send
   ``function_call_output`` items back, repeat until the model stops asking.
"""

import json
import logging
from typing import Awaitable, Callable, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.conversation.tools import ASSISTANT_INSTRUCTIONS, responses_tools
from app.events.client import get_valkey

logger = logging.getLogger("ai-core")

ToolExecutor = Callable[[str, dict], Awaitable[dict]]

# A turn should need one or two rounds. The cap exists because, unlike an
# Assistants run (which the server bounded), this loop is ours: a model that
# kept re-calling a failing tool would otherwise spin until the process died.
MAX_TOOL_ROUNDS = 6


class OpenAIResponsesGateway:
    """Thin wrapper over ``client.responses`` / ``client.conversations``."""

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None

    def is_available(self) -> bool:
        """An API key is now the only requirement.

        There is no Assistant object any more, so ``OPENAI_ASSISTANT_ID`` is no
        longer part of this check — a deployment that had a key but no assistant
        id used to fall back to the rule-based path and will now use the model.
        """
        return bool(settings.openai_api_key)

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    @staticmethod
    def _conversation_key(tenant_id: str, our_thread_id: str) -> str:
        # Deliberately NOT the old `openai:thread:` prefix. Those values are
        # Assistants thread ids; handing one to `conversation=` would fail on
        # every turn for the lifetime of the old key's TTL.
        return f"openai:conv:{tenant_id}:{our_thread_id}"

    async def get_or_create_conversation(self, tenant_id: str, our_thread_id: str) -> str:
        """The OpenAI conversation id mapped to our internal thread id.

        Creates and stores one on first use; TTL matches
        ``CONVERSATION_STATE_TTL_HOURS`` so the mapping expires with the rest of
        the conversation state.
        """
        valkey = get_valkey()
        key = self._conversation_key(tenant_id, our_thread_id)
        existing = await valkey.get(key)
        if existing:
            return existing

        conversation = await self.client.conversations.create()
        ttl = settings.conversation_state_ttl_hours * 3600
        await valkey.set(key, conversation.id, ex=ttl)
        logger.info("created openai conversation=%s for threadId=%s", conversation.id, our_thread_id)
        return conversation.id

    async def _forget_conversation(self, tenant_id: str, our_thread_id: str) -> None:
        try:
            await get_valkey().delete(self._conversation_key(tenant_id, our_thread_id))
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning("could not clear the stale conversation mapping: %s", exc)

    async def run_turn(
        self,
        tenant_id: str,
        our_thread_id: str,
        user_message: str,
        execute_tool: ToolExecutor,
        additional_instructions: Optional[str] = None,
    ) -> str:
        """Send a user message, resolve any tool calls, return the reply text."""
        conversation_id = await self.get_or_create_conversation(tenant_id, our_thread_id)
        try:
            return await self._run(conversation_id, user_message, execute_tool,
                                   additional_instructions)
        except Exception as exc:  # noqa: BLE001 - one retry for a vanished conversation
            if not _is_missing_conversation(exc):
                raise
            # The stored id no longer resolves (expired server-side, or the key
            # outlived the object). Start a fresh conversation rather than
            # failing the turn — the citizen loses the model's recollection, not
            # their message, and `original_complaint` is re-seeded into the
            # per-turn instructions for exactly this case.
            logger.warning("openai conversation %s is gone; starting a new one", conversation_id)
            await self._forget_conversation(tenant_id, our_thread_id)
            conversation_id = await self.get_or_create_conversation(tenant_id, our_thread_id)
            return await self._run(conversation_id, user_message, execute_tool,
                                   additional_instructions)

    async def _run(
        self,
        conversation_id: str,
        user_message: str,
        execute_tool: ToolExecutor,
        additional_instructions: Optional[str],
    ) -> str:
        instructions = ASSISTANT_INSTRUCTIONS
        if additional_instructions:
            instructions = f"{instructions}\n\nTHIS TURN:\n{additional_instructions}"

        # First round carries the citizen's message; later rounds carry only the
        # tool results, because the conversation already holds everything else.
        pending_input: list[dict] = [{"role": "user", "content": user_message}]

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.responses.create(
                model=settings.openai_model,
                conversation=conversation_id,
                instructions=instructions,
                tools=responses_tools(),
                input=pending_input,
            )
            status = getattr(response, "status", None)
            if status not in (None, "completed"):
                raise RuntimeError(f"assistant response ended in status={status}")

            calls = [item for item in (response.output or [])
                     if getattr(item, "type", None) == "function_call"]
            if not calls:
                return (getattr(response, "output_text", None) or "").strip()

            pending_input = []
            for call in calls:
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = await execute_tool(call.name, args)
                except Exception as exc:  # noqa: BLE001 - surface to the model, don't crash the turn
                    logger.exception("tool call %s failed", call.name)
                    result = {"error": str(exc)}
                pending_input.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                })

        raise RuntimeError(f"tool-call loop did not settle within {MAX_TOOL_ROUNDS} rounds")


def _is_missing_conversation(exc: Exception) -> bool:
    """Whether this error means "that conversation id no longer exists".

    Matched on the message as well as the status code: the SDK raises a
    `NotFoundError` for a missing conversation, but a 400 naming the
    conversation parameter means the same thing in practice, and both should
    lead to starting a fresh one rather than dropping the citizen's message.
    """
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    if status == 400 and "conversation" in str(exc).lower():
        return True
    return False


# Feature 27: the old name, kept as an alias so nothing outside this module has
# to care that the transport changed. There is no Assistant object any more.
OpenAIAssistantGateway = OpenAIResponsesGateway
