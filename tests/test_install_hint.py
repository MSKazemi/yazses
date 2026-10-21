"""`system/remedy.install_hint` — the install command a user-facing message gives.

Eight messages hand-wrote `uv sync --extra <x>`, which does nothing outside a source
checkout. The helper derives the remedy instead: the point-of-need
`yazses features install <slug>` when the named capability is on and the registry
agrees it ships the extra's libraries, the environment's refusal where nothing can
be installed, and otherwise the command that installs into *this* environment and
lasts there. Every probe is injected, so no test depends on how this checkout is
installed or touches the network.
"""
from __future__ import annotations

import sys

import pytest

from yazses.system import install_txn, remedy
from yazses.system.features import EXPERIMENTAL, OPTIONAL, Feature

_PYSIDE = "PySide6>=6.11.1"
_REQUIRES = [
    "faster-whisper>=1.2",                       # a base requirement: in no extra
    f'{_PYSIDE}; extra == "desktop"',
    'speechbrain>=1.1; extra == "voiceprint"',
    'llama-cpp-python>=0.3.33; extra == "notes"',
    "onnxruntime>=1.27.0; sys_platform == 'nonexistent-os' and extra == \"tts\"",
    'kokoro-onnx>=0.5.0; extra == "tts"',
]


def _row(slug="tray", *, on=True, tier=OPTIONAL, packages=(_PYSIDE,), modules=("PySide6",)):
    return Feature(name=slug.title(), on=on, slug=slug, tier=tier,
                   on_writes=((slug, "enabled", "true", False),),
                   pip_packages=packages, check_modules=modules)


def _hint(extra, **kw):
    kw.setdefault("requires", _REQUIRES)
    kw.setdefault("installed", lambda name: False)
    kw.setdefault("missing", lambda mods: list(mods))
    kw.setdefault("blocked", lambda pkgs: None)
    kw.setdefault("graphical", lambda: True)
    kw.setdefault("channel", install_txn.VENV)
    return remedy.install_hint(extra, **kw)


# ---- the extra's requirements come from the installed metadata ----------------

def test_extra_requirements_are_read_from_metadata_with_markers_evaluated():
    assert remedy.extra_requirements("desktop", _REQUIRES) == (_PYSIDE,)
    # The platform-gated onnxruntime does not hold here and is dropped; the marker
    # of the one that does is removed, because the hint is for this machine.
    assert remedy.extra_requirements("tts", _REQUIRES) == ("kokoro-onnx>=0.5.0",)
    assert remedy.extra_requirements("nope", _REQUIRES) == ()


def test_the_real_metadata_declares_the_extras_the_call_sites_name():
    for extra in ("desktop", "voiceprint", "voiceprint-resemblyzer", "notes", "ble",
                  "emg-band"):
        assert remedy.extra_requirements(extra), f"no requirements read for {extra!r}"


# ---- a named capability that is on ---------------------------------------------

def test_an_enabled_dormant_capability_gets_the_point_of_need_command():
    out = _hint("desktop", feature="tray", features=[_row()])
    assert out == "Install them with:  yazses features install tray"


def test_an_experimental_capability_needs_no_force_to_install():
    """`features install` writes no config, so it has no experimental gate to pass."""
    row = _row("cocktail", tier=EXPERIMENTAL, packages=("speechbrain>=1.1",),
               modules=("speechbrain",))
    out = _hint("voiceprint", feature="cocktail", features=[row])
    assert out == "Install them with:  yazses features install cocktail"


def test_an_environment_that_can_never_install_gets_its_reason_not_a_command():
    reason = "this is the snap, whose payload is fixed"
    out = _hint("desktop", feature="tray", features=[_row()], blocked=lambda p: reason)
    assert out == reason
    assert "yazses features" not in out


# ---- when the capability is not the answer ------------------------------------

def test_a_switched_off_capability_is_never_turned_on_by_a_hint():
    """Enabling the overlay to get PySide6 would also make it steal focus on Wayland."""
    out = _hint("desktop", feature="overlay", features=[_row("overlay", on=False)])
    assert "features enable" not in out and "features install" not in out
    assert _PYSIDE in out


def test_a_capability_whose_libraries_are_not_the_extras_is_ignored():
    """The Cocktail Filter ships speechbrain; the resemblyzer backend needs another."""
    row = _row("cocktail", tier=EXPERIMENTAL, packages=("speechbrain>=1.1",),
               modules=("speechbrain",))
    out = _hint("voiceprint-resemblyzer", feature="cocktail", features=[row],
                requires=['resemblyzer>=0.1.4; extra == "voiceprint-resemblyzer"'])
    assert "cocktail" not in out
    assert "resemblyzer>=0.1.4" in out


def test_no_capability_named_installs_the_extra_into_this_environment(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    out = _hint("notes")
    assert out == (
        f'Install them with:  {sys.executable} -m pip install "llama-cpp-python>=0.3.33"'
    )


def test_a_windows_interpreter_path_without_spaces_is_left_bare(monkeypatch):
    # PowerShell will not run a quoted first word followed by arguments, so a quoted
    # `"D:\...\python.exe" -m pip ...` is a parse error there (Windows CI caught it).
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(sys, "executable", r"D:\a\yazses\.venv\Scripts\python.exe")
    assert _hint("notes") == (
        r'Install them with:  D:\a\yazses\.venv\Scripts\python.exe -m pip install '
        '"llama-cpp-python>=0.3.33"'
    )


def test_an_interpreter_path_with_a_space_is_still_quoted(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(sys, "executable", r"C:\Users\Ada Lovelace\py\python.exe")
    assert _hint("notes").startswith(
        r'Install them with:  "C:\Users\Ada Lovelace\py\python.exe" -m pip install '
    )


def test_a_pipx_venv_gets_pipx_inject(monkeypatch, tmp_path):
    venv = tmp_path / "yazses"
    venv.mkdir()
    monkeypatch.setattr(sys, "prefix", str(venv))
    out = _hint("notes", channel=install_txn.PIPX)
    assert out == 'Install them with:  pipx inject yazses "llama-cpp-python>=0.3.33"'


def test_a_uv_tool_keeps_what_its_receipt_already_records(monkeypatch, tmp_path):
    """A bare `uv tool install --with X` replaces the with-list; the hint must not."""
    env = tmp_path / "tools" / "yazses"
    env.mkdir(parents=True)
    (env / "uv-receipt.toml").write_text(
        "[tool]\nrequirements = [\n"
        '  { name = "yazses", extras = ["desktop"] },\n'
        '  { name = "onnx-asr", extras = ["cpu", "hub"], specifier = ">=0.12" },\n'
        "]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "prefix", str(env))
    out = _hint("notes", channel=install_txn.UV_TOOL)
    assert out.startswith("Install them with:  uv tool install ")
    assert '--with "onnx-asr[cpu,hub]>=0.12"' in out
    assert '--with "llama-cpp-python>=0.3.33"' in out
    assert out.endswith('"yazses[desktop]"')


def test_a_source_checkout_syncs_the_extra_without_dropping_the_others():
    out = _hint("notes", channel=install_txn.EDITABLE)
    assert out == "Install them with:  uv sync --inexact --extra notes"


def test_a_blocked_environment_without_a_capability_gets_the_reason():
    out = _hint("notes", blocked=lambda p: "the system Python belongs to the OS")
    assert out == "the system Python belongs to the OS"


def test_everything_installed_means_installing_is_not_the_fix():
    """PySide6 present but unusable (missing Qt system libs) must not say 'install'."""
    assert _hint("desktop", feature="tray", features=[_row()],
                 installed=lambda name: True) == ""


# ---- the voiceprint message tells the two causes apart -------------------------

class _Vp:
    def __init__(self, enabled=True, backend="ecapa"):
        self.enabled = enabled
        self.backend = backend


def test_voiceprint_off_is_not_blamed_on_a_missing_library(monkeypatch):
    from yazses.voiceprint import factory

    monkeypatch.setattr(remedy, "install_hint", lambda *a, **k: pytest.fail("hinted"))
    out = factory.unavailable_message(_Vp(enabled=False))
    assert "`[voiceprint] enabled = true`" in out


@pytest.mark.parametrize("backend, extra", [("ecapa", "voiceprint"),
                                            ("resemblyzer", "voiceprint-resemblyzer")])
def test_each_backend_asks_for_its_own_extra(monkeypatch, backend, extra):
    from yazses.voiceprint import factory

    calls: list[tuple] = []
    monkeypatch.setattr(
        remedy, "install_hint",
        lambda e, **k: calls.append((e, k.get("feature"))) or "HINT",
    )
    out = factory.unavailable_message(_Vp(backend=backend))
    assert out.endswith("HINT")
    assert calls == [(extra, "cocktail")]
    assert "uv sync" not in out
