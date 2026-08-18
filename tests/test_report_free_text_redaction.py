"""A bug report must not carry the user's own words — including from `config.toml`.

`yazses report` promises *"your dictated text is never in it"*, and the log honours
that by recording word counts rather than words. The **config** section did not.

Found by auditing a real bundle. It was clean, but only because that machine has no
`[stt]` section — and `yazses tune` proposes writing one. Fed a realistic value, the
old redaction returned:

    "<redacted> Seyedkazemi Ardebili, <redacted>.seyedkazemi@gmail.com, KubeIntellect…"

The account name matched and nothing else did. The surname, the email domain, the
employer and two project names travelled into the report **wearing a `<redacted>`
marker**, which is worse than no redaction: it invites the reader to conclude the
field was cleaned. Partial redaction of free text is a false negative with a badge on.

Two rules close it. Known prose keys are replaced wholesale, and **every list and dict
is summarised by size** — those passed through verbatim before, and they are exactly
where user prose lives.
"""

from __future__ import annotations

import getpass

import pytest

from yazses.system.report import _REDACT_KEYS, redact_config


def _value(cfg) -> str:
    """The single redacted value from a one-key config, **as text**.

    `str()` is not cosmetic. These tests assert that a secret does not appear in the
    value, and for a list or dict value `"password" not in value` is *element*
    membership — `"password" not in ["my password is x"]` is True, so the assertion
    could not fail. Sabotaging the redaction is what exposed it: three leak tests
    stayed green while the leak was wide open.
    """
    out = redact_config(cfg)
    section = next(iter(out))
    return str(next(iter(out[section].values())))


# ---- the free-text keys ----------------------------------------------------


def test_the_personal_dictionary_is_replaced_not_filtered():
    """The defect, stated. Every surviving token below is a real leak."""
    value = _value({"stt": {"initial_prompt": (
        "Mohsen Seyedkazemi Ardebili, mohsen.seyedkazemi@gmail.com, "
        "KubeIntellect, NovaFabric, unibo"
    )}})
    for leaked in ("Seyedkazemi", "gmail", "KubeIntellect", "NovaFabric", "unibo"):
        assert leaked not in value, f"{leaked!r} survived into the bug report"


def test_the_users_own_redaction_patterns_do_not_travel():
    """The subtler leak: those regexes describe what the user considers secret.

    Publishing the rule is a smaller disclosure than publishing the data, not none.
    """
    value = _value({"learning": {"redact_patterns": [
        "(?i)my password is \\w+", "ACME Corp", "patient \\d+",
    ]}})
    for leaked in ("password", "ACME", "patient"):
        assert leaked not in value


def test_snippet_templates_do_not_travel():
    """`entries` maps a spoken trigger to the user's own text — an address, a
    signature, a client name. It is a dict, so it used to pass through untouched."""
    value = _value({"snippets": {"entries": {
        "my address": "12 Real Street, Bologna", "sig": "Dr M. Seyedkazemi",
    }}})
    assert "Real Street" not in value and "Seyedkazemi" not in value


def test_per_app_profiles_do_not_travel():
    """A profile value may be an entire custom LLM prompt written by the user."""
    value = _value({"profiles": {"app": {
        "Mail": "write as Dr Seyedkazemi, consultant at ACME",
    }}})
    assert "Seyedkazemi" not in value and "ACME" not in value


def test_a_hand_written_system_prompt_does_not_travel():
    value = _value({"filters.disfluency": {
        "llm_system_prompt": "You are editing notes for patient Jane Doe."
    }})
    assert "Jane Doe" not in value


# ---- what is kept, because a report with nothing in it explains nothing ----


def test_the_size_is_kept_because_it_is_the_diagnostic_half():
    """An empty vocabulary and a 400-term one are a real difference to a reader."""
    assert "(3 items)" in _value({"learning": {"redact_patterns": ["a", "b", "c"]}})
    assert "(2 entries)" in _value({"snippets": {"entries": {"a": "1", "b": "2"}}})
    assert "(1 entry)" in _value({"snippets": {"entries": {"a": "1"}}})
    assert "chars" in _value({"stt": {"initial_prompt": "some terms"}})


def test_an_unset_free_text_key_reads_as_unset_rather_than_as_redacted():
    """"<redacted> (0 chars)" would imply something was there to hide."""
    assert _value({"stt": {"initial_prompt": ""}}) == ""


def test_switches_and_numbers_are_untouched():
    """These are what actually change behaviour, and none identifies anyone."""
    out = redact_config({"audio": {"sample_rate": 16000, "auto_heal_device": True}})
    assert out["audio"] == {"sample_rate": 16000, "auto_heal_device": True}


def test_the_microphone_name_is_kept():
    """Hardware, not identity — and the single most useful line in an audio bug."""
    out = redact_config({"audio": {"device": "Raptor Lake-P/U/H cAVS Digital Microphone"}})
    assert "Raptor Lake" in out["audio"]["device"]


def test_the_key_name_filter_still_applies():
    """Paths, hosts and tokens were already handled; that must not have regressed."""
    out = redact_config({"remote": {"host": "lab-server.internal", "editor_socket": "/tmp/nvim"}})
    assert "lab-server" not in str(out)
    assert "/tmp/nvim" not in str(out)


# ---- the generic half: no list or dict escapes ----------------------------


@pytest.mark.parametrize(
    "value", [["one", "two"], {"k": "v"}, ("a", "b"), [], {}]
)
def test_no_list_or_dict_value_passes_through_verbatim(value):
    """The actual hole: the old `else` branch returned these untouched.

    Enumerating prose keys alone would leave the next collection-valued setting
    leaking on the day it is added, which is how this one arrived.

    The key is named `templates` deliberately. The first version used
    `some_future_key`, which contains the substring **"key"** — so `_REDACT_KEYS`
    matched it and the test passed on the *existing* filter while the hole it was
    written for stayed open. Sabotaging the code is what exposed that.
    """
    assert not _REDACT_KEYS.search("templates"), "the probe name must not self-match"
    out = redact_config({"some_section": {"templates": value}})
    assert isinstance(out["some_section"]["templates"], str)


def test_the_account_name_is_still_scrubbed_from_ordinary_strings():
    """The pre-existing protection, unchanged — it just is no longer the only one."""
    account = getpass.getuser()
    if len(account) < 3:  # pragma: no cover - depends on the running account
        pytest.skip("account name too short to be redacted by design")
    out = redact_config({"general": {"note": f"configured by {account} last week"}})
    assert account not in out["general"]["note"]


def test_a_real_config_round_trips_without_raising():
    """`redact_config` runs on whatever TOML the user has; it must never raise."""
    from yazses.config import Config

    messy = {
        "stt": {"initial_prompt": "x", "model": "base.en"},
        "weird": {"none_value": None, "nested": {"deep": ["a"]}},
        "not_a_section": "a bare string at top level",
    }
    out = redact_config(messy)
    assert out["not_a_section"] == "a bare string at top level"
    assert isinstance(Config(), Config)
