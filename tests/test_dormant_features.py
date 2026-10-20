"""An enabled feature whose libraries are missing is named, with the command that fixes it.

Routes to "on, but nothing can run it" that never pass through `features enable`'s
install: a hand-edited `config.toml`, `--no-install`, a failed install whose key
stood (by design, see `settingsui/deps.py`), and an upgrade that rebuilt the
environment without the extra. Before `system/dormant.py` each ended with one
factory log line — several naming `uv sync --extra …`, which does nothing outside
a source checkout — and `yazses features` still drew the row as a healthy `● ON`.

These pin the shared finding and each surface that reports it: the daemon at
start, `yazses doctor`, and the `yazses features` listing. Nothing here installs
anything or needs an optional dependency.
"""

from __future__ import annotations

import ast
import inspect
import threading
import types
from pathlib import Path

from typer.testing import CliRunner

from yazses.config import Config
from yazses.system import dormant
from yazses.system.features import _FEATURE_DEPS, EXPERIMENTAL, feature_status

ROOT = Path(__file__).resolve().parents[1]


def _all_missing(modules):
    return list(modules)


def _none_missing(_modules):
    return []


def _feat(slug, *, on=True, wired=True, tier="opt", mods=("m",), pkgs=("p>=1",)):
    return types.SimpleNamespace(
        slug=slug, name=slug.title(), on=on, wired=wired, tier=tier,
        check_modules=mods, pip_packages=pkgs,
    )


# ---- the finding itself ------------------------------------------------------


def test_every_registered_dependency_feature_can_be_found_dormant():
    """Derived from the registry: switch each one on, take its libraries away."""
    feats = [
        dataclass_on(f) for f in feature_status(Config())
        if f.slug in _FEATURE_DEPS and f.wired
    ]
    assert feats, "no feature with optional deps is wired; the check is blind"
    found = dormant.dormant_features(
        None, features=feats, missing=_all_missing,
        blocked=lambda pkgs: None, graphical=lambda: True,
    )
    assert {d.slug for d in found} == {f.slug for f in feats}


def dataclass_on(feat):
    import dataclasses

    return dataclasses.replace(feat, on=True)


def test_a_clean_install_reports_nothing():
    feats = [_feat("a"), _feat("b", on=False)]
    assert dormant.dormant_features(
        None, features=feats, missing=_none_missing, blocked=lambda p: None,
        graphical=lambda: True,
    ) == []


def test_off_and_unwired_features_are_not_findings():
    feats = [_feat("off", on=False), _feat("unwired", wired=False), _feat("plain", pkgs=())]
    assert dormant.dormant_features(
        None, features=feats, missing=_all_missing, blocked=lambda p: None,
        graphical=lambda: True,
    ) == []


def test_the_remedy_is_the_enable_command_with_force_when_it_is_needed():
    feats = [_feat("stt-parakeet"), _feat("gaze", tier=EXPERIMENTAL)]
    found = dormant.dormant_by_slug(dormant.dormant_features(
        None, features=feats, missing=_all_missing, blocked=lambda p: None,
        graphical=lambda: True,
    ))
    assert found["stt-parakeet"].remedy.endswith("yazses features enable stt-parakeet")
    # Without --force the printed command would itself refuse: the dead end again.
    assert found["gaze"].remedy.endswith("yazses features enable gaze --force")
    assert "uv sync" not in found["gaze"].describe()


def test_an_environment_that_can_never_install_says_why_instead():
    feats = [_feat("gaze", tier=EXPERIMENTAL)]
    (only,) = dormant.dormant_features(
        None, features=feats, missing=_all_missing,
        blocked=lambda pkgs: "this is the macOS app — pipx install yazses",
        graphical=lambda: True,
    )
    assert "pipx install yazses" in only.remedy
    assert "features enable" not in only.remedy


def test_a_desktop_feature_on_a_headless_box_is_not_a_finding():
    """The tray ships on by default; a server must not be told to fetch 648 MB of Qt."""
    feats = [_feat(slug, mods=("PySide6",)) for slug in sorted(dormant.DESKTOP_ONLY)]
    headless = dormant.dormant_features(
        None, features=feats, missing=_all_missing, blocked=lambda p: None,
        graphical=lambda: False,
    )
    desktop = dormant.dormant_features(
        None, features=feats, missing=_all_missing, blocked=lambda p: None,
        graphical=lambda: True,
    )
    assert headless == []
    assert {d.slug for d in desktop} == set(dormant.DESKTOP_ONLY)


def test_the_desktop_only_slugs_are_real_dependency_features():
    assert dormant.DESKTOP_ONLY <= set(_FEATURE_DEPS)


def test_a_hand_edited_config_is_found_through_the_real_registry(tmp_path):
    """The owner's case: `[denoise] enabled = true` typed by hand, noisereduce absent."""
    from yazses.config import load_config

    path = tmp_path / "config.toml"
    path.write_text("[denoise]\nenabled = true\n", encoding="utf-8")
    cfg = load_config(path)
    found = dormant.dormant_by_slug(dormant.dormant_features(
        cfg, missing=lambda mods: [m for m in mods if m == "noisereduce"],
        blocked=lambda p: None, graphical=lambda: False,
    ))
    assert "denoise" in found
    assert found["denoise"].missing == ("noisereduce",)
    assert "yazses features enable denoise" in found["denoise"].describe()


# ---- the daemon announces it at start ---------------------------------------


def _daemon_stub(cfg):
    return types.SimpleNamespace(
        _config=cfg, _lock=threading.Lock(), _diagnosed_at={},
        _persist_shown_notices=lambda: None,
    )


def test_the_daemon_logs_and_notifies_each_dormant_feature_once(monkeypatch, caplog):
    from yazses.core.daemon import Daemon
    from yazses.system import notify as notify_mod

    item = dormant.DormantFeature(
        slug="denoise", name="Denoise", missing=("noisereduce",),
        packages=("noisereduce>=3.0.3",), remedy="Install them with:  yazses features enable denoise",
    )
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: [item])
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, body, **k: toasts.append((title, body)))

    stub = _daemon_stub(Config())
    with caplog.at_level("WARNING"):
        Daemon._announce_dormant_features(stub)
        Daemon._announce_dormant_features(stub)  # a crash-loop restart

    assert len(toasts) == 1, "the repeat-silence record must stop a second toast"
    assert "yazses features enable denoise" in toasts[0][1]
    assert sum("yazses features enable denoise" in r.message for r in caplog.records) == 2


def test_the_daemon_survives_a_probe_that_raises(monkeypatch):
    from yazses.core.daemon import Daemon

    def boom(cfg):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(dormant, "dormant_features", boom)
    Daemon._announce_dormant_features(_daemon_stub(Config()))  # must not raise


def test_daemon_run_calls_the_announcement():
    """A method nobody calls is the denoise bug again: correct, and never reached."""
    from yazses.core.daemon import Daemon

    tree = ast.parse(inspect.getsource(Daemon.run).lstrip())
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_announce_dormant_features" in called


# ---- yazses doctor ------------------------------------------------------------


def test_doctor_prints_one_row_per_dormant_feature_with_its_remedy():
    from yazses.system.doctor import _dormant_feature_checks

    items = [
        dormant.DormantFeature("stt-parakeet", "Parakeet", ("onnx_asr",), ("onnx-asr",),
                               "Install them with:  yazses features enable stt-parakeet"),
        dormant.DormantFeature("prosody", "Prosody", ("parselmouth",), ("praat-parselmouth",),
                               "Install them with:  yazses features enable prosody"),
    ]
    rows = _dormant_feature_checks(Config(), dormant=items)
    assert len(rows) == 1, "prosody has its own, more precise row"
    name, status, detail = rows[0]
    assert "stt-parakeet" in name and status == "WARN"
    assert "yazses features enable stt-parakeet" in detail


def test_doctor_is_silent_on_a_clean_install():
    from yazses.system.doctor import _dormant_feature_checks

    assert _dormant_feature_checks(Config(), dormant=[]) == []


def test_doctor_no_longer_tells_end_users_to_run_uv_sync():
    """The rows this replaced said `uv sync --extra tts` and probed `l2cs` for gaze."""
    src = (ROOT / "src" / "yazses" / "system" / "doctor.py").read_text(encoding="utf-8")
    assert '"uv sync --extra' not in src
    assert '"l2cs"' not in src


# ---- yazses features ------------------------------------------------------------


def test_the_listing_marks_a_dormant_feature_and_names_the_fix(monkeypatch):
    from yazses import cli

    item = dormant.DormantFeature(
        "denoise", "Noise suppression", ("noisereduce",), ("noisereduce>=3.0.3",),
        "Install them with:  yazses features enable denoise",
    )
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg, features: [item])
    result = CliRunner().invoke(cli.app, ["features"], env={"COLUMNS": "220"})

    assert result.exit_code == 0, result.output
    row = next(line for line in result.output.splitlines() if " denoise " in line)
    assert "◐ ON" in row, row
    assert "denoise: Install them with:  yazses features enable denoise" in result.output


def test_the_listing_has_no_dormant_legend_when_nothing_is_dormant(monkeypatch):
    from yazses import cli

    monkeypatch.setattr(dormant, "dormant_features", lambda cfg, features: [])
    result = CliRunner().invoke(cli.app, ["features"], env={"COLUMNS": "220"})
    assert result.exit_code == 0
    assert "◐" not in result.output
