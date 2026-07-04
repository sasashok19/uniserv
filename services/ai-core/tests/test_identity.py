"""Unit tests for identity normalisation and anon-ref generation (Feature 03)."""

import re

from app.identity.anon import generate_anon_ref
from app.identity.normalise import normalise_email, normalise_phone


def test_normalise_phone_e164_from_international():
    assert normalise_phone("+919876543210") == "+919876543210"


def test_normalise_phone_e164_from_national_with_region():
    assert normalise_phone("98765 43210", region="IN") == "+919876543210"


def test_normalise_phone_strips_spaces_and_dashes():
    assert normalise_phone("+91 98765-43210") == "+919876543210"


def test_normalise_email_lowercases_and_strips_plus_alias():
    assert normalise_email("Rajesh+newsletter@Example.com") == "rajesh@example.com"


def test_normalise_email_plain():
    assert normalise_email("rajesh@example.com") == "rajesh@example.com"


def test_generate_anon_ref_format():
    ref = generate_anon_ref("ANON")
    assert re.fullmatch(r"ANON-[A-Z0-9]{4}", ref), ref


def test_generate_anon_ref_uses_prefix():
    assert generate_anon_ref("GHOST").startswith("GHOST-")
