"""Function-tool schemas exposed to the OpenAI Assistant (Feature 06).

These are registered on the Assistant object itself (see
``scripts/create_assistant.py``) so the tool contract lives in git rather than
a dashboard. The conversation agent only needs to know how to *execute* a
tool call by name — see ``ConversationAgent._execute_tool``.
"""

CONFIRM_IDENTITY_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm_identity",
        "description": (
            "Confirm or register the citizen's identity via the identity service. "
            "Call this as soon as identity is known: immediately if the channel "
            "already provides a verified identity (e.g. a verified WhatsApp phone "
            "number — pass declaredAnonymous=false with no identityType/identityValue "
            "to accept the channel's native identity), once the citizen supplies an "
            "email or phone number in the chat, or once they say they want to stay "
            "anonymous."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "declaredAnonymous": {
                    "type": "boolean",
                    "description": "True if the citizen asked to remain anonymous.",
                },
                "identityType": {
                    "type": "string",
                    "enum": ["phone", "email"],
                    "description": "Type of identity the citizen supplied in the chat, if any.",
                },
                "identityValue": {
                    "type": "string",
                    "description": "The phone number or email the citizen supplied in the chat, if any.",
                },
            },
            "required": ["declaredAnonymous"],
        },
    },
}

SUBMIT_COMPLAINT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_complaint",
        "description": (
            "Submit the citizen's complaint for ticket creation. Call this once you "
            "have a clear 1-3 sentence summary and a category, or after 2 follow-up "
            "questions regardless of how much detail you have."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "complaint_summary": {
                    "type": "string",
                    "description": "1-3 sentence summary of what happened.",
                },
                "category_hint": {
                    "type": "string",
                    "enum": ["billing", "service", "product", "technical", "other"],
                },
            },
            "required": ["complaint_summary", "category_hint"],
        },
    },
}

ASSISTANT_TOOLS = [CONFIRM_IDENTITY_TOOL, SUBMIT_COMPLAINT_TOOL]

ASSISTANT_NAME = "UniServe Complaint Intake Agent"

ASSISTANT_INSTRUCTIONS = """\
You are the UniServe citizen complaint intake agent. You run the identity gate \
first, then gather enough detail to log a complaint.

Identity gate:
- If the message metadata says the channel identity is already verified (e.g. a \
verified WhatsApp phone number), call confirm_identity immediately with \
declaredAnonymous=false and no identityType/identityValue — accept the channel's \
native identity, do not ask the citizen to repeat it.
- Otherwise, if identity_status is not yet confirmed, ask the citizen for an email \
or phone number. If they reply with one, call confirm_identity with that \
identityType/identityValue. If they say "anonymous" (or equivalent), call \
confirm_identity with declaredAnonymous=true.
- Do not discuss the complaint until identity is resolved (confirmed or anonymous).

Info gathering (after identity is resolved):
- You need a complaint_summary (1-3 sentences on what happened) and a \
category_hint (billing, service, product, technical, or other).
- Ask at most 2 follow-up questions total. The metadata tells you how many \
follow-up questions you have already asked in this thread. Once you've asked 2, \
or once you have a clear summary, call submit_complaint immediately — do not ask \
a 3rd question.
- Keep replies short and courteous. After calling submit_complaint, send a brief \
closing acknowledgement to the citizen.
"""
