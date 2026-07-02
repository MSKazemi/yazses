"""Redaction Ink (ADR-v2-046) + Field-Aware Dictation (ADR-v2-047) — pure cores."""
from __future__ import annotations

from yazses.fieldaware.profile import FormatProfile, apply_profile, profile_for_role
from yazses.redaction.scrub import redact


# ---- redaction -------------------------------------------------------------

def test_redact_masks_valid_card_luhn():
    # 4111 1111 1111 1111 is a Luhn-valid test card
    r = redact("my card is 4111 1111 1111 1111 ok")
    assert "[CARD]" in r.text and "CARD" in r.redactions
    assert "4111" not in r.text


def test_redact_ignores_non_luhn_digit_run():
    # a random 16-digit run that fails Luhn must be left alone
    r = redact("the number 1234 5678 9012 3456 is not a card")
    assert "[CARD]" not in r.text


def test_redact_masks_ssn_email_key():
    r = redact("ssn 123-45-6789 email a@b.com key sk-ABCDEFGHIJKLMNOP1234")
    assert "[SSN]" in r.text and "[EMAIL]" in r.text and "[KEY]" in r.text


def test_redact_hold_mode_reports_but_keeps_text():
    r = redact("email a@b.com", mode="hold")
    assert r.text == "email a@b.com"
    assert "EMAIL" in r.redactions


def test_redact_clean_text_untouched():
    r = redact("nothing secret here")
    assert r.text == "nothing secret here" and r.redactions == []


def test_redact_empty():
    assert redact("").text == ""


def test_luhn_rejects_short_input():
    from yazses.redaction.scrub import _luhn
    assert _luhn("1234") is False        # too short to be a card
    assert _luhn("4111111111111111") is True


# ---- field-aware -----------------------------------------------------------

def test_profile_password_refuses():
    assert profile_for_role("passwordtext").refuse is True
    assert apply_profile("hunter2", profile_for_role("password")) is None


def test_profile_number_digits_only():
    p = profile_for_role("spinbutton")
    assert p.digits_only is True
    assert apply_profile("forty 2 dollars", p) == "2"


def test_profile_search_no_trailing_punct():
    p = profile_for_role("searchbox")
    assert p.trailing_punct is False
    assert apply_profile("open files.", p) == "Open files"


def test_profile_default_prose():
    p = profile_for_role("entry")
    assert apply_profile("hello world", p) == "Hello world"


def test_apply_profile_empty_and_refuse():
    assert apply_profile("", FormatProfile()) == ""
    assert apply_profile("x", FormatProfile(refuse=True)) is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "redaction" in slugs and "fieldaware" in slugs
    assert Config().redaction.enabled is False and Config().fieldaware.enabled is False
