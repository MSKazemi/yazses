"""`yazses features enable` in a pack-capable install (spec *Contracts*, ADR-028 §5).

* the price is shown and the user confirms (``--yes`` skips the question);
* config is written **only after** the pack installed; a "no", ``--no-install``, a
  failed or cancelled install, or an elevated process writes nothing and exits 1;
* every other install (source, MSIX, a channel without packs, a feature with no pack in
  this build) keeps the existing path untouched.

Offline: the pack context and the install are injected; nothing is fetched and pip is
never run.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from tests.packs_fixtures import FakeRuntime, base, build_pack
from yazses.packs.context import PackContext
from yazses.packs.install import InstallResult
from yazses.packs.layout import PackLayout
from yazses.packs.policy import Capability
from yazses.system import deps

runner = CliRunner()


def _out(result) -> str:
    try:
        return result.output + result.stderr
    except ValueError:
        return result.output


@pytest.fixture
def world(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(config_file=config)),
    )
    monkeypatch.setattr(deps, "missing_modules", lambda modules: list(modules))
    pip_calls: list = []
    monkeypatch.setattr(deps, "install_packages",
                        lambda packages, *, echo=print: pip_calls.append(packages) or True)
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")

    pack = build_pack(tmp_path / "src" / "p.yazpack")
    state = types.SimpleNamespace(
        ctx=PackContext(
            runtime=FakeRuntime(),
            layout=PackLayout.under(tmp_path / "data"),
            frozen=True,
            capability=Capability(True),
            index=pack.index(),
            base=base(),
        ),
        installs=[],
        result=InstallResult(True, "Parakeet add-on installed", "The Parakeet add-on is installed."),
        config=config,
        pip_calls=pip_calls,
    )
    monkeypatch.setattr("yazses.packs.context.load_context", lambda **k: state.ctx)

    def fake_install(ctx, entry, *, progress=None, cancel=None):
        state.installs.append(entry.name)
        return state.result

    monkeypatch.setattr("yazses.packs.manage.install", fake_install)
    return state


def _enable(*args: str, input: str | None = None):
    return runner.invoke(cli.app, ["features", "enable", "stt-parakeet", *args], input=input)


def test_yes_installs_the_pack_then_writes_config(world) -> None:
    result = _enable("--yes")
    assert result.exit_code == 0, _out(result)
    assert world.installs == ["parakeet"]
    assert "download" in _out(result) and "on disk" in _out(result), "the price is shown"
    assert world.config.read_text(encoding="utf-8").strip(), "config written after install"
    assert "yazses restart" in _out(result)
    assert world.pip_calls == [], "pip is never run in a frozen install"


def test_the_prompt_is_asked_and_a_no_changes_nothing(world) -> None:
    result = _enable(input="n\n")
    assert result.exit_code == 1
    assert "Download and install the parakeet add-on now?" in _out(result)
    assert world.installs == [] and not world.config.exists()


def test_a_yes_at_the_prompt_installs(world) -> None:
    assert _enable(input="y\n").exit_code == 0
    assert world.installs == ["parakeet"] and world.config.exists()


def test_no_install_writes_nothing_and_says_how(world) -> None:
    result = _enable("--no-install")
    assert result.exit_code == 1
    assert world.installs == [] and not world.config.exists()
    assert "stays off until its add-on is installed" in _out(result)


def test_a_failed_install_writes_no_config(world) -> None:
    world.result = InstallResult(False, "Add-on not installed",
                                 "Couldn't reach github.com … Nothing was changed.",
                                 ["The add-on file is X on the v2.44.0 release: URL"])
    result = _enable("--yes")
    assert result.exit_code == 1
    assert not world.config.exists()
    assert "Couldn't reach github.com" in _out(result)
    assert "v2.44.0 release" in _out(result), "the manual route is named"


def test_an_elevated_process_refuses_before_anything(world) -> None:
    world.ctx = PackContext(
        runtime=FakeRuntime(), layout=world.ctx.layout, frozen=True,
        capability=Capability(False, "YazSes is running as administrator", "elevated"),
        index=world.ctx.index, base=base(),
    )
    result = _enable("--yes")
    assert result.exit_code == 1
    assert "administrator" in _out(result)
    assert world.installs == [] and not world.config.exists()


def test_an_installed_pack_needs_no_download(world, tmp_path) -> None:
    from yazses.packs.install import install_pack
    from yazses.packs.state import empty_state

    pack = build_pack(tmp_path / "again" / "p.yazpack")

    def fetch(index, entry, dest, **k):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / entry.asset).write_bytes(pack.path.read_bytes())
        return dest / entry.asset

    index = world.ctx.index
    assert install_pack(index, index.packs[0], base(), world.ctx.layout, doc=empty_state(),
                        probe=lambda n, s: (True, ""), fetch=fetch,
                        free_bytes=lambda p: 10**12).ok
    result = _enable("--yes")
    assert result.exit_code == 0, _out(result)
    assert world.installs == [], "already installed for this build"
    assert world.config.exists()


@pytest.mark.parametrize(
    "ctx_over",
    [
        {"frozen": False, "capability": Capability(False, "source", "not-frozen")},
        {"capability": Capability(False, "not in the MSIX", "unsupported")},
        {"capability": Capability(False, "choco", "method")},
        {"index": None},
    ],
)
def test_other_installs_keep_the_existing_path(world, ctx_over) -> None:
    fields = dict(runtime=FakeRuntime(), layout=world.ctx.layout, frozen=True,
                  capability=Capability(True), index=world.ctx.index, base=base())
    fields.update(ctx_over)
    world.ctx = PackContext(**fields)
    _enable("--yes")
    assert world.installs == []
    assert world.pip_calls, "the ordinary dependency path ran"


def test_a_feature_with_no_pack_in_this_build_keeps_the_existing_path(world) -> None:
    result = runner.invoke(cli.app, ["features", "enable", "denoise", "--yes"])
    assert world.installs == []
    assert world.pip_calls or result.exit_code == 1


def test_the_hook_in_cli_is_the_only_change_to_the_enable_order() -> None:
    """The pack branch sits after the unwired/experimental refusals and before the
    existing fixed-payload refusal, as the spec orders it."""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    body = src[src.index("def features_enable("):src.index("def _feature_download_note(")]
    assert body.index("if not feat.wired") < body.index("_enable_via_pack(")
    assert body.index("EXPERIMENTAL and not force") < body.index("_enable_via_pack(")
    assert body.index("_enable_via_pack(") < body.index("_feature_deps_blocked(feat)")
