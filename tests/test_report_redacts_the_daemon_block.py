"""The bundle's daemon block went in verbatim, dictated text and all.

`yazses report --help`, in the same breath as inviting the user to attach the file to a
public issue:

    Includes versions, the daemon's state, your settings with paths, identifiers and
    anything you typed yourself removed, and the tail of the metadata-only log. **Your
    dictated text and the learning corpus are never included.**

The config half of `system/report.py` has been hardened four times — a key-name filter, a
free-text set, list/dict summarising, a fixed-value allow-list. The daemon half was one
line with no filter of any kind:

    report["daemon"] = status if status is not None else {"reachable": False}

and `_handle_status` returns `staged.preview`, which `staged/buffer.py` documents as *"the
tail is where the words you just said are"* — the pending buffer verbatim, up to 240
characters. Staged mode exists so a person can review text *before* it is typed, so that
field is populated exactly when someone is mid-sentence, which is exactly when they hit a
bug worth reporting. Measured through the real `collect()`:

    "preview": "My bank card is 4539 1488 0343 6467 and the PIN is 8812. Tell Sarah…"

`summarise_for_issue` states the invariant that was not true: *"Redaction is not repeated
here. Everything in report has already been through `redact_text`/`redact_config` in
`collect`."*

Two facts one line apart, which is this repo's most frequent defect shape: the redactors
existed, the daemon block simply never went through them.
"""
from __future__ import annotations

import ast
import getpass
import json
import pathlib

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.system import report as R

DAEMON_SRC = pathlib.Path(R.__file__).resolve().parents[2] / "yazses" / "core" / "daemon.py"


# --- the classification has to be total ---------------------------------------------
#
# Same discipline as `test_report_classifies_every_config_string.py`: a guard that lists
# what was wrong on the day it was written says nothing about the next field. The key
# names are read out of the daemon's own source so a new status field fails the build
# until someone decides which side it is on.

#: Fields that carry **what the user said**. Must match the set `src/` acts on.
_USER_TEXT = frozenset({"preview"})

#: Fields that describe the machine or the daemon, not the person using it. Strings here
#: still go through `redact_text` — `last_error` is an exception message and those are
#: mostly paths; `input_device` is a microphone name and a Bluetooth microphone is
#: usually named after its owner — they are kept because which mic is in use is the
#: first question any audio bug asks.
_MACHINE_FACTS = frozenset({
    "audio_level", "bursts", "command_mode", "commands_enabled", "confidence_enabled",
    "decode_latency", "enabled", "hotkey", "injection_backend", "input_device",
    "last_error", "last_good_device", "low_confidence_last", "meeting_active",
    "meeting_enabled", "meeting_finalizing", "modality_roles", "model", "notifications",
    "outcomes", "platform", "read_back", "ready", "remote_connected", "silent_streak",
    "silent_streak_threshold", "spoken_commit", "staged", "state", "streaming_enabled",
    "summary", "target_ok", "tts_backend", "uptime_s", "vad_threshold", "version",
    "words",
})


def _status_keys_in_source() -> set[str]:
    """Every literal key in the dicts `status` is assembled from.

    Both producers, not just the outer one: `staged_state()` is where `preview` lives,
    and a guard that scanned only `_handle_status` would have declared the payload fully
    classified while missing the single field this file exists for.
    """
    tree = ast.parse(DAEMON_SRC.read_text(encoding="utf-8"))
    wanted = {"_handle_status", "staged_state"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                found |= {
                    k.value for k in sub.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
    return found


def test_the_source_scan_actually_finds_both_producers():
    """A guard that iterates is green on an empty set. Prove it is not empty."""
    keys = _status_keys_in_source()
    assert len(keys) >= 30, keys
    assert "state" in keys, "the outer status dict was not found"
    assert "preview" in keys, "staged_state() was not found — the leak would be invisible"


def test_every_status_field_is_classified():
    unclassified = _status_keys_in_source() - _USER_TEXT - _MACHINE_FACTS
    assert not unclassified, (
        f"{sorted(unclassified)} is returned by the daemon's status and classified "
        "neither as the user's own words nor as a fact about the machine. Decide: if it "
        "can hold anything the user said, add it to `_STATUS_PROSE_KEYS` in "
        "`system/report.py` so it is replaced by its shape; otherwise add it here."
    )


def test_the_prose_set_here_matches_the_one_src_acts_on():
    """Two sets one module apart is how this bug happened in the first place."""
    assert _USER_TEXT == R._STATUS_PROSE_KEYS


# --- the leak itself, through the real bundle ---------------------------------------


def _daemon():
    cfg = Config()
    cfg.staged.enabled = True
    return Daemon(config=cfg, platform=get_platform())


def _bundle(tmp_path, status) -> dict:
    (tmp_path / "config.toml").write_text('[stt]\nmodel = "base.en"\n', encoding="utf-8")
    (tmp_path / "daemon.log").write_text("2026-08-21 00:00:00,000 INFO yazses: up\n", encoding="utf-8")
    return R.collect(
        config_file=tmp_path / "config.toml",
        log_file=tmp_path / "daemon.log",
        data_dir=tmp_path,
        status=status,
        log_lines=5,
    )


def test_the_staged_buffer_never_reaches_the_bundle(tmp_path):
    """The measured case, end to end through `collect()`."""
    d = _daemon()
    d._staged.stage("My bank card is 4539 1488 0343 6467 and the PIN is 8812.")
    d._staged.stage("Tell Sarah the offer is 92000 euro.")

    blob = json.dumps(_bundle(tmp_path, d._handle_status(None)))

    for secret in ("4539 1488 0343 6467", "PIN is 8812", "Sarah", "92000"):
        assert secret not in blob, f"the bundle carries dictated text: {secret!r}"


def test_what_is_left_still_explains_the_buffer(tmp_path):
    """Redaction that destroys the report defeats its purpose as surely as a leak.

    The module says so itself about `_summarise`: "Configured, and this big" is the
    diagnostic half. Counts distinguish an empty buffer from a stuck one.
    """
    d = _daemon()
    d._staged.stage("one two three")

    staged = _bundle(tmp_path, d._handle_status(None))["daemon"]["staged"]

    assert staged["enabled"] is True
    assert staged["words"] == 3 and staged["bursts"] == 1
    assert staged["preview"].startswith("<redacted>") and "chars" in staged["preview"]
    assert "3 words pending" in staged["summary"], staged["summary"]


# --- the rest of the block, which had no filter either -------------------------------


def test_a_path_in_last_error_is_redacted(tmp_path):
    """Exception messages are mostly paths, and `last_error` is an exception message."""
    d = _daemon()
    d._state.last_error = f"FileNotFoundError: {pathlib.Path.home()}/private/keys.txt"

    daemon = _bundle(tmp_path, d._handle_status(None))["daemon"]

    assert str(pathlib.Path.home()) not in daemon["last_error"], daemon["last_error"]
    assert "~/private/keys.txt" in daemon["last_error"], (
        "the path was blanked rather than redacted — which mic/file failed is the "
        "diagnostic part and must survive"
    )


def test_a_microphone_named_after_its_owner_is_redacted(tmp_path, monkeypatch):
    r"""Bluetooth microphones are named by their owner, and the name is the identifier.

    The account name is patched rather than read. It used to be taken back out of
    `_account_pattern().pattern`, which is the *escaped* spelling: on a Windows machine
    account (`yz-win2$`) that asserted `yz\-win2\$` was redacted -- a string that never
    appears in a report -- so the leak this test exists to catch went unnoticed for as
    long as the test existed. Reading `getpass.getuser()` instead would only move the
    problem: on CI the account is `runner`, which `_GENERIC_ACCOUNTS` deliberately
    leaves alone, so the test would assert nothing there.
    """
    name = "ada-tester"
    monkeypatch.setattr(getpass, "getuser", lambda: name)
    monkeypatch.setattr(R, "_ACCOUNT", R._account_pattern())

    d = _daemon()
    d._state.input_device = f"{name}'s AirPods Pro"

    daemon = _bundle(tmp_path, d._handle_status(None))["daemon"]

    assert name.lower() not in daemon["input_device"].lower(), daemon["input_device"]
    assert "AirPods Pro" in daemon["input_device"], (
        "which microphone is in use is the first question an audio bug asks"
    )


def test_queued_notifications_are_summarised_not_quoted(tmp_path):
    """A toast quotes whatever it is reporting on, so the list goes in by size only."""
    d = _daemon()
    d._queue_notification("YazSes", "Discarded the held command: rm -rf ~/thesis")

    daemon = _bundle(tmp_path, d._handle_status(None))["daemon"]

    assert "thesis" not in json.dumps(daemon), daemon["notifications"]
    assert daemon["notifications"] == "<redacted> (1 item)", daemon["notifications"]


def test_the_facts_that_explain_a_failure_all_survive(tmp_path):
    """The whole point of collecting a report. Numbers and states are untouched."""
    d = _daemon()
    d._state.silent_streak = 3

    daemon = _bundle(tmp_path, d._handle_status(None))["daemon"]

    assert daemon["state"] == "loading"
    assert daemon["model"] == d._config.stt.model
    assert daemon["silent_streak"] == 3
    assert daemon["vad_threshold"] == d._config.accessibility.vad_threshold
    assert isinstance(daemon["uptime_s"], float)
    assert daemon["streaming_enabled"] is d._config.streaming.enabled


def test_nested_dicts_keep_their_numbers(tmp_path):
    """`outcomes` and `decode_latency` are dicts whose numbers are the diagnosis.

    Summarising them wholesale, the way lists are summarised, would be the other way to
    get this wrong — safe and useless.
    """
    d = _daemon()
    d._outcomes.record("typed")
    d._outcomes.record("empty")

    outcomes = _bundle(tmp_path, d._handle_status(None))["daemon"]["outcomes"]

    assert isinstance(outcomes, dict), outcomes
    assert outcomes["total"] == 2, outcomes
    assert outcomes["counts"]["typed"] == 1, outcomes


def test_an_unreachable_daemon_still_reports_that(tmp_path):
    """The `status is None` path must not be disturbed by the new call."""
    assert _bundle(tmp_path, None)["daemon"] == {"reachable": False}


# --- the pure redactor, directly ----------------------------------------------------


def test_redact_status_recurses_to_any_depth():
    out = R.redact_status({"a": {"b": {"preview": "secret words", "n": 4}}})
    assert out["a"]["b"]["n"] == 4
    assert out["a"]["b"]["preview"] == "<redacted> (12 chars)"


def test_redact_status_leaves_none_alone():
    """`last_error` and `tts_backend` are None on a healthy daemon."""
    assert R.redact_status({"last_error": None, "tts_backend": None}) == {
        "last_error": None, "tts_backend": None
    }


# There is deliberately no test that booleans survive the `bool | int | float` branch.
# The final `else` keeps values untouched too, so no single edit to that branch can
# change what a boolean comes out as — a test for it could never go red, and a test
# that cannot fail is decoration. The branch is documentation of intent; the facts that
# actually have to survive are asserted in `test_the_facts_that_explain_a_failure_all_survive`.


def test_an_account_name_ending_in_a_symbol_is_still_redacted(tmp_path, monkeypatch):
    r"""The Windows machine-account shape, which `\b` alone could never match.

    `re.compile(rf"\b{re.escape(name)}\b")` for `yz-win2$` is `\byz\-win2\$\b`, and
    `\b` asserts a *transition*: next to the non-word `$` it demands a word character
    on the other side. In `yz-win2$'s AirPods Pro` the following `'` is not one, so
    the pattern could not match and the account name went into the report in clear.

    Not a corner case on Windows -- a machine account is `<hostname>$` by convention.
    Parameterised over the other non-word endings an account name really has.
    """
    import re

    for name in ("yz-win2$", "mohsen.", "svc-account-"):
        monkeypatch.setattr(getpass, "getuser", lambda n=name: n)
        pattern = R._account_pattern()
        assert pattern is not None, name
        assert pattern.search(f"{name}'s AirPods Pro"), (
            f"{name!r} is not redacted; pattern was {pattern.pattern!r}"
        )
        assert re.compile(
            rf"\b{re.escape(name)}\b", re.IGNORECASE
        ).search(f"{name}'s AirPods Pro") is None, (
            f"{name!r} no longer demonstrates the bug -- this test has stopped testing it"
        )


def test_a_short_name_still_does_not_match_inside_a_longer_word(monkeypatch):
    """Guards the fix in the other direction.

    Relaxing the boundary everywhere would redact `ada` out of `adam`, shredding the
    surrounding log -- the failure mode the module comment already warns about.
    """
    monkeypatch.setattr(getpass, "getuser", lambda: "ada")
    pattern = R._account_pattern()
    assert pattern is not None
    assert pattern.search("adam is here") is None
    assert pattern.search("ada is here") is not None
