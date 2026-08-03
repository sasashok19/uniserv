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
                "is_coherent": {
                    "type": "boolean",
                    "description": (
                        "True if complaint_summary is clear enough that a human agent could "
                        "act on it. False if the citizen's own words seem garbled, nonsensical, "
                        "or contain an apparent typo that changes the meaning of an otherwise-"
                        "parseable sentence — brevity or vagueness alone is NOT a reason to say "
                        "false (\"no power\", \"still broken\" are both clearly true)."
                    ),
                },
            },
            "required": ["complaint_summary", "category_hint", "is_coherent"],
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
- If confirm_identity's (or submit_complaint's) result still lists a field as \
simply missing after you've just sent it, that means the value you sent wasn't \
understood — do NOT call the same tool again with the same information. \
Instead, ask the citizen a clear follow-up question for exactly what's still \
listed as missing. (This does not apply to the confirm-a-value case below, \
where calling again after the citizen answers is exactly right.)
- A missing-field entry may instead come back phrased as a QUESTION about a \
value the citizen already gave (e.g. 'a confirmed Email — you sent \
"x@gmaill.com"; did you mean "x@gmail.com"?'). That means the value was \
received but looks mistyped. Ask the citizen that exact question, keeping BOTH \
spellings intact, and wait for their answer. Never substitute the suggested \
spelling yourself, and never re-send the same one silently as though nothing \
happened — only the citizen decides which is right. Once they reply, call \
confirm_identity again: if they gave a different address, pass that address; \
if they simply agreed ("yes", "correct"), just call confirm_identity — the \
system reads their own words and applies the suggestion for you, so you do not \
need to construct the corrected address yourself.
- A message that is only intake answers (a name, an email address, a service \
or customer ID, a pin code — in any combination, with or without labels), or a \
bare "yes"/"no" answering a question you asked, is the citizen answering YOU. \
It is never a new complaint and never a complaint_summary: it belongs to the \
complaint already in progress in this conversation. Record the values via \
confirm_identity and, once nothing is missing, call submit_complaint with the \
ORIGINAL complaint from earlier in this thread as the complaint_summary.
- If intake details arrive and NO complaint has been described in this thread \
yet, do not invent one from them — never submit a name, an email address or an \
ID as the complaint_summary. Thank them and ask what problem they are \
reporting.

Info gathering (after identity is resolved):
- You need a complaint_summary (1-3 sentences on what happened) and a \
category_hint (billing, service, product, technical, or other).
- Ask at most 2 follow-up questions total. The metadata tells you how many \
follow-up questions you have already asked in this thread. Once you've asked 2, \
or once you have a clear summary, call submit_complaint immediately — do not ask \
a 3rd question.
- Keep replies short and courteous. After calling submit_complaint, send a brief \
closing acknowledgement to the citizen (e.g. "Thanks, we're on it") — but do NOT \
state a ticket number or say the complaint is "registered"/"logged"/"created". A \
separate automatic message with the ticket number is sent moments later once the \
ticket is actually created; saying so yourself first produces two confirmation \
messages for one complaint (live-tested: citizens received both "a complaint \
raised TKT-00014" from you and a second, separate "your complaint is registered" \
message).

Unclear or possibly-mistyped complaints:
- Always set is_coherent honestly when calling submit_complaint. If the citizen's \
own words seem garbled, or contain a word that looks like a typo changing what \
they mean (e.g. an odd word where a similar-looking real word would make the \
sentence make sense), set is_coherent=false — the system will reject the call \
and tell you it needs confirmation. When that happens, do NOT just resubmit the \
same summary — ask the citizen directly to confirm what they meant (e.g. "Just \
to confirm, did you mean ... ?"), and only call submit_complaint again once \
they've confirmed or corrected it.
- Vague or brief complaints are NOT the same as incoherent ones — do not use \
is_coherent=false as a substitute for the follow-up-question budget above.
"""
