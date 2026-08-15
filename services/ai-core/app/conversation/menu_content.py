"""WhatsApp menu copy (Feature 26) — the Python side of the tenant config.

Mirrors ``services/api-gateway/src/main/java/com/uniserve/auth/WhatsAppMenuContent.java``.
The gateway owns the admin read/write API; ai-core reads the stored blob
straight out of db-writer and therefore has to apply the same defaults, the
same ``companyName`` cascade, and the same TTL clamp.

**The two copies must not drift.** ``tests/test_menu_content.py`` parses the
Java file's ``TEXT_DEFAULTS`` block and asserts it matches :data:`TEXT_DEFAULTS`
here, key for key and string for string — the landing page has the same
mirroring arrangement and its handoff notes record drift as the trap to watch.
Change one, run the tests, and the other is pointed at by name.
"""

from typing import Any, Optional

# Meta only permits a free-form reply within 24h of the citizen's last inbound
# message, so a session may never outlive that window.
MAX_SESSION_TTL_HOURS = 24
DEFAULT_SESSION_TTL_HOURS = 12

# Meta caps an interactive reply-button title at 20 characters.
MAX_BUTTON_LABEL = 20

TEXT_DEFAULTS: dict[str, str] = {
    "companyName": "",
    "welcome": "Welcome to {company}!",
    "menuPrompt": (
        "Please choose an option:\n"
        "Press 1 to know the status, ETA and last update for an existing ticket.\n"
        "Press 2 to register a new ticket.\n"
        "Press 3 to end this chat."
    ),
    "menuIntro": "Please choose an option:",
    "option1Label": "Ticket status",
    "option2Label": "New ticket",
    "option3Label": "End chat",
    "menuHint": "You can press # at any time to return to the main menu.",
    "unknownOption": "Sorry, I didn't catch that. Please reply with 1, 2 or 3.",
    "askTicketId": "Please share your Ticket ID (for example TKT-00042).",
    "ticketNotFound": (
        "I couldn't find a ticket with that ID against this number. "
        "Please check the Ticket ID and send it again."
    ),
    "ticketDetails": (
        "Ticket {ticket}\nComplaint: {complaint}\nStatus: {status}\nETA: {eta}"
        "\nLast updated: {updated}"
    ),
    "inviteNote": (
        "If you have any questions, or would like to add anything to this ticket, "
        "you can type your message here and I'll add it to the ticket."
    ),
    "noteAdded": (
        "Thank you — your note has been added to ticket {ticket} and the team will revert on it."
    ),
    "registerIntro": (
        "Sure, let's register a new ticket. Please reply with the following details:"
    ),
    "ticketCreated": (
        "Your ticket has been registered.\nTicket {ticket}\nComplaint: {complaint}"
        "\nStatus: {status}\nETA: {eta}"
    ),
    "conversationEnd": (
        "We're ending this conversation here. Send us any message whenever you need us "
        "and the main menu will open again."
    ),
    "farewell": "Thanks for reaching out. Have a great time",
    "etaUnknown": "not set yet",
    "complaintUnknown": "not summarised yet",
    "duplicateAsk": (
        'Before I raise a new ticket — we already have ticket {ticket} open for '
        '"{existing}". {question}'
    ),
    "duplicateMerged": (
        "Thanks for confirming. I've added your message to the existing ticket {ticket} "
        "rather than raising a duplicate.\nComplaint: {complaint}\nStatus: {status}\nETA: {eta}"
    ),
}


def defaults() -> dict[str, Any]:
    """A complete, sendable menu — what a tenant that configures nothing gets."""
    out: dict[str, Any] = dict(TEXT_DEFAULTS)
    out["enabled"] = True
    out["useInteractiveButtons"] = True
    out["sessionTtlHours"] = DEFAULT_SESSION_TTL_HOURS
    return out


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clamp_ttl(raw: Any) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_SESSION_TTL_HOURS
    if value < 1 or value > MAX_SESSION_TTL_HOURS:
        return DEFAULT_SESSION_TTL_HOURS
    return value


def _brand_name(tenant_config: Optional[dict]) -> str:
    """The tenant's brand name from the landing-page config, or the product name.

    Read leniently rather than through a full mirror of ``LandingPageContent``:
    only one field of it matters here, and importing the whole landing-page
    default set into ai-core would be a second, larger thing to keep in sync.
    """
    landing = (tenant_config or {}).get("landingPage")
    if isinstance(landing, dict):
        brand = _str(landing.get("brandName"))
        if brand:
            return brand
    return "UniServe"


def resolve(tenant_config: Optional[dict]) -> dict[str, Any]:
    """The tenant's stored menu laid over :func:`defaults`.

    A field left blank reads as its default rather than as an empty string — a
    blank ``welcome`` would otherwise send the citizen an empty WhatsApp message.
    ``companyName`` is the one field with a cascade rather than a literal
    default: it falls back to the landing page's ``brandName`` so a tenant that
    has already branded its public page needn't type its name a second time.
    """
    out = defaults()
    stored = (tenant_config or {}).get("whatsappMenu")
    if not isinstance(stored, dict):
        stored = {}

    for key in TEXT_DEFAULTS:
        value = _str(stored.get(key))
        if value:
            out[key] = value
    if not _str(out.get("companyName")):
        out["companyName"] = _brand_name(tenant_config)

    for flag in ("enabled", "useInteractiveButtons"):
        value = stored.get(flag)
        if value is not None:
            out[flag] = value if isinstance(value, bool) else str(value).lower() == "true"

    # Clamped on READ as well as write, for the same reason the TTL is: a label
    # longer than Meta's cap makes the whole interactive send fail, and the
    # citizen would receive nothing at all rather than a clipped word.
    for option in ("1", "2", "3"):
        key = f"option{option}Label"
        out[key] = str(out.get(key) or "")[:MAX_BUTTON_LABEL]

    # Clamped on READ as well as write: TenantConfigResource replaces the whole
    # config_json blob, so a whatsappMenu object can reach the database without
    # ever passing through the gateway's normalise().
    out["sessionTtlHours"] = _clamp_ttl(stored.get("sessionTtlHours"))
    return out


def render(content: dict[str, Any], key: str, **values: Any) -> str:
    """One menu string with its placeholders filled in.

    Plain ``str.replace`` rather than ``str.format``: the templates are admin-
    editable, and an admin who types a stray ``{`` or a placeholder we don't
    supply would make ``format`` raise — turning a typo in a config field into a
    citizen receiving no reply at all. Unknown placeholders are simply left
    as-is, which is visible and harmless.
    """
    text = str(content.get(key, TEXT_DEFAULTS.get(key, "")))
    text = text.replace("{company}", _str(content.get("companyName")) or "UniServe")
    for name, value in values.items():
        text = text.replace("{" + name + "}", "" if value is None else str(value))
    return text
