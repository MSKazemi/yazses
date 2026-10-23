"""The `sendto` row in the feature registry (ADR-031 §1): a real switch, described truly.

ADR-031 names the opt-in capability `sendto` with `[sendto] enabled = false`. The first
build shipped the config key and the code but no registry row, so `yazses features` did
not list it and the only way on was editing `config.toml`. This file pins the row:

* **it is wired and opt-in** -- not in `_UNWIRED`, implemented by the `sendto` package,
  off by default and never seeded on a fresh install, with no optional dependencies;
* **its switch is the ADR's key** -- `features enable sendto` writes `[sendto] enabled =
  true` and nothing else, and the send-to command then stops refusing;
* **what it says is what happens** -- the spoken phrases the card quotes are exactly the
  ones `parse_send_phrase` accepts, the CLI targets it names are the closed table, and it
  says "never sent", "no web fallback", the 14,000-character refusal, and that it has not
  been verified against a real client (ADR-031 §5 names no verified version yet).

The registry-wide guards (examples, use-cases, categories, write targets, wiring
honesty, toggle round trip) cover this row too; these are the facts specific to it.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, load_config
from yazses.sendto import handoff
from yazses.sendto.targets import CLAUDE_MAX_CHARS, parse_send_phrase, target_names
from yazses.system.features import (
    CAT_COMMANDS,
    OPTIONAL,
    _UNWIRED,
    _registry,
    default_enabled_slugs,
    feature_packages,
    find_feature,
)

SLUG = "sendto"


def _row():
    rows = [d for d in _registry() if d.slug == SLUG]
    assert len(rows) == 1, "the sendto row is missing or duplicated"
    return rows[0]


def _feature():
    feature = find_feature(Config(), SLUG)
    assert feature is not None
    return feature


# ---- wired, opt-in, nothing to install --------------------------------------------


def test_it_is_wired_and_lives_in_the_sendto_package() -> None:
    assert SLUG not in _UNWIRED
    assert feature_packages(SLUG) == ("sendto",)
    assert _feature().wired is True


def test_it_is_opt_in_and_never_seeded() -> None:
    assert _row().tier == OPTIONAL
    assert SLUG not in default_enabled_slugs()
    assert _feature().on is False


def test_it_installs_nothing() -> None:
    feature = _feature()
    assert feature.check_modules == ()
    assert feature.pip_packages == ()


def test_it_is_filed_under_commands() -> None:
    assert _feature().category == CAT_COMMANDS


# ---- the switch is the ADR's key -------------------------------------------------------


def test_the_writes_are_exactly_the_sendto_enabled_key() -> None:
    row = _row()
    assert row.on_writes == (("sendto", "enabled", "true", False),)
    assert row.off_writes == (("sendto", "enabled", "false", False),)


def test_the_status_reads_that_key() -> None:
    cfg = Config()
    assert _row().status(cfg) is False
    cfg.sendto.enabled = True
    assert _row().status(cfg) is True


def _platform(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.toml"
    platform = SimpleNamespace(
        paths=SimpleNamespace(config_file=cfg_file, data_dir=tmp_path,
                              ipc_socket=tmp_path / "ipc.sock"),
        lifecycle=SimpleNamespace(is_running=lambda: False),
        ipc_client_factory=lambda _path: None,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return cfg_file


def test_features_enable_sendto_turns_send_to_on(monkeypatch, tmp_path) -> None:
    """The CHANGELOG's instruction, end to end, with the opener faked."""
    cfg_file = _platform(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(handoff, "default_opener", lambda url: bool(calls.append(url)) or True)
    runner = CliRunner()

    before = runner.invoke(cli.app, ["send-to", "codex", "hello"])
    assert before.exit_code == 1 and "Send to is off" in before.output
    assert calls == []

    enabled = runner.invoke(cli.app, ["features", "enable", SLUG])
    assert enabled.exit_code == 0, enabled.output
    assert load_config(cfg_file).sendto.enabled is True

    after = runner.invoke(cli.app, ["send-to", "codex", "hello"])
    assert after.exit_code == 0, after.output
    assert calls == ["codex://new?prompt=hello"]


def test_features_disable_sendto_turns_it_off_again(monkeypatch, tmp_path) -> None:
    cfg_file = _platform(monkeypatch, tmp_path)
    cfg_file.write_text("[sendto]\nenabled = true\n", encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["features", "disable", SLUG])
    assert result.exit_code == 0, result.output
    assert load_config(cfg_file).sendto.enabled is False


def test_the_off_message_names_the_features_switch() -> None:
    assert f"yazses features enable {SLUG}" in handoff.DISABLED_MESSAGE


# ---- what the card says is what happens -------------------------------------------------

_QUOTED_PHRASE = re.compile(r"'(send to [^']+)'", re.IGNORECASE)


def _card_text() -> str:
    feature = _feature()
    return " ".join([feature.why, feature.example, feature.use_case])


def test_every_quoted_phrase_is_one_the_parser_accepts() -> None:
    phrases = _QUOTED_PHRASE.findall(_card_text())
    assert phrases, "the card quotes no spoken phrase"
    for phrase in phrases:
        assert parse_send_phrase(phrase) is not None, (
            f"the sendto card tells users to say {phrase!r}, which the parser ignores"
        )


def test_the_description_quotes_one_phrase_for_every_target() -> None:
    reached = {parse_send_phrase(p) for p in _QUOTED_PHRASE.findall(_feature().why)}
    assert reached == set(target_names())


def test_the_cli_targets_named_are_the_closed_table() -> None:
    why = _feature().why
    assert "yazses send-to claude|claude-code|codex" in why
    assert tuple(target_names()) == ("claude", "claude-code", "codex")


def test_the_example_s_cli_call_uses_a_real_target() -> None:
    match = re.search(r"yazses send-to (\S+)", _feature().example)
    assert match is not None
    assert match.group(1) in target_names()


@pytest.mark.parametrize(
    "promise",
    ["never sent", "press Enter", "no web fallback", f"{CLAUDE_MAX_CHARS:,} characters",
     "never cut", "Not yet verified", "Off by default"],
)
def test_the_description_makes_the_adr_s_promises(promise) -> None:
    assert promise in _feature().why, f"the sendto card no longer says {promise!r}"


def test_the_description_does_not_claim_a_verified_client() -> None:
    """ADR-031 §5: `features info` names verified client versions -- there are none yet."""
    why = _feature().why.lower()
    assert "verified on" not in why
    assert "tested with" not in why
