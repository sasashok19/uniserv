"""The WhatsApp menu copy, and the guard against the mirror drifting.

``app/conversation/menu_content.py`` and
``services/api-gateway/.../auth/WhatsAppMenuContent.java`` hold the same
defaults in two languages: the gateway owns the admin API, ai-core reads the
stored blob straight from db-writer and must apply identical defaults.

The landing page (Feature 25) has the same arrangement and its handoff notes
name drift as the trap — "defaults are a MIRROR; drift = the page re-wording
itself when the backend comes back". Here the failure would be worse and
quieter: the admin screen would show one welcome message and the citizen would
receive a different one, with nothing anywhere reporting a mismatch. So the
Java file is parsed and compared, rather than trusted.
"""

import re
from pathlib import Path

from app.conversation import menu_content

_JAVA = (Path(__file__).resolve().parents[2]
         / "api-gateway/src/main/java/com/uniserve/auth/WhatsAppMenuContent.java")

# TEXT_DEFAULTS.put("key", "value" + "continued");
_PUT_RE = re.compile(r'TEXT_DEFAULTS\.put\(\s*"([A-Za-z]+)"\s*,\s*(.*?)\);', re.DOTALL)
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unescape(java_literal: str) -> str:
    return (java_literal
            .replace('\\n', '\n').replace('\\t', '\t')
            .replace('\\"', '"').replace("\\\\", "\\"))


def _java_defaults() -> dict[str, str]:
    source = _JAVA.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for key, raw_value in _PUT_RE.findall(source):
        # Java concatenates adjacent literals with '+'; join the pieces.
        out[key] = "".join(_unescape(piece) for piece in _STRING_RE.findall(raw_value))
    return out


def test_the_java_file_is_where_we_think_it_is():
    assert _JAVA.exists(), f"the mirror guard cannot find {_JAVA}"


def test_every_key_exists_on_both_sides():
    java = _java_defaults()
    assert java, "parsed no defaults out of the Java file — the guard has gone blind"
    assert set(java) == set(menu_content.TEXT_DEFAULTS), (
        "the Java and Python menu defaults have different keys; "
        "update both WhatsAppMenuContent.java and app/conversation/menu_content.py"
    )


def test_every_default_string_is_identical():
    java = _java_defaults()
    for key, value in menu_content.TEXT_DEFAULTS.items():
        assert java[key] == value, (
            f"default {key!r} differs between the gateway and ai-core: "
            f"{java[key]!r} vs {value!r} — the admin screen and the citizen "
            f"would disagree with nothing reporting it"
        )


def test_the_session_ttl_bounds_match():
    source = _JAVA.read_text(encoding="utf-8")
    assert f"MAX_SESSION_TTL_HOURS = {menu_content.MAX_SESSION_TTL_HOURS}" in source
    assert f"DEFAULT_SESSION_TTL_HOURS = {menu_content.DEFAULT_SESSION_TTL_HOURS}" in source


# --- resolve/render behaviour ---------------------------------------------

def test_defaults_are_complete_and_none_are_blank():
    resolved = menu_content.resolve(None)
    for key, value in resolved.items():
        if isinstance(value, str) and key != "companyName":
            assert value.strip(), f"{key} must have a default, or it sends an empty message"
    assert resolved["companyName"] == "UniServe"
    assert resolved["enabled"] is True


def test_company_name_cascades_brand_then_product():
    assert menu_content.resolve({"landingPage": {"brandName": "TNEB"}})["companyName"] == "TNEB"
    assert menu_content.resolve({"whatsappMenu": {"companyName": "Care"},
                                 "landingPage": {"brandName": "TNEB"}})["companyName"] == "Care"
    assert menu_content.resolve({})["companyName"] == "UniServe"


def test_an_out_of_range_ttl_that_bypassed_the_gateway_is_clamped_on_read():
    # TenantConfigResource replaces the whole config_json blob, so a
    # whatsappMenu object can reach the database without passing normalise().
    for bad in (0, -3, 72, "soon", None):
        assert menu_content.resolve({"whatsappMenu": {"sessionTtlHours": bad}})["sessionTtlHours"] \
            == menu_content.DEFAULT_SESSION_TTL_HOURS


def test_a_valid_ttl_is_kept():
    assert menu_content.resolve({"whatsappMenu": {"sessionTtlHours": 6}})["sessionTtlHours"] == 6
    assert menu_content.resolve({"whatsappMenu": {"sessionTtlHours": "8"}})["sessionTtlHours"] == 8


def test_enabled_accepts_a_string_from_a_hand_edited_config():
    assert menu_content.resolve({"whatsappMenu": {"enabled": "false"}})["enabled"] is False
    assert menu_content.resolve({"whatsappMenu": {"enabled": True}})["enabled"] is True


def test_render_fills_placeholders_and_survives_unknown_ones():
    content = menu_content.resolve({"whatsappMenu": {
        "companyName": "TNEB", "ticketDetails": "{ticket} {status} {eta} {mystery}"}})

    assert menu_content.render(content, "ticketDetails", ticket="TKT-1", status="Open", eta="soon") \
        == "TKT-1 Open soon {mystery}"


def test_render_substitutes_company_everywhere():
    content = menu_content.resolve({"whatsappMenu": {
        "companyName": "TNEB", "farewell": "Bye from {company}"}})
    assert menu_content.render(content, "farewell") == "Bye from TNEB"
