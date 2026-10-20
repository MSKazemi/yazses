"""An update must not delete an enabled feature's libraries.

The incident: the tray's "Install update" runs ``uv tool upgrade yazses`` for a
`uv tool` install, and that command rebuilds the tool environment from its receipt,
removing anything the receipt does not list. Parakeet's ``onnx-asr`` had been
installed by an older `features enable` with a bare ``uv pip install``, so the
receipt never knew it, and the upgrade removed it without a word. Dictation then
fell back to a smaller Whisper model.

`features enable` now records its packages in the receipt
(`tests/test_uv_tool_extras_persist.py`), but that only protects installs made
*after* the fix. Every machine that enabled an extra before it — and every install
that hit the fallback path — still lost it on the next update. These tests pin the
upgrade side: when an enabled, working feature's requirement is not on the receipt,
the upgrade is issued as ``uv tool install --upgrade --with … <target>``.

The behaviour of the real uv this relies on was checked once, offline, against uv
0.12.21 with hand-built wheels in a throwaway ``UV_TOOL_DIR`` (not repeatable in
this suite, which never runs uv):

* ``uv pip install`` a package into the tool venv, then ``uv tool upgrade`` —
  uv prints ``- extra-a==1.0``: the drop reproduces, even on a pinned no-op;
* ``uv tool install --upgrade --with 'extra-a>=1.0' --with "<marker pair>" yazses``
  moves 1.0 -> 2.0, records every ``--with`` (markers as a ``marker`` key), and a
  second plain ``uv tool upgrade`` then keeps them all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.system import deps, updater
from yazses.system.dormant import preserved_requirements

ONNX_A = "onnxruntime>=1.27.0; sys_platform != 'darwin' or platform_machine != 'x86_64'"
ONNX_B = "onnxruntime>=1.23.2,<1.24; sys_platform == 'darwin' and platform_machine == 'x86_64'"

# The shape uv 0.12.21 actually wrote in the offline experiment, markers normalised.
_RECEIPT_WITH_MARKERS = """
[tool]
requirements = [
    { name = "yazses", extras = ["desktop"] },
    { name = "kokoro-onnx", specifier = ">=0.5.0" },
    { name = "onnxruntime", marker = "platform_machine != 'x86_64' or sys_platform != 'darwin'", specifier = ">=1.27.0" },
    { name = "onnxruntime", marker = "platform_machine == 'x86_64' and sys_platform == 'darwin'", specifier = ">=1.23.2,<1.24" },
]
"""

_RECEIPT_BARE = """
[tool]
requirements = [{ name = "yazses" }]
"""

_RECEIPT_PINNED = """
[tool]
requirements = [{ name = "yazses", specifier = "==2.36.0" }]
"""


def _receipt(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "uv-receipt.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _withs(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == "--with"]


# ---- the receipt round-trip keeps markers ----------------------------------


def test_a_receipt_marker_survives_rendering():
    """Dropped, it turns an Intel-Mac-only ceiling into one for every platform."""
    entry = {"name": "onnxruntime", "specifier": ">=1.23.2,<1.24",
             "marker": "platform_machine == 'x86_64' and sys_platform == 'darwin'"}
    rendered = deps._render_requirement(entry)
    assert rendered.endswith("; platform_machine == 'x86_64' and sys_platform == 'darwin'")
    assert rendered.startswith("onnxruntime>=1.23.2,<1.24")


def test_enabling_a_second_feature_keeps_both_halves_of_a_marker_pair(monkeypatch, tmp_path):
    """Keyed by name alone, the old merge kept only the second onnxruntime entry,
    and rendered it without its marker — `<1.24` for everyone, beside a `>=1.27`."""
    receipt = _receipt(tmp_path, _RECEIPT_WITH_MARKERS)
    calls: list[list[str]] = []
    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, check: calls.append(cmd))

    assert deps._persist_uv_tool_extras(receipt, ["onnx-asr[cpu,hub]>=0.12"]) is True

    withs = _withs(calls[0])
    onnx = [w for w in withs if deps._requirement_name(w) == "onnxruntime"]
    assert len(onnx) == 2, withs
    assert all(";" in w for w in onnx), f"a marker was dropped: {onnx}"
    assert "onnx-asr[cpu,hub]>=0.12" in withs
    assert calls[0][-1] == "yazses[desktop]", "the target's extra was dropped"


def test_a_feature_replaces_every_recorded_entry_of_a_package_it_names(monkeypatch, tmp_path):
    receipt = _receipt(tmp_path, _RECEIPT_WITH_MARKERS)
    calls: list[list[str]] = []
    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, check: calls.append(cmd))

    deps._persist_uv_tool_extras(receipt, ["kokoro-onnx>=0.5.0", ONNX_A, ONNX_B])

    onnx = [w for w in _withs(calls[0]) if deps._requirement_name(w) == "onnxruntime"]
    assert onnx == [ONNX_A, ONNX_B]


# ---- uv_tool_upgrade_command -------------------------------------------------


def test_no_rewrite_when_this_is_not_a_uv_tool_install(monkeypatch):
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    assert deps.uv_tool_upgrade_command(["onnx-asr[cpu,hub]>=0.12"]) is None


def test_no_rewrite_when_nothing_is_required(tmp_path):
    assert deps.uv_tool_upgrade_command([], receipt=_receipt(tmp_path, _RECEIPT_BARE)) is None


def test_no_rewrite_when_the_receipt_already_lists_every_requirement(tmp_path):
    receipt = _receipt(tmp_path, _RECEIPT_WITH_MARKERS)
    required = ["kokoro-onnx>=0.5.0", ONNX_A, ONNX_B]
    assert deps.uv_tool_upgrade_command(required, receipt=receipt, covered=()) is None


def test_a_requirement_the_targets_extra_supplies_is_not_missing(tmp_path):
    """`yazses[desktop]` keeps PySide6 by itself; a plain upgrade is already right."""
    receipt = _receipt(tmp_path, _RECEIPT_WITH_MARKERS)
    assert deps.uv_tool_upgrade_command(
        ["PySide6>=6.11.1"], receipt=receipt, covered={"pyside6"}
    ) is None


def test_the_desktop_extra_is_read_from_the_installed_metadata(monkeypatch):
    import importlib.metadata as md

    monkeypatch.setattr(
        md, "requires",
        lambda name: ['PySide6>=6.11.1; extra == "desktop"', "numpy>=2", 'mcp; extra == "agent"'],
    )
    assert deps._extra_requirement_names(["desktop"]) == {"pyside6"}
    assert deps._extra_requirement_names([]) == set()


def test_the_incident_shape_is_rewritten_to_keep_the_engine(tmp_path):
    """A receipt that never heard of onnx-asr, and Parakeet enabled and working."""
    receipt = _receipt(tmp_path, _RECEIPT_BARE)

    cmd = deps.uv_tool_upgrade_command(["onnx-asr[cpu,hub]>=0.12"], receipt=receipt, covered=())

    assert cmd is not None
    assert cmd[:4] == ["uv", "tool", "install", "--upgrade"]
    assert _withs(cmd) == ["onnx-asr[cpu,hub]>=0.12"]
    assert cmd[-1] == "yazses"


def test_a_rewrite_keeps_what_the_receipt_already_had_and_the_pin(tmp_path):
    receipt = _receipt(tmp_path, _RECEIPT_PINNED)
    cmd = deps.uv_tool_upgrade_command(["noisereduce>=3.0.3"], receipt=receipt, covered=())
    assert cmd is not None and cmd[-1] == "yazses==2.36.0"

    receipt = _receipt(tmp_path, _RECEIPT_WITH_MARKERS)
    cmd = deps.uv_tool_upgrade_command(["noisereduce>=3.0.3"], receipt=receipt, covered=())
    assert cmd is not None
    withs = _withs(cmd)
    assert "kokoro-onnx>=0.5.0" in withs and "noisereduce>=3.0.3" in withs
    assert sum(deps._requirement_name(w) == "onnxruntime" for w in withs) == 2


def test_an_unreadable_receipt_leaves_the_plain_upgrade(tmp_path):
    bad = _receipt(tmp_path, "not toml [[[")
    assert deps.uv_tool_upgrade_command(["pkg"], receipt=bad, covered=()) is None


# ---- which requirements an upgrade keeps --------------------------------------


class _Feat:
    def __init__(self, slug, *, on=True, wired=True, mods=("m",), pkgs=("p>=1",)):
        self.slug, self.name, self.on, self.wired = slug, slug, on, wired
        self.check_modules, self.pip_packages, self.tier = mods, pkgs, "opt"


def test_only_enabled_working_features_are_preserved():
    feats = [
        _Feat("parakeet", mods=("onnx_asr",), pkgs=("onnx-asr[cpu,hub]>=0.12",)),
        _Feat("off", on=False, mods=("x",), pkgs=("x>=1",)),
        _Feat("unwired", wired=False, mods=("y",), pkgs=("y>=1",)),
        # Enabled but dormant: preserving it would make "Install update" a download
        # of whatever that feature needs, which nobody asked for in that click.
        _Feat("dormant", mods=("gone",), pkgs=("gone>=1",)),
    ]
    kept = preserved_requirements(None, features=feats, missing=lambda m: [x for x in m if x == "gone"])
    assert kept == ("onnx-asr[cpu,hub]>=0.12",)


def test_preserved_requirements_are_deduplicated():
    feats = [_Feat("a", pkgs=("mediapipe>=0.10.35",)), _Feat("b", pkgs=("mediapipe>=0.10.35",))]
    assert preserved_requirements(None, features=feats, missing=lambda m: []) == (
        "mediapipe>=0.10.35",
    )


# ---- the updater uses it, for uv only ----------------------------------------


def _status(method="uv", command=None):
    return updater.UpdateStatus(
        method=method, current="2.43.1", latest="2.43.2", available=True,
        command=command if command is not None else updater.upgrade_command(method),
    )


def test_the_uv_upgrade_is_rewritten_when_an_enabled_feature_is_unrecorded():
    rewritten = ["uv", "tool", "install", "--upgrade", "--with", "onnx-asr", "yazses"]
    out = updater.preserve_enabled_features(
        _status(), required=lambda: ("onnx-asr",), command_for=lambda pkgs: rewritten
    )
    assert out.command == rewritten


def test_the_uv_upgrade_is_unchanged_when_nothing_needs_keeping():
    out = updater.preserve_enabled_features(
        _status(), required=lambda: ("onnx-asr",), command_for=lambda pkgs: None
    )
    assert out.command == ["uv", "tool", "upgrade", "yazses"]


@pytest.mark.parametrize("method", ["pipx", "pip", "snap", "choco", "winget", "scoop"])
def test_every_other_method_is_left_alone(method):
    def must_not_ask():  # pragma: no cover - must not be reached
        raise AssertionError("asked for requirements on a non-uv install")

    status = _status(method)
    assert updater.preserve_enabled_features(status, required=must_not_ask) is status


def test_a_failure_while_resolving_never_breaks_the_update():
    def boom():
        raise RuntimeError("config unreadable")

    status = _status()
    assert updater.preserve_enabled_features(status, required=boom) is status


def test_rewriting_is_idempotent():
    rewritten = ["uv", "tool", "install", "--upgrade", "--with", "x", "yazses"]
    once = updater.preserve_enabled_features(
        _status(), required=lambda: ("x",), command_for=lambda pkgs: rewritten
    )
    twice = updater.preserve_enabled_features(
        once, required=lambda: pytest.fail("re-resolved"), command_for=None
    )
    assert twice.command == rewritten


# ---- "is this a uv tool install?" comes from the receipt, not a path substring --
#
# The first version gated on "/uv/tools/" in sys.prefix. That never matches a custom
# UV_TOOL_DIR, and the Windows default is %APPDATA%\uv\data\tools (`uv help tool
# dir`), so on both the preservation silently did nothing.

_PARAKEET = ("onnx-asr[cpu,hub]>=0.12",)


def _tool_env(monkeypatch, tool_dir: Path) -> None:
    """A real `_uv_tool_receipt()` lookup, with `uv tool dir` answering *tool_dir*."""
    env = tool_dir / "yazses"
    env.mkdir(parents=True)
    (env / "uv-receipt.toml").write_text(_RECEIPT_BARE, encoding="utf-8")
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(
        deps.subprocess, "run",
        lambda cmd, **k: type("R", (), {"stdout": str(tool_dir) + "\n"})(),
    )
    monkeypatch.setattr(deps.sys, "prefix", str(env))
    _enabled_parakeet(monkeypatch)


def _enabled_parakeet(monkeypatch) -> None:
    """Parakeet on and working. Patched below `_enabled_requirements`, not instead of
    it, so whatever gate decides "uv tool install" is the real one under test."""
    import yazses.system.dormant as dormant

    monkeypatch.setattr(dormant, "preserved_requirements", lambda cfg: _PARAKEET)


def _assert_kept(status) -> None:
    assert status.command is not None
    assert status.command[:4] == ["uv", "tool", "install", "--upgrade"], status.command
    assert _withs(status.command) == list(_PARAKEET)


def test_the_default_unix_layout_is_found(monkeypatch, tmp_path):
    _tool_env(monkeypatch, tmp_path / ".local" / "share" / "uv" / "tools")
    _assert_kept(updater.preserve_enabled_features(_status()))


def test_a_custom_uv_tool_dir_is_found(monkeypatch, tmp_path):
    """UV_TOOL_DIR is honoured by `uv tool dir` itself; nothing here parses a path."""
    custom = tmp_path / "opt" / "my-tools"
    monkeypatch.setenv("UV_TOOL_DIR", str(custom))
    _tool_env(monkeypatch, custom)
    assert "/uv/tools/" not in str(custom).replace("\\", "/")
    _assert_kept(updater.preserve_enabled_features(_status()))


def test_a_windows_backslash_prefix_is_not_rejected_by_its_spelling(monkeypatch, tmp_path):
    """The default Windows tool dir. Path normalisation for it cannot run on POSIX,
    so the lookup is stubbed here; the point is that no substring test sits in front."""
    receipt = _receipt(tmp_path, _RECEIPT_BARE)
    monkeypatch.setattr(
        updater.sys, "prefix", r"C:\Users\u\AppData\Roaming\uv\data\tools\yazses"
    )
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: receipt)
    _enabled_parakeet(monkeypatch)
    monkeypatch.setattr(deps, "_extra_requirement_names", lambda extras: set())
    _assert_kept(updater.preserve_enabled_features(_status()))


def test_the_windows_default_tool_dir_is_detected_as_a_uv_install():
    path = r"C:\Users\u\AppData\Roaming\uv\data\tools\yazses\Lib\site-packages\yazses\x.py"
    assert updater.detect_install_method(path, frozen=False) == "uv"


def test_a_plain_venv_reads_no_config(monkeypatch):
    """No receipt: return at once, before the config is ever loaded."""
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: None)
    monkeypatch.setattr(
        updater, "_enabled_requirements", lambda: pytest.fail("read the config")
    )
    status = _status()
    assert updater.preserve_enabled_features(status) is status


def test_run_upgrade_checked_runs_the_rewritten_command(monkeypatch):
    """Both the tray's "Install update" and `yazses update` go through here."""
    rewritten = ["uv", "tool", "install", "--upgrade", "--with", "onnx-asr", "yazses"]
    monkeypatch.setattr(
        updater, "preserve_enabled_features",
        lambda status: updater.UpdateStatus(
            method=status.method, current=status.current, latest=status.latest,
            available=True, command=rewritten,
        ),
    )
    ran: list[list[str] | None] = []
    outcome = updater.run_upgrade_checked(
        _status(),
        upgrade=lambda status: ran.append(status.command) or 0,
        read_version=lambda: "2.43.2",
    )
    assert ran == [rewritten]
    assert outcome.command == rewritten and outcome.ok


def test_yazses_update_prints_the_command_it_will_run(monkeypatch):
    from typer.testing import CliRunner

    from yazses import cli

    rewritten = ["uv", "tool", "install", "--upgrade", "--with", "onnx-asr", "yazses"]
    monkeypatch.setattr(cli, "_installed_version", lambda: "2.43.1")
    monkeypatch.setattr(updater, "check_update", lambda current: _status())
    monkeypatch.setattr(
        updater, "_enabled_requirements", lambda: ("onnx-asr[cpu,hub]>=0.12",)
    )
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: Path("uv-receipt.toml"))
    monkeypatch.setattr(deps, "uv_tool_upgrade_command", lambda pkgs, **k: rewritten)

    result = CliRunner().invoke(cli.app, ["update", "--check"])

    assert result.exit_code == 0, result.output
    assert "Command: " + " ".join(rewritten) in result.output
    assert "Keeping your enabled features" in result.output
