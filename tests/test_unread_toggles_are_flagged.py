"""A switch that nothing reads must say so everywhere a user meets it.

`[gitvoice] enabled` and `[chords] enabled` are written by `yazses features enable`
and read by no code. Both capabilities are command-line tools -- `yazses gitvoice` and
`yazses chords` -- that never consult the switch, and no dictation path runs git or
presses a chord. Three surfaces still told users otherwise:

* `docs/features.md` printed "Activate: `yazses features enable <slug>` then
  `yazses restart`" for both, an instruction that changes nothing;
* `docs/configuration.md` showed both keys as live, because `.enabled` is read by
  nearly every other section and the name-based detector in
  `scripts/config_status.py` cannot tell them apart;
* the chords catalog entry said "Say any shortcut and it's pressed", which no code
  does: `chords/parse.py` is imported by the CLI command alone, and that command
  prints a combo and presses nothing.

The fix keeps two lists -- `AMBIGUOUS_UNREAD` (the config page) and
`features._TOGGLE_NOT_READ` (the feature page) -- and this file holds them equal, so
a third unread switch cannot hide in one, and wiring one of these two forces both to
change in the same commit.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.system.features import (
    _TOGGLE_NOT_READ,
    enable_caveat,
    feature_status,
    find_feature,
    unread_toggle_usage,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def status():
    return _load("config_status_unread", "config_status.py")


@pytest.fixture(scope="module")
def gen():
    return _load("gen_docs_unread", "gen-docs.py")


@pytest.fixture(scope="module")
def features_page(gen) -> str:
    return gen.gen_features()


def _entry(page: str, name: str) -> str:
    """The generated `### <name>` block of docs/features.md."""
    block = page.split(f"### {name}\n", 1)
    assert len(block) == 2, f"no `### {name}` entry on the generated feature page"
    return block[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


# --- the two ledgers agree ----------------------------------------------------


def test_the_registry_and_the_config_ledger_name_the_same_unread_switches(gen, status):
    """Every wired capability whose switch writes only inert keys is in
    `_TOGGLE_NOT_READ`, and nothing else is."""
    inert = status.inert_dotted_keys(Config())
    unread = {
        f.slug for f in feature_status(Config())
        if f.wired and gen.unread_toggle_keys(f, inert)
    }
    assert unread == set(_TOGGLE_NOT_READ), (
        f"config ledger says {sorted(unread)}, features._TOGGLE_NOT_READ says "
        f"{sorted(_TOGGLE_NOT_READ)}"
    )


@pytest.mark.parametrize("cls", ["GitvoiceConfig", "ChordsConfig"])
def test_both_switches_are_in_the_ambiguous_ledger(status, cls):
    assert f"{cls}.enabled" in status.AMBIGUOUS_UNREAD


def test_the_ledger_resolves_to_the_toml_keys(status):
    inert = status.inert_dotted_keys(Config())
    assert {"gitvoice.enabled", "chords.enabled"} <= inert


def test_the_registry_display_lambda_is_the_only_reader():
    """What makes "nothing reads" true. The registry's `lambda c: c.<x>.enabled` only
    displays the switch; any other read means the switch now does something, and the
    ledgers and the catalog text must change with it."""
    for section in ("gitvoice", "chords"):
        pattern = re.compile(
            rf"\.{section}\.enabled\b|getattr\([^)]*[\"']{section}[\"'][^)]*\)\.enabled"
        )
        readers = sorted(
            p.relative_to(SRC).as_posix()
            for p in SRC.rglob("*.py")
            if pattern.search(p.read_text(encoding="utf-8"))
        )
        assert readers == ["system/features.py"], (section, readers)
        registry = (SRC / "system" / "features.py").read_text(encoding="utf-8")
        assert len(re.findall(rf"\.{section}\.enabled\b", registry)) == 1, (
            f"system/features.py reads [{section}] enabled somewhere besides its "
            "status lambda"
        )
        assert re.search(rf"lambda c: c\.{section}\.enabled\s*,", registry), (
            "the shared-config-names exemption no longer matches the registry lambda"
        )


# --- the feature reference ----------------------------------------------------


@pytest.mark.parametrize("slug,command", [
    ("gitvoice", "yazses gitvoice"),
    ("chords", "yazses chords"),
])
def test_the_feature_page_does_not_tell_you_to_enable_an_unread_switch(
    features_page, slug, command,
):
    feat = find_feature(Config(), slug)
    assert feat is not None
    entry = _entry(features_page, feat.name)
    activate = next(ln for ln in entry.splitlines() if ln.startswith("- **Activate:**"))
    assert f"`yazses features enable {slug}` then `yazses restart`" not in activate
    assert "nothing to switch on" in activate
    assert command in activate
    assert f"`[{slug}] enabled`" in activate


def test_a_read_switch_keeps_the_ordinary_activate_line(features_page):
    """The new branch is narrow: a switch something reads is still enabled as before."""
    feat = find_feature(Config(), "compute")
    assert feat is not None and not unread_toggle_usage("compute")
    entry = _entry(features_page, feat.name)
    assert "`yazses features enable compute` then `yazses restart`" in entry


def test_usage_lookup_is_normalised_and_empty_for_ordinary_slugs():
    assert unread_toggle_usage("  GitVoice ") == unread_toggle_usage("gitvoice") != ""
    assert unread_toggle_usage("compute") == ""
    assert unread_toggle_usage("") == ""


# --- the chords catalog entry -------------------------------------------------


def _chords():
    feat = find_feature(Config(), "chords")
    assert feat is not None, "chords left the feature registry"
    return feat


def test_the_chords_entry_names_the_command_and_promises_no_keypress():
    feat = _chords()
    text = " ".join((feat.why, feat.example, feat.use_case)).lower()
    assert "yazses chords" in feat.why
    assert "presses nothing" in feat.why
    assert "nothing reads" in feat.why
    assert "it's pressed" not in text
    assert "command palette opens" not in text
    assert not re.search(r"\bsay 'press", text), "the example tells you to SAY it"
    assert "hands-free" not in text


def test_enabling_chords_says_the_switch_changes_nothing():
    caveat = enable_caveat("chords", Config())
    assert caveat, "`features enable chords` would imply dictation now presses shortcuts"
    assert "nothing reads [chords] enabled" in caveat
    assert "presses" in caveat


def test_the_chords_command_runs_with_the_switch_off(sandbox_paths):
    """The default config has it off, and the command works anyway."""
    from typer.testing import CliRunner

    from yazses.cli import app

    assert Config().chords.enabled is False
    r = CliRunner().invoke(app, ["chords", "press control shift P"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "ctrl+shift+p"
