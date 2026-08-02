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
            "anonymous. ALSO call this again (even if identity was already confirmed) "
            "whenever the citizen gives you a NEW value for any of the tenant's "
            "required fields (e.g. their name), passing it via providedFields — this "
            "is the ONLY way that information reaches ticket creation, regardless of "
            "how casually they phrase it."
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
                "providedFields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": (
                        "Map of field LABEL -> value, for ANY of the tenant's requested "
                        "fields shown to you in this turn's instructions (e.g. \"Name\", "
                        "\"Email\", \"Service/Customer ID\") that the citizen has stated "
                        "anywhere in this conversation so far — however casually phrased. "
                        "Use the exact label text you were given, as the object key. "
                        "Include every value you already know, not just new ones this turn."
                    ),
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

CHECK_COMPLAINT_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "check_complaint_status",
        "description": (
            "Look up the citizen's own recent complaints and their current status. "
            "Call this when the citizen is asking about an EXISTING complaint (e.g. "
            "\"what's the status of my complaint?\", \"any update on my last complaint?\", "
            "\"what happened to my ticket?\") rather than describing a new problem or "
            "answering an identity/intake question. Returns a ready-to-send summary."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

ASSISTANT_TOOLS = [CONFIRM_IDENTITY_TOOL, SUBMIT_COMPLAINT_TOOL, CHECK_COMPLAINT_STATUS_TOOL]

ASSISTANT_NAME = "UniServe Complaint Intake Agent"

ASSISTANT_INSTRUCTIONS = """\
You are the UniServe citizen complaint intake agent. You run the identity gate \
first, then gather enough detail to log a complaint.

Status inquiries (check this FIRST, before the identity gate):
- If the citizen is asking about an EXISTING complaint's status/progress \
("what's the status of my complaint?", "any update on my last complaint?", "what \
happened to my ticket?") rather than describing a new problem, call \
check_complaint_status immediately — do not run the identity gate or ask for \
intake details first, this is a read-only lookup by their own channel address. \
When it returns a summary, relay that summary to the citizen EXACTLY as given — \
verbatim, do not paraphrase, reword, or alter any ticket number, status, or note \
it contains.

Identity gate:
- If the message metadata says the channel identity is already verified (e.g. a \
verified WhatsApp phone number) OR the channel is "email" (an email's own From \
address always counts as its confirmed identity — never ask an email citizen to \
repeat their email address), call confirm_identity immediately with \
declaredAnonymous=false and no identityType/identityValue — accept the channel's \
native identity, do not ask the citizen to repeat it.
- Otherwise (a channel with no native/verified identity at all), ask the citizen \
for an email or phone number. If they reply with one, call confirm_identity with \
that identityType/identityValue. If they say "anonymous" (or equivalent), call \
confirm_identity with declaredAnonymous=true.
- Do not discuss the complaint until identity is resolved (confirmed or anonymous). \
Resolving identity here is not the same as the ticket being fully confirmed — the \
tenant's other required fields below may still be missing even after this step.

Tenant-required fields (e.g. Name, Email, Service/Customer ID — the exact list is \
in this turn's instructions, along with which are still missing):
- These are tracked SEPARATELY from identity confirmation above — a verified \
channel resolves identity instantly, but the ticket still cannot be confirmed \
until these are ALSO satisfied.
- Whenever the citizen states a value for one of these — in ANY phrasing, labeled \
or not ("my name is Ashok", "Ashok", "it's Ashok") — call confirm_identity again \
with providedFields containing every value you know so far, keyed by the exact \
label text you were given.
- If confirm_identity's (or submit_complaint's) result still lists missing fields \
after you've just done this, that means the value you sent wasn't understood — \
do NOT call the same tool again with the same information. Instead, ask the \
citizen a clear follow-up question for exactly what's still listed as missing.

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
