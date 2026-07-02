"""Entity ITN (ADR-v2-045) — pure inverse text normalization."""
from __future__ import annotations

from yazses.itn.normalize import normalize_entities


# ---- emails ----------------------------------------------------------------

def test_email_simple():
    assert normalize_entities("email me at jane at gmail dot com") == "email me at jane@gmail.com"


def test_email_dotted_local_and_domain():
    got = normalize_entities("john dot doe at mail dot example dot com")
    assert got == "john.doe@mail.example.com"


def test_email_embedded_in_sentence():
    got = normalize_entities("my email is john dot doe at gmail dot com thanks")
    assert got == "my email is john.doe@gmail.com thanks"


def test_plain_at_is_not_an_email():
    # "at" without a dotted domain must be left alone
    assert normalize_entities("let's meet at noon") == "let's meet at noon"
    assert normalize_entities("look at the cat") == "look at the cat"


# ---- versions --------------------------------------------------------------

def test_version_number_words():
    assert normalize_entities("upgrade to version two point one") == "upgrade to v2.1"


def test_version_digits():
    assert normalize_entities("version 3 point 14 point 2") == "v3.14.2"


def test_version_single_component():
    assert normalize_entities("release version five") == "release v5"


def test_version_control_left_alone():
    # "version control" is not a version number
    assert normalize_entities("use version control please") == "use version control please"


# ---- edges -----------------------------------------------------------------

def test_empty_and_plain():
    assert normalize_entities("") == ""
    assert normalize_entities("just ordinary words here") == "just ordinary words here"


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "itn" in [f.slug for f in feature_status(Config())]
    assert Config().itn.enabled is False
