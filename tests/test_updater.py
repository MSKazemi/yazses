"""Self-update logic: detect install method, find latest, decide if newer.

`yazses update` checks the source that matches how YazSes was installed (PyPI for
pip/pipx/uv-tool, the tracked snap channel for snap) and only offers an upgrade
when the available version is strictly newer. Pure/deterministic here — network
and subprocess are injected. See src/yazses/system/updater.py.
"""
from __future__ import annotations

from yazses.system import updater

# ---- install-method detection ---------------------------------------------

def test_detect_snap_install():
    assert updater.detect_install_method("/snap/yazses/11/lib/python3.12/site-packages/yazses/__init__.py") == "snap"


def test_detect_uv_tool_install():
    p = "/home/u/.local/share/uv/tools/yazses/lib/python3.12/site-packages/yazses/__init__.py"
    assert updater.detect_install_method(p) == "uv"


def test_detect_pipx_install():
    p = "/home/u/.local/pipx/venvs/yazses/lib/python3.12/site-packages/yazses/__init__.py"
    assert updater.detect_install_method(p) == "pipx"


def test_detect_plain_pip_install():
    p = "/usr/lib/python3.12/site-packages/yazses/__init__.py"
    assert updater.detect_install_method(p) == "pip"


# ---- version comparison ----------------------------------------------------

def test_is_newer_true_false_equal():
    assert updater.is_newer("0.5.0", "0.4.1") is True
    assert updater.is_newer("0.4.1", "0.5.0") is False
    assert updater.is_newer("0.8.0", "0.8.0") is False


def test_is_newer_handles_prerelease_and_garbage():
    assert updater.is_newer("1.0.0", "1.0.0rc1") is True
    assert updater.is_newer("not-a-version", "1.0.0") is False  # never offer on garbage


# ---- source parsers (pure) -------------------------------------------------

def test_pypi_version_from_json():
    assert updater._pypi_version_from_json({"info": {"version": "1.2.3"}}) == "1.2.3"
    assert updater._pypi_version_from_json({}) is None


_SNAP_INFO = """\
name:      yazses
tracking:     latest/edge
channels:
  latest/stable:    --
  latest/candidate: --
  latest/beta:      --
  latest/edge:      0.5.1 2026-05-31 (11) 136MB -
installed:          0.5.1            (11) 136MB -
"""


def test_snap_tracked_version_parses_tracked_channel():
    assert updater._snap_tracked_version(_SNAP_INFO) == "0.5.1"


def test_snap_tracked_version_none_when_channel_empty():
    text = "tracking:     latest/stable\nchannels:\n  latest/stable:    --\n"
    assert updater._snap_tracked_version(text) is None


# ---- upgrade command mapping ----------------------------------------------

def test_upgrade_command_per_method():
    assert updater.upgrade_command("snap")[:3] == ["sudo", "snap", "refresh"]
    assert updater.upgrade_command("uv")[:3] == ["uv", "tool", "upgrade"]
    assert updater.upgrade_command("pipx")[:2] == ["pipx", "upgrade"]
    assert updater.upgrade_command("pip")[:3] == ["pip", "install", "--upgrade"]
    assert updater.upgrade_command("unknown") is None


# ---- check_update orchestration (injected latest-resolver) ------------------

def test_check_update_available(monkeypatch):
    monkeypatch.setattr(updater, "_latest_for_method", lambda method, pkg: "0.5.0")
    st = updater.check_update("0.4.1", method="pip")
    assert st.available is True
    assert st.latest == "0.5.0"
    assert st.command[:3] == ["pip", "install", "--upgrade"]


def test_check_update_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "_latest_for_method", lambda method, pkg: "0.4.1")
    st = updater.check_update("0.8.0", method="pip")
    assert st.available is False
    assert st.command is None


def test_check_update_no_latest_resolved(monkeypatch):
    monkeypatch.setattr(updater, "_latest_for_method", lambda method, pkg: None)
    st = updater.check_update("0.8.0", method="uv")
    assert st.available is False
    assert "could not" in st.note.lower() or st.latest is None
