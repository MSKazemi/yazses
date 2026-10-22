"""`detect_install_method` recognises a uv tool by its receipt, not by its path.

It classified a uv tool install by the substrings ``/uv/tools/`` and
``/uv/data/tools/``. A ``UV_TOOL_DIR`` pointing anywhere else read as ``pip``, and
`yazses update` then told the user to ``pip install --upgrade yazses`` — which
upgrades some other environment, exits 0, and leaves the running one where it was.
uv writes ``uv-receipt.toml`` at the root of every tool environment, which is
``sys.prefix`` for the interpreter running YazSes; that file is now the signal, and
the substrings are the fallback.
"""
from __future__ import annotations

import sys

from yazses.system import updater


def _env(tmp_path, *, receipt: bool, name: str = "yazses"):
    env = tmp_path / name
    pkg = env / "lib" / "python3.12" / "site-packages" / "yazses"
    pkg.mkdir(parents=True)
    if receipt:
        (env / "uv-receipt.toml").write_text(
            '[tool]\nrequirements = [{ name = "yazses" }]\n', encoding="utf-8"
        )
    return env, str(pkg / "__init__.py")


def test_a_custom_uv_tool_dir_is_still_a_uv_install(tmp_path):
    # /opt/tools/yazses: none of the substrings the path test knows.
    env, init = _env(tmp_path / "opt" / "tools", receipt=True)
    assert "/uv/" not in init.replace("\\", "/")
    assert updater.detect_install_method(init, frozen=False, prefix=str(env)) == "uv"


def test_the_receipt_is_read_from_the_running_environment_by_default(tmp_path, monkeypatch):
    """Production passes nothing: the answer must come from ``sys.prefix``."""
    env, _init = _env(tmp_path / "custom", receipt=True)
    monkeypatch.setattr(sys, "prefix", str(env))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert updater.detect_install_method() == "uv"


def test_an_explicit_path_is_not_answered_by_the_test_runners_venv(tmp_path, monkeypatch):
    env, _init = _env(tmp_path / "custom", receipt=True)
    monkeypatch.setattr(sys, "prefix", str(env))
    p = "/usr/lib/python3.12/site-packages/yazses/__init__.py"
    assert updater.detect_install_method(p, frozen=False) == "pip"


def test_the_windows_default_tool_dir_still_matches_without_a_receipt():
    path = r"C:\Users\u\AppData\Roaming\uv\data\tools\yazses\Lib\site-packages\yazses\x.py"
    assert updater.detect_install_method(path, frozen=False) == "uv"


def test_the_unix_default_tool_dir_still_matches_without_a_receipt(tmp_path):
    p = "/home/u/.local/share/uv/tools/yazses/lib/python3.12/site-packages/yazses/x.py"
    no_receipt = tmp_path / "empty"
    no_receipt.mkdir()
    assert updater.detect_install_method(p, frozen=False, prefix=str(no_receipt)) == "uv"


def test_a_plain_venv_without_a_receipt_is_not_uv(tmp_path):
    env, init = _env(tmp_path / "venvs", receipt=False, name="myenv")
    assert updater.detect_install_method(init, frozen=False, prefix=str(env)) == "pip"


def test_a_pipx_venv_is_pipx(tmp_path):
    env, init = _env(tmp_path / "pipx" / "venvs", receipt=False)
    (env / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    assert updater.detect_install_method(init, frozen=False, prefix=str(env)) == "pipx"


def test_a_receipt_never_outranks_a_frozen_bundle(tmp_path):
    env, init = _env(tmp_path, receipt=True)
    assert updater.detect_install_method(
        init, frozen=True, choco=False, platform="win32", msix=False, prefix=str(env)
    ) == "windows-installer"


def test_a_custom_uv_tool_dir_gets_the_uv_upgrade_steps(tmp_path):
    """The point of the fix: the recipe that follows from the method."""
    env, init = _env(tmp_path / "opt" / "tools", receipt=True)
    method = updater.detect_install_method(init, frozen=False, prefix=str(env))
    assert method == "uv"
    assert updater.upgrade_command(method)[:2] == ["uv", "tool"]
    steps = " ".join(updater.manual_update_steps(method))
    assert "pip install --upgrade" not in steps
