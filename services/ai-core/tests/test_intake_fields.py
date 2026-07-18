"""Unit tests for configurable per-channel intake fields (Feature 15/16)."""

from app.conversation.intake_fields import (
    build_identity_request_message,
    extract_configured_fields,
    fields_for_channel,
    is_native_field,
    missing_fields,
)


def test_fields_for_channel_falls_back_to_default_when_tenant_has_no_config():
    fields = fields_for_channel(None, "email")
    assert [f["key"] for f in fields] == ["name", "mobile", "serviceId", "pinCode"]
    assert fields[0]["mandatory"] is True


def test_fields_for_channel_default_for_whatsapp_requires_email():
    """The fix for the WhatsApp/email cross-check gap: WhatsApp's default
    config asks for (and requires) email, unlike the old hardcoded behavior
    that resolved a verified phone number without ever asking anything."""
    fields = fields_for_channel(None, "whatsapp")
    email_field = next(f for f in fields if f["key"] == "email")
    assert email_field["mandatory"] is True


def test_fields_for_channel_uses_tenant_override_when_present():
    tenant_config = {"intakeFields": {"email": [{"key": "name", "mandatory": False, "mandatoryIfAnonymous": False}]}}
    fields = fields_for_channel(tenant_config, "email")
    assert fields == [{"key": "name", "mandatory": False, "mandatoryIfAnonymous": False}]


def test_fields_for_channel_drops_unknown_field_keys_defensively():
    tenant_config = {"intakeFields": {"email": [
        {"key": "name", "mandatory": True},
        {"key": "notARealField", "mandatory": True},
    ]}}
    fields = fields_for_channel(tenant_config, "email")
    assert [f["key"] for f in fields] == ["name"]


def test_is_native_field_email_channel_email_and_whatsapp_verified_phone():
    assert is_native_field("email", "email", False) is True
    assert is_native_field("mobile", "whatsapp", True) is True
    assert is_native_field("mobile", "whatsapp", False) is False  # unverified WhatsApp -- can't trust the number
    assert is_native_field("email", "whatsapp", True) is False
    assert is_native_field("mobile", "email", False) is False


FIELDS = [
    {"key": "name", "mandatory": True, "mandatoryIfAnonymous": False},
    {"key": "mobile", "mandatory": False, "mandatoryIfAnonymous": False},
    {"key": "serviceId", "mandatory": False, "mandatoryIfAnonymous": True},
]


def test_extract_configured_fields_native_field_auto_satisfied():
    extracted = extract_configured_fields(
        "hello", "whatsapp", "+919876543210", True,
        [{"key": "mobile", "mandatory": True, "mandatoryIfAnonymous": False}],
    )
    assert extracted["mobile"] == {"value": "+919876543210", "valid": True, "source": "native"}


def test_extract_configured_fields_known_profile_auto_satisfies_identity_fields():
    known = {"name": "Jane Doe", "phone": "9876543210"}
    extracted = extract_configured_fields("My meter is broken", "email", "jane@example.com", False, FIELDS, known=known)
    assert extracted["name"] == {"value": "Jane Doe", "valid": True, "source": "known"}
    assert extracted["mobile"] == {"value": "9876543210", "valid": True, "source": "known"}


def test_extract_configured_fields_known_profile_never_satisfies_complaint_specific_fields():
    """serviceId is per-complaint, not a stored identity attribute -- a
    returning citizen still has to supply it fresh each time."""
    known = {"name": "Jane Doe", "phone": "9876543210"}
    extracted = extract_configured_fields("My meter is broken", "email", "jane@example.com", False, FIELDS, known=known)
    assert extracted["serviceId"]["source"] is None


def test_extract_configured_fields_extracts_from_text_when_not_native_or_known():
    extracted = extract_configured_fields("Name: Jane Doe", "email", "jane@example.com", False, FIELDS)
    assert extracted["name"] == {"value": "Jane Doe", "valid": True, "source": "extracted"}


def test_extract_configured_fields_flags_invalid_but_supplied_value():
    extracted = extract_configured_fields(
        "Mobile: 98765", "email", "jane@example.com", False, FIELDS,
    )
    assert extracted["mobile"]["value"] == "98765"
    assert extracted["mobile"]["valid"] is False
    assert extracted["mobile"]["source"] == "extracted"


def test_missing_fields_flags_absent_mandatory_field():
    extracted = {"name": {"value": None, "valid": True, "source": None},
                 "mobile": {"value": None, "valid": True, "source": None},
                 "serviceId": {"value": None, "valid": True, "source": None}}
    missing = missing_fields(extracted, FIELDS, declared_anonymous=False)
    assert missing == ["Name"]


def test_missing_fields_flags_invalid_supplied_value_even_when_optional():
    extracted = {"name": {"value": "Jane", "valid": True, "source": "extracted"},
                 "mobile": {"value": "98765", "valid": False, "source": "extracted"},
                 "serviceId": {"value": None, "valid": True, "source": None}}
    missing = missing_fields(extracted, FIELDS, declared_anonymous=False)
    assert len(missing) == 1
    assert "Mobile" in missing[0]


def test_missing_fields_mandatory_if_anonymous_only_applies_when_declared_anonymous():
    extracted = {"name": {"value": "Jane", "valid": True, "source": "extracted"},
                 "mobile": {"value": None, "valid": True, "source": None},
                 "serviceId": {"value": None, "valid": True, "source": None}}
    assert missing_fields(extracted, FIELDS, declared_anonymous=False) == []
    assert missing_fields(extracted, FIELDS, declared_anonymous=True) == ["Service/Customer ID"]


def test_missing_fields_skips_native_and_known_regardless_of_mandatory():
    extracted = {"name": {"value": "Jane", "valid": True, "source": "known"},
                 "mobile": {"value": None, "valid": True, "source": None},
                 "serviceId": {"value": None, "valid": True, "source": None}}
    assert missing_fields(extracted, FIELDS, declared_anonymous=False) == []


def test_build_identity_request_message_first_ask_lists_all_askable_fields():
    message = build_identity_request_message(FIELDS, "email", False, [], is_first_ask=True)
    assert "Name" in message
    assert "Mobile" in message
    assert "Service/Customer ID" in message
    assert "14 days" in message


def test_build_identity_request_message_excludes_native_fields():
    fields = [{"key": "mobile", "mandatory": True, "mandatoryIfAnonymous": False},
              {"key": "name", "mandatory": True, "mandatoryIfAnonymous": False}]
    message = build_identity_request_message(fields, "whatsapp", True, [], is_first_ask=True)
    assert "Mobile" not in message
    assert "Name" in message


def test_build_identity_request_message_followup_lists_only_missing():
    message = build_identity_request_message(FIELDS, "email", False, ["Name"], is_first_ask=False)
    assert "still need" in message
    assert message.count("Name") == 1
    assert "Mobile" not in message
