"""The Chocolatey package must checksum the file it actually downloads.

`render-chocolatey.py` built the URL and the checksum independently: the URL
hardcoded ``windows-x64.exe``, while the checksum took the *first* line ending in
``.exe`` from SHA256SUMS.txt. That file is not ordered by architecture -- in the
real v2.36.0 release the arm64 line comes first -- so the package shipped the x64
installer paired with the arm64 digest and Chocolatey refused every install.

It was invisible for nineteen releases because CHOCO_API_KEY was never set, so the
publish job skipped and the renderer never ran. It became shippable the moment the
secret was added.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The real SHA256SUMS.txt from v2.36.0, arm64 before x64 -- the ordering that broke it.
REAL_SUMS = """\
b5360b0ce8994dc67210067ef96edeece0ec80675930b0b2b0e0b26d376c6035  yazses_2.36.0_amd64.deb
d9b9e0d378826c2ae9703efab05e414c02ba0bd0009e9bb972b23b5c0dc47b70  YazSes-2.36.0-macos-arm64.dmg
187a31129f3102c3e06f81526fb19e7a3c804bc55d84d8d74daf208da2df5c02  YazSes-2.36.0-windows-arm64.exe
6de31b891d20bb35e531b0d47cb057b5b561920d9ae8140a95a2f50cf36b1204  YazSes-2.36.0-windows-x64.exe
"""
X64_DIGEST = "6de31b891d20bb35e531b0d47cb057b5b561920d9ae8140a95a2f50cf36b1204"
ARM64_DIGEST = "187a31129f3102c3e06f81526fb19e7a3c804bc55d84d8d74daf208da2df5c02"


def _load():
    path = ROOT / "scripts" / "render-chocolatey.py"
    spec = importlib.util.spec_from_file_location("render_chocolatey", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def render(monkeypatch):
    mod = _load()

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    monkeypatch.setattr(
        mod.urllib.request, "urlopen", lambda *a, **k: _Resp(REAL_SUMS.encode())
    )
    return mod


def test_checksum_is_the_x64_one_not_whichever_comes_first(render):
    assert render.sha_for_exe("2.36.0") == X64_DIGEST
    assert render.sha_for_exe("2.36.0") != ARM64_DIGEST


def test_url_and_checksum_name_the_same_file(render, tmp_path):
    """The end-to-end property: whatever the script writes must be self-consistent."""
    nuspec = tmp_path / "yazses.nuspec"
    nuspec.write_text("<package><version>0.0.0</version></package>", encoding="utf-8")
    install = tmp_path / "chocolateyinstall.ps1"
    install.write_text(
        "$packageArgs = @{\n"
        "  url64bit       = 'https://example.invalid/old.exe'\n"
        "  checksum64     = 'deadbeef'\n"
        "}\n",
        encoding="utf-8",
    )

    render.main("2.36.0", str(nuspec), str(install))
    written = install.read_text(encoding="utf-8")

    assert "YazSes-2.36.0-windows-x64.exe" in written
    assert X64_DIGEST in written
    # The specific regression: the arm64 digest must never appear beside an x64 URL.
    assert ARM64_DIGEST not in written
    assert "<version>2.36.0</version>" in nuspec.read_text(encoding="utf-8")


def test_a_missing_x64_asset_fails_loudly_rather_than_guessing(render, monkeypatch):
    """An arm64-only release must abort, not silently checksum the wrong file."""
    arm_only = "187a3112  YazSes-2.36.0-windows-arm64.exe\n"

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    monkeypatch.setattr(
        render.urllib.request, "urlopen", lambda *a, **k: _Resp(arm_only.encode())
    )
    with pytest.raises(SystemExit):
        render.sha_for_exe("2.36.0")
