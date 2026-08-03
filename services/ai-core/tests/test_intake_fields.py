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


def test_extract_configured_fields_email_word_boundary_does_not_match_mid_word():
    """Regression: 'miscemail19@gmail.com' contains "email" as a literal
    substring (m-i-s-c-EMAIL-19...) — without a word-boundary check before
    the label, the old regex matched starting mid-word and captured a
    truncated '19@gmail.com' instead of the real address. Live-testing
    transcript that surfaced this: citizen replied "Ashok, miscemail19@gmail.com"."""
    extracted = extract_configured_fields(
        "Ashok, miscemail19@gmail.com", "whatsapp", "+919876543210", True,
        [{"key": "email", "mandatory": True, "mandatoryIfAnonymous": False}],
    )
    # No literal "email" LABEL word (only the substring inside the address
    # itself) -> correctly not extracted, rather than silently truncated.
    assert extracted["email"]["value"] is None


def test_extract_configured_fields_email_still_matches_with_real_label():
    extracted = extract_configured_fields(
        "My email is miscemail19@gmail.com", "whatsapp", "+919876543210", True,
        [{"key": "email", "mandatory": True, "mandatoryIfAnonymous": False}],
    )
    assert extracted["email"] == {"value": "miscemail19@gmail.com", "valid": True, "source": "extracted"}


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


# ---------------------------------------------------------------------------
# Tenant-defined custom fields (admin "Add field" — cascades everywhere)
# ---------------------------------------------------------------------------

from app.conversation.intake_fields import catalog_for_tenant  # noqa: E402

_CUSTOM_CONFIG = {
    "intakeFieldCatalog": [
        {"key": "consumerNumber", "label": "Consumer Number", "validation": "digits", "digits": 8},
        {"key": "street", "label": "Street", "validation": "text"},
        # Invalid entries must be skipped, never crash:
        {"key": "name", "label": "Collides with builtin"},
        {"key": "bad key!", "label": "Bad key"},
        {"label": "No key at all"},
        "not-a-dict",
    ],
    "intakeFields": {
        "email": [
            {"key": "name", "mandatory": True, "mandatoryIfAnonymous": False},
            {"key": "consumerNumber", "mandatory": True, "mandatoryIfAnonymous": True},
            {"key": "street", "mandatory": False, "mandatoryIfAnonymous": False},
        ],
    },
}


def test_catalog_for_tenant_merges_valid_customs_and_skips_invalid():
    catalog = catalog_for_tenant(_CUSTOM_CONFIG)
    assert "consumerNumber" in catalog and "street" in catalog
    assert catalog["consumerNumber"]["label"] == "Consumer Number (8 digits)"
    # Built-in collision kept the BUILT-IN definition.
    assert catalog["name"]["label"] == "Name"
    assert "bad key!" not in catalog


def test_custom_digits_field_extracts_validates_and_blocks_gate():
    catalog = catalog_for_tenant(_CUSTOM_CONFIG)
    fields = fields_for_channel(_CUSTOM_CONFIG, "email", catalog=catalog)
    assert [f["key"] for f in fields] == ["name", "consumerNumber", "street"]

    # Missing consumer number -> gate blocks with the custom label.
    extracted = extract_configured_fields(
        "Name: Nithin\nMy meter is broken", "email", "n@x.com", False, fields, catalog=catalog)
    missing = missing_fields(extracted, fields, declared_anonymous=False, catalog=catalog)
    assert missing == ["Consumer Number (8 digits)"]

    # Provided + valid (8 digits, label-anchored, punctuation-tolerant).
    extracted = extract_configured_fields(
        "Name: Nithin\nConsumer Number: 1234-5678\nStreet: 12 Elm Street",
        "email", "n@x.com", False, fields, catalog=catalog)
    assert extracted["consumerNumber"] == {"value": "12345678", "valid": True, "source": "extracted"}
    assert extracted["street"]["value"] == "12 Elm Street"
    assert missing_fields(extracted, fields, declared_anonymous=False, catalog=catalog) == []

    # Wrong length -> flagged invalid with the custom label.
    extracted = extract_configured_fields(
        "Name: N\nConsumer Number: 123", "email", "n@x.com", False, fields, catalog=catalog)
    missing = missing_fields(extracted, fields, declared_anonymous=False, catalog=catalog)
    assert any("Consumer Number" in m for m in missing)


# ---------------------------------------------------------------------------
# Feature 20: email validation + consumer-domain typo detection.
#
# Reported bug: "Nithya@gmaill.com" was accepted outright (the validator was
# `bool(v)`), written onto the identity profile, and the citizen was never
# asked about it — so every notification we'd ever send them would bounce
# into nothing.
# ---------------------------------------------------------------------------

from app.conversation.intake_fields import (  # noqa: E402
    is_email_syntax_valid,
    suggest_email_correction,
    validate_email,
)

_EMAIL_FIELD = [{"key": "email", "mandatory": True, "mandatoryIfAnonymous": False}]


def test_suggest_email_correction_catches_the_reported_typo():
    assert suggest_email_correction("Nithya@gmaill.com") == "Nithya@gmail.com"


def test_suggest_email_correction_catches_transposed_letters():
    """"gmial"/"hotmial" are distance TWO under plain Levenshtein — a
    substitution-only check misses both, and they're among the commonest
    real mistypings there are."""
    assert suggest_email_correction("x@gmial.com") == "x@gmail.com"
    assert suggest_email_correction("x@hotmial.com") == "x@hotmail.com"


def test_suggest_email_correction_covers_insertions_deletions_substitutions():
    assert suggest_email_correction("x@yahooo.com") == "x@yahoo.com"
    assert suggest_email_correction("x@gmail.co") == "x@gmail.com"
    assert suggest_email_correction("x@gnail.com") == "x@gmail.com"


def test_suggest_email_correction_never_second_guesses_a_plausible_domain():
    """Only a domain that is one keystroke from a KNOWN consumer domain is
    ever questioned — an ordinary corporate/government address must sail
    through untouched, as must a known domain that merely resembles another
    ("mail.com" is one character from "gmail.com" but is perfectly real)."""
    assert suggest_email_correction("citizen@gmail.com") is None
    assert suggest_email_correction("ceo@uniserve-energy.co.in") is None
    assert suggest_email_correction("officer@tn.gov.in") is None
    assert suggest_email_correction("someone@mail.com") is None
    assert suggest_email_correction(None) is None
    assert suggest_email_correction("no-at-sign") is None


def test_validate_email_rejects_malformed_and_typo_addresses_only():
    assert validate_email("dharshini.s.raj@gmail.com") is True
    assert validate_email("officer@tn.gov.in") is True
    assert validate_email("Nithya@gmaill.com") is False    # typo domain
    assert validate_email("noatsign") is False             # malformed
    assert validate_email("bad@@x.com") is False
    assert validate_email("trailing@dot.") is False
    assert validate_email("") is False
    assert is_email_syntax_valid("Nithya@gmaill.com") is True  # shape is fine; the DOMAIN is the problem


def test_missing_fields_asks_the_citizen_to_confirm_a_likely_typo():
    """A refused email must come back as an actionable question naming both
    spellings — not as a bare "invalid", which tells the citizen nothing and
    tells the assistant nothing to relay."""
    extracted = {"email": {"value": "Nithya@gmaill.com", "valid": False, "source": "extracted"}}
    missing = missing_fields(extracted, _EMAIL_FIELD, declared_anonymous=False)

    assert len(missing) == 1
    assert "Nithya@gmail.com" in missing[0]     # the suggestion
    assert "Nithya@gmaill.com" in missing[0]    # what they actually typed


def test_missing_fields_falls_back_to_generic_wording_for_unguessable_addresses():
    extracted = {"email": {"value": "not-an-email", "valid": False, "source": "extracted"}}
    missing = missing_fields(extracted, _EMAIL_FIELD, declared_anonymous=False)

    assert len(missing) == 1
    assert "not-an-email" in missing[0]
    assert "did you mean" not in missing[0]


def test_valid_email_on_retry_clears_the_gate():
    """The end of the reported transcript: the citizen sends a real address
    and nothing is outstanding any more — which is what lets the ticket move
    to confirmed."""
    extracted = {"email": {"value": "dharshini.s.raj@gmail.com", "valid": True, "source": "extracted"}}
    assert missing_fields(extracted, _EMAIL_FIELD, declared_anonymous=False) == []


def test_email_field_validation_flows_through_the_catalog_extractor():
    extracted = extract_configured_fields(
        "My email is Nithya@gmaill.com", "whatsapp", "+918939014142", True, _EMAIL_FIELD)
    assert extracted["email"]["value"] == "Nithya@gmaill.com"
    assert extracted["email"]["valid"] is False


def test_custom_field_appears_in_identity_request_form():
    catalog = catalog_for_tenant(_CUSTOM_CONFIG)
    fields = fields_for_channel(_CUSTOM_CONFIG, "email", catalog=catalog)
    message = build_identity_request_message(fields, "email", False, [], is_first_ask=True, catalog=catalog)
    assert "Consumer Number (8 digits) (required):" in message
    assert "Street (if available):" in message
