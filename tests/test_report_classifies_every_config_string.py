"""Every string in the config has to be classified before `yazses report` prints it.

The bundle's promise, in the command's own help: *"your settings with paths and
identifiers removed"*, followed by an invitation to attach it to a public issue. What
decided whether a value was an identifier was a key-name regex plus a two-item set of
"free text" keys — and that set was a list of the fields someone had thought of.

`[macros] author` had not been thought of. Its comment in `config.py` reads *"value
substituted for ${author}"*: a person's name, by design. Through the real redactor it
came out as

    "<redacted> Seyedkazemi Ardebili"

which is precisely the failure `_FREE_TEXT_KEYS` exists to prevent, one field over —
the account name matched, the surname did not, and the `<redacted>` marker invites the
reader to believe the field was cleaned. `[filters.disfluency] llm_endpoint` was the
second: `host`, `address` and `port` are all in the key filter, "endpoint" was simply
never spelled, so `http://192.168.1.50:1234/v1` travelled whole.

So this file does not test those two fields (it does that too, at the bottom). It tests
that the classification is **total**: every `str` field reachable from `Config` is
either redacted, replaced as prose, or claimed as a published setting. A new field fails
the build until someone decides which. That is the difference between a guard that
records the last bug and a guard that catches the next one.
"""
from __future__ import annotations

import dataclasses

import pytest

from yazses.config import Config
from yazses.system.report import _FREE_TEXT_KEYS, _REDACT_KEYS, redact_config

#: Config strings whose value comes from a small, published set -- a backend name, a
#: language code, a log level -- and which `report` therefore keeps verbatim.
#:
#: It lives here rather than in `src/` on purpose. `scripts/config_status.py` decides
#: whether a config key is *read by code* by looking for its name in `src/yazses`, and
#: seven of these are on its ledger of keys nothing reads. Naming them there would have
#: made a redaction rule vouch for a feature being wired -- which is the trap
#: `_FREE_TEXT_KEYS` already carries a note about, sprung again by this very change.
#:
#: Nothing at runtime needs the list: falling through *is* keeping the value. What it
#: buys is the assertion below that the classification is total.
_SETTING_KEYS = frozenset({
    "accent", "backend", "chinese_script", "clone_backend", "compute_type", "confirm",
    "delimiter", "device", "embed_model", "engine", "evdev_device", "flavor", "format",
    "language", "lid", "llm_model", "log_level", "lora_base_model", "lsp_editor",
    "mode", "model", "notes_model", "output_format", "pair", "partial_marker",
    "position", "preset", "read_back", "reduced_motion", "scheme", "source", "style",
    "target", "target_guard", "tune_model", "vad_backend", "vad_source", "voice",
    "zones",
})

#: Non-vacuity. An empty traversal would make every assertion below trivially true,
#: which is the shape that has produced green guards over nothing in this repo before.
_MIN_SECTIONS = 100
_MIN_STRING_FIELDS = 50


def _string_fields() -> dict[str, set[str]]:
    """Every ``str``-typed field reachable from `Config`, mapped to its owners.

    Walked from `Config` rather than swept out of the module, so it covers exactly what
    a config file can contain -- and cannot drag in a dataclass that is not config at
    all, which is how an earlier sweep of mine picked up `ConfigProblem.detail`.
    """
    seen: set[type] = set()
    stack: list[type] = [Config]
    found: dict[str, set[str]] = {}
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        for f in dataclasses.fields(cls):
            if dataclasses.is_dataclass(f.type) and isinstance(f.type, type):
                stack.append(f.type)
            elif f.type is str:
                found.setdefault(f.name, set()).add(cls.__name__)
    assert len(seen) >= _MIN_SECTIONS, f"traversal reached only {len(seen)} dataclasses"
    return found


def _classes(name: str) -> list[str]:
    """Which of the three buckets *name* falls into. Should always be exactly one."""
    return [
        label
        for label, hit in (
            ("redacted", bool(_REDACT_KEYS.search(name))),
            ("free-text", name in _FREE_TEXT_KEYS),
            ("setting", name in _SETTING_KEYS),
        )
        if hit
    ]


# --- the classification is total ------------------------------------------------


def test_there_are_string_fields_to_classify():
    assert len(_string_fields()) >= _MIN_STRING_FIELDS


def test_every_config_string_is_classified():
    fields = _string_fields()
    unclassified = sorted(n for n in fields if not _classes(n))
    assert not unclassified, (
        "these config strings would be printed verbatim into a bundle a user is "
        f"invited to attach to a public issue: {unclassified} -- decide for each: "
        "_REDACT_KEYS if the value is an identifier, _FREE_TEXT_KEYS if it is the "
        "user's own prose, _SETTING_KEYS if it comes from a small published set"
    )


def test_no_field_is_classified_twice():
    """Two buckets disagreeing is decided by branch order, which is not a decision."""
    both = {n: _classes(n) for n in _string_fields() if len(_classes(n)) > 1}
    assert not both, f"ambiguous classification: {both}"


def test_nothing_is_claimed_as_a_setting_that_is_not_a_config_field():
    stale = sorted(_SETTING_KEYS - set(_string_fields()))
    assert not stale, f"_SETTING_KEYS names fields that no longer exist: {stale}"


def test_free_text_keys_are_real_config_fields_too():
    stale = sorted(_FREE_TEXT_KEYS - set(_string_fields()))
    assert not stale, f"_FREE_TEXT_KEYS names fields that no longer exist: {stale}"


# --- the two that got through ---------------------------------------------------


def test_the_macro_author_is_not_printed():
    """A name with one matching token is the worst case: it looks handled."""
    out = redact_config({"macros": {"author": "Mohsen Seyedkazemi Ardebili"}})
    value = out["macros"]["author"]
    assert "Seyedkazemi" not in value
    assert "Ardebili" not in value
    assert value == "<redacted> (27 chars)"


def test_the_llm_endpoint_is_not_printed():
    out = redact_config(
        {"filters.disfluency": {"llm_endpoint": "http://192.168.1.50:1234/v1"}}
    )
    assert out["filters.disfluency"]["llm_endpoint"] == "<redacted>"
    assert "192.168" not in str(out)


def test_a_paired_companion_is_not_printed():
    """`[bridge] device_name` is documented as informational, and phones carry names."""
    out = redact_config({"bridge": {"device_name": "Mohsen's iPhone"}})
    assert "iPhone" not in out["bridge"]["device_name"]


@pytest.mark.parametrize("key", sorted(_FREE_TEXT_KEYS))
def test_prose_keeps_its_length_and_loses_its_content(key):
    """Whether a field is *set*, and roughly how big, is the diagnostic half."""
    out = redact_config({"any": {key: "Hildegard von Bingen"}})
    value = out["any"][key]
    assert "Hildegard" not in value
    assert "(20 chars)" in value


def test_an_unset_prose_field_stays_empty_rather_than_becoming_a_marker():
    out = redact_config({"macros": {"author": ""}})
    assert out["macros"]["author"] == ""


# --- and the report is still worth reading --------------------------------------


def test_settings_still_come_through_verbatim():
    """Redaction that destroys the bundle fails as surely as redaction that misses."""
    raw = {
        "stt": {"model": "base.en", "language": "en", "engine": "faster-whisper"},
        "general": {"log_level": "INFO"},
        "injection": {"backend": "auto", "target_guard": "clipboard"},
    }
    assert redact_config(raw) == raw


def test_the_hotkey_is_still_readable():
    """It matches `key` in the name filter and is kept by its published-value set."""
    out = redact_config({"hotkey": {"key": "right_alt", "command_key": "right_ctrl"}})
    assert out["hotkey"] == {"key": "right_alt", "command_key": "right_ctrl"}


def test_an_unrecognised_hotkey_value_still_falls_through_to_redaction():
    out = redact_config({"hotkey": {"key": "/dev/input/by-id/usb-Acme_1234-kbd"}})
    assert out["hotkey"]["key"] == "<redacted>"
