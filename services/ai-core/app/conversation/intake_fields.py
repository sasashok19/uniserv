"""Configurable per-channel identity/intake fields (Feature 15/16).

Replaces the old hardcoded "only Name is mandatory, everything else is
best-effort" gate. Each tenant can now configure, per channel, exactly which
fields to ask for and whether each is mandatory — and, separately, whether
it's still mandatory even when the citizen has explicitly declared
themselves anonymous (e.g. a Service/Customer ID needed to route the
complaint, even from someone who won't give their name).

This is also how the WhatsApp/email cross-check gap gets closed: a verified
WhatsApp phone number used to skip the identity ask entirely (phone alone
was treated as sufficient); now WhatsApp's default config asks for email
too, so the same citizen complaining on both channels resolves to one
identity instead of two.

A field that matches the channel's own NATIVE identity (the email address
for the email channel; the phone number for a *verified* WhatsApp sender) is
always auto-satisfied from the channel identity itself — asking for it back
would be nonsensical.
"""

import re
from typing import Optional

FIELD_CATALOG_ORDER = ["name", "mobile", "email", "serviceId", "pinCode"]

_SEP = r"(?:\s*(?:is\b|[:=\-])\s*)?"


def _digits_only(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def _extract_name(text: str) -> Optional[str]:
    match = re.search(rf"\bname{_SEP}([A-Za-z][A-Za-z .]{{1,60}})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _extract_mobile(text: str) -> Optional[str]:
    match = re.search(rf"\bmobile(?:\s*number)?\s*(?:\([^)]*\))?{_SEP}(\+?[\d\s\-]{{4,15}})", text, re.IGNORECASE)
    return _digits_only(match.group(1)) or None if match else None


def _extract_email(text: str) -> Optional[str]:
    # \b matters here: without it, "email" matches mid-word inside the
    # citizen's OWN address (e.g. "miscemail19@gmail.com" contains "email"
    # as a substring), silently truncating the captured value.
    match = re.search(
        rf"\bemail{_SEP}([A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{{2,24}})",
        text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _extract_service_id(text: str) -> Optional[str]:
    match = re.search(rf"\b(?:service|customer)[\s/]*id{_SEP}([A-Za-z0-9\-]{{2,20}})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _extract_pincode(text: str) -> Optional[str]:
    match = re.search(rf"(?:area\s*)?\bpin\s*code\s*(?:\([^)]*\))?{_SEP}([\d\s\-]{{4,10}})", text, re.IGNORECASE)
    return _digits_only(match.group(1)) or None if match else None


# --- Email validation (Feature 20) -----------------------------------------
# The old validator was `bool(v)`: ANY non-empty string passed, so a mistyped
# consumer domain ("nithya@gmaill.com") sailed through the intake gate, was
# written onto the identity profile, and the citizen never got a chance to
# correct it — every future notification then bounced silently. Two levels of
# check now:
#   1. Syntax — a deliberately permissive, RFC-lite shape check (one @, a
#      sane local part, a dotted domain with a 2+ letter TLD). Anything
#      exotic-but-legal still passes; the goal is catching obvious garbage,
#      not policing the RFC.
#   2. Likely-typo domains — a Damerau-Levenshtein-distance-1 match against
#      the consumer domains citizens actually use (the "mailcheck"
#      heuristic; see `_is_one_typo_away` for why transposition counts). A domain
#      that IS one of them is always accepted; only a domain that is one
#      character away from one, and isn't itself known-good, is flagged, so a
#      legitimate corporate domain can never be rejected by this rule.
# A flagged address is NOT silently dropped: it comes back through
# `missing_fields` as an actionable correction request naming the suggestion,
# which the assistant relays so the citizen can confirm or correct it.

_EMAIL_SYNTAX_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~\-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~\-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)

# Consumer domains common in this deployment's citizen base (India-weighted),
# plus the global majors. Membership here means "always valid"; proximity to a
# member means "probably a typo of it".
KNOWN_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in", "yahoo.co.uk",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "outlook.in", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "gmx.com", "zoho.com", "zohomail.in",
    "protonmail.com", "proton.me", "yandex.com", "rediffmail.com", "rediff.com",
    # Real providers that are themselves one keystroke from one of the above —
    # listed so they're accepted outright instead of being "corrected" at their
    # own users (mail.com/email.com/mailo.com are all genuinely in use).
    "mail.com", "email.com", "mailo.com", "inbox.com", "ymail.com", "rocketmail.com",
}


def _is_one_typo_away(a: str, b: str) -> bool:
    """True when `a` can be turned into `b` by a single insert, delete,
    substitution, or swap of two adjacent characters (Damerau-Levenshtein
    distance 1). Cheap prefix/suffix walk rather than a full DP matrix — this
    runs on every intake turn and only ever needs the "is it 1?" answer.

    The transposition case is not an optional extra here: "gmial.com" and
    "hotmial.com" are two of the most common real-world mistypings, and both
    are distance TWO under plain Levenshtein — a substitutions-only check
    waves them straight through."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    start = 0
    while start < min(la, lb) and a[start] == b[start]:
        start += 1
    end = 0
    while end < min(la, lb) - start and a[la - 1 - end] == b[lb - 1 - end]:
        end += 1
    if (la - start - end) <= 1 and (lb - start - end) <= 1:
        return True
    # Two same-length characters left over on each side, mirrored -> a swap.
    return (la == lb and la - start - end == 2
            and a[start] == b[start + 1] and a[start + 1] == b[start])


# When more than one known domain is a single keystroke away, the tie is
# broken towards the ones citizens overwhelmingly use, so "amail.com" is
# offered "gmail.com" rather than an equally-close but far rarer neighbour.
_DOMAIN_PREFERENCE = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "rediffmail.com")


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def suggest_email_correction(value: Optional[str]) -> Optional[str]:
    """The address the citizen most likely MEANT, when theirs is one keystroke
    away from a well-known consumer domain ("gmaill.com" -> "gmail.com",
    "yahooo.com" -> "yahoo.com", "hotmial.com" -> "hotmail.com"). ``None``
    when the domain is already known-good, or is nothing like any of them
    (i.e. an ordinary corporate/other domain — never second-guessed).

    Whitespace is stripped first: without that, a trailing newline (WhatsApp
    and copy-paste both produce them) makes the domain differ from the real
    one by exactly one character, so the citizen would be asked whether they
    meant an address that looks CHARACTER-FOR-CHARACTER identical to the one
    they sent — a question with no answerable form.

    When more than one known domain is a single keystroke away, the one
    sharing the longest prefix wins, so "ail.com" suggests "mail.com" rather
    than whichever candidate happens to sort first.
    """
    if not value:
        return None
    value = value.strip()
    if "@" not in value:
        return None
    local, _, domain = value.rpartition("@")
    domain = domain.lower()
    if not local or not domain or domain in KNOWN_EMAIL_DOMAINS:
        return None
    matches = [c for c in KNOWN_EMAIL_DOMAINS if _is_one_typo_away(domain, c)]
    if not matches:
        return None

    def rank(candidate: str) -> tuple:
        preference = (len(_DOMAIN_PREFERENCE) - _DOMAIN_PREFERENCE.index(candidate)
                      if candidate in _DOMAIN_PREFERENCE else 0)
        return (_common_prefix_len(domain, candidate), preference, candidate)

    return f"{local}@{max(matches, key=rank)}"


def is_email_syntax_valid(value: Optional[str]) -> bool:
    return bool(value) and bool(_EMAIL_SYNTAX_RE.match(value.strip()))


def validate_email(value: Optional[str]) -> bool:
    """An email is accepted only when it parses AND isn't an obvious typo of a
    common consumer domain — see the module note above."""
    return is_email_syntax_valid(value) and suggest_email_correction(value) is None


def _email_invalid_hint(value: Optional[str]) -> str:
    """What to tell the citizen about an email we refused, phrased as a
    question they can answer — a bare "that's invalid" gives them nothing to
    act on, and a wrong domain is far more often a typo than a real address.

    Both branches spell out the "no" path explicitly (send the address again),
    because the domain list is a heuristic and some citizens really do have an
    address it doesn't recognise — they must always have a way to overrule it
    rather than be asked the same question forever."""
    suggestion = suggest_email_correction(value)
    if suggestion:
        return (f'a confirmed Email — you sent "{value}"; did you mean "{suggestion}"? '
                f'(reply yes to use "{suggestion}", or send the correct address)')
    return f'a valid Email — "{value}" doesn\'t look like a working address; please send it again'


FIELD_CATALOG = {
    "name": {
        "label": "Name",
        "extract": _extract_name,
        "validate": lambda v: bool(v),
    },
    "mobile": {
        "label": "Mobile Number (10 digits)",
        "extract": _extract_mobile,
        "validate": lambda v: len(v) == 10,
    },
    "email": {
        "label": "Email",
        "extract": _extract_email,
        "validate": validate_email,
        "hint": _email_invalid_hint,
    },
    "serviceId": {
        "label": "Service/Customer ID",
        "extract": _extract_service_id,
        "validate": lambda v: bool(v),
    },
    "pinCode": {
        "label": "Area Pin Code (6 digits)",
        "extract": _extract_pincode,
        "validate": lambda v: len(v) == 6,
    },
}

# --- Tenant-defined custom fields (admin "Add field" in Intake Fields UI) ---
# Stored in tenant config under `intakeFieldCatalog` as
# [{key, label, validation: "text"|"digits", digits?: int}]. Custom fields get
# a generic label-anchored extractor and a text/digits validator, so they
# cascade automatically into the rule-based intake form, extraction,
# validation, the assistant's per-turn instructions, and the ticket's
# citizen-provided summary — no per-field code needed anywhere else.

_CUSTOM_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,29}$")


def _make_text_extractor(label: str):
    pattern = re.compile(rf"{re.escape(label)}\s*(?:\([^)]*\))?{_SEP}([^\n]{{1,80}})", re.IGNORECASE)

    def extract(text: str) -> Optional[str]:
        match = pattern.search(text)
        return (match.group(1).strip() or None) if match else None

    return extract


def _make_digits_extractor(label: str):
    pattern = re.compile(rf"{re.escape(label)}\s*(?:\([^)]*\))?{_SEP}([\d\s\-]{{1,30}})", re.IGNORECASE)

    def extract(text: str) -> Optional[str]:
        match = pattern.search(text)
        return (_digits_only(match.group(1)) or None) if match else None

    return extract


def catalog_for_tenant(tenant_config: Optional[dict]) -> dict:
    """Built-in FIELD_CATALOG merged with the tenant's custom fields.

    Defensive: entries with a missing/invalid key or label, or a key that
    collides with a built-in, are skipped — the config endpoint validates on
    write, but a hand-edited config must never crash a conversation turn.
    """
    catalog = dict(FIELD_CATALOG)
    for entry in (tenant_config or {}).get("intakeFieldCatalog") or []:
        if not isinstance(entry, dict):
            continue
        key, label = entry.get("key"), entry.get("label")
        if (not isinstance(key, str) or not _CUSTOM_KEY_RE.match(key) or key in FIELD_CATALOG
                or not isinstance(label, str) or not label.strip()):
            continue
        label = label.strip()
        if entry.get("validation") == "digits":
            digits = entry.get("digits")
            length = digits if isinstance(digits, int) and not isinstance(digits, bool) and 1 <= digits <= 20 else None
            catalog[key] = {
                "label": label + (f" ({length} digits)" if length else ""),
                "extract": _make_digits_extractor(label),
                "validate": (lambda n: lambda v: bool(v) and v.isdigit() and (n is None or len(v) == n))(length),
            }
        else:
            catalog[key] = {
                "label": label,
                "extract": _make_text_extractor(label),
                "validate": lambda v: bool(v),
            }
    return catalog


# Used only when a tenant has no `intakeFields` configured yet. serviceId
# defaults to mandatory-if-anonymous since routing an anonymous complaint
# still needs SOME way to identify what it's about.
DEFAULT_INTAKE_FIELDS = {
    "email": [
        {"key": "name", "mandatory": True, "mandatoryIfAnonymous": False},
        {"key": "mobile", "mandatory": False, "mandatoryIfAnonymous": False},
        {"key": "serviceId", "mandatory": False, "mandatoryIfAnonymous": True},
        {"key": "pinCode", "mandatory": False, "mandatoryIfAnonymous": False},
    ],
    "whatsapp": [
        {"key": "name", "mandatory": True, "mandatoryIfAnonymous": False},
        {"key": "email", "mandatory": True, "mandatoryIfAnonymous": False},
        {"key": "serviceId", "mandatory": False, "mandatoryIfAnonymous": True},
    ],
}


def fields_for_channel(tenant_config: Optional[dict], channel: str, catalog: Optional[dict] = None) -> list[dict]:
    """The configured field list for this channel, falling back to the
    built-in default when the tenant hasn't configured `intakeFields`.
    Pass ``catalog_for_tenant(...)`` as `catalog` to honour tenant-defined
    custom fields; defaults to the built-in catalog."""
    known = catalog if catalog is not None else FIELD_CATALOG
    configured = (tenant_config or {}).get("intakeFields") or {}
    fields = configured.get(channel)
    if fields is None:
        fields = DEFAULT_INTAKE_FIELDS.get(channel, [])
    # Drop any field key that isn't in the catalog (defensive — the config
    # endpoint validates this too, but a stale/hand-edited config shouldn't crash a turn).
    return [f for f in fields if f.get("key") in known]


def is_native_field(key: str, channel: str, channel_identity_verified: bool) -> bool:
    """True when this field is already known from the channel itself and
    should never be asked for."""
    if key == "email" and channel == "email":
        return True
    if key == "mobile" and channel == "whatsapp" and channel_identity_verified:
        return True
    return False


# Catalog keys that are genuine identity attributes, storable on (and
# reusable from) a previously-resolved identity profile. serviceId/pinCode
# are complaint-specific, not identity attributes — a returning citizen
# still needs to supply those fresh for each new complaint.
_IDENTITY_PROFILE_FIELD = {"name": "name", "mobile": "phone", "email": "email"}


def extract_configured_fields(
    raw_text: str, channel: str, channel_identity_value: Optional[str],
    channel_identity_verified: bool, field_configs: list[dict],
    known: Optional[dict] = None, catalog: Optional[dict] = None,
) -> dict:
    """Extract every configured field from the message text.

    Each entry's `source` distinguishes WHY a value is present, since that
    matters to more than one downstream consumer — `missing_fields` treats
    "native"/"known" as already-satisfied (never ask), but only "native" or
    "extracted" values are trustworthy enough to feed back into identity
    resolution (a "known" value is already-on-file, not a new signal — see
    ConversationAgent._resolve_master_id), and only "extracted" values
    belong in the ticket's citizen-provided-details summary (native/known
    values weren't actually written in THIS message).

    A field auto-satisfies (no need to ask, no need to extract) when either:
    - it's native to this channel (the address/verified phone itself), or
    - `known` (an already-resolved identity profile for this citizen) already
      has it on file — reusing exactly what Feature 06's "don't re-ask a
      returning citizen" behavior always did, now applied per-field instead
      of all-or-nothing.
    """
    text = raw_text or ""
    spec_by_key = catalog if catalog is not None else FIELD_CATALOG
    result = {}
    for fc in field_configs:
        key = fc["key"]
        if is_native_field(key, channel, channel_identity_verified):
            result[key] = {"value": channel_identity_value, "valid": True, "source": "native"}
            continue
        profile_field = _IDENTITY_PROFILE_FIELD.get(key)
        if known and profile_field and known.get(profile_field):
            result[key] = {"value": known.get(profile_field), "valid": True, "source": "known"}
            continue
        raw_value = spec_by_key[key]["extract"](text)
        if raw_value is None:
            result[key] = {"value": None, "valid": True, "source": None}
        else:
            result[key] = {
                "value": raw_value, "valid": spec_by_key[key]["validate"](raw_value), "source": "extracted",
            }
    return result


def missing_fields(extracted: dict, field_configs: list[dict], declared_anonymous: bool,
                   catalog: Optional[dict] = None) -> list[str]:
    """Human-readable list of what's missing or invalid, empty when every
    mandatory (or mandatory-if-anonymous) field is present and valid.

    A field spec may carry an optional ``hint(value) -> str`` describing WHY a
    supplied value was refused and what to do about it (Feature 20 — e.g. the
    likely-correct spelling of a mistyped email domain). Without one, the
    generic "doesn't look right" wording is used, exactly as before."""
    spec_by_key = catalog if catalog is not None else FIELD_CATALOG
    missing = []
    for fc in field_configs:
        key = fc["key"]
        entry = extracted.get(key) or {}
        if entry.get("source") in ("native", "known"):
            continue
        required = fc.get("mandatoryIfAnonymous", False) if declared_anonymous else fc.get("mandatory", False)
        value = entry.get("value")
        if value is None:
            if required:
                missing.append(spec_by_key[key]["label"])
        elif not entry.get("valid", True):
            hint = spec_by_key[key].get("hint")
            missing.append(hint(value) if hint
                           else f"a valid {spec_by_key[key]['label']} (the one you sent doesn't look right)")
    return missing


def build_identity_request_message(
    field_configs: list[dict], channel: str, channel_identity_verified: bool,
    missing: list[str], is_first_ask: bool, catalog: Optional[dict] = None,
) -> str:
    """First ask: show every askable (non-native) field as a numbered form,
    mandatory ones marked. Later asks: list only what's still missing."""
    spec_by_key = catalog if catalog is not None else FIELD_CATALOG
    if not is_first_ask:
        bullets = "\n".join(f"- {item}" for item in missing)
        return f"Thanks for the details. We still need:\n{bullets}"

    lines = []
    n = 1
    for fc in field_configs:
        key = fc["key"]
        if is_native_field(key, channel, channel_identity_verified):
            continue
        label = spec_by_key[key]["label"]
        required = fc.get("mandatory", False)
        lines.append(f"{n}. {label}{' (required)' if required else ' (if available)'}:")
        n += 1
    bullets = "\n".join(lines)
    return (
        "Thanks for reaching out. To register your complaint, please reply with "
        "the following details:\n\n" + bullets + "\n\n"
        "If we don't hear back within 14 days, this request will be automatically closed."
    )
