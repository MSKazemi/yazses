"""Contract tests for the committed icon containers in `assets/`.

`packaging/windows/yazses.spec` referenced `assets/yazses.ico` for the whole life
of the file, and the file never existed — so `icon=... if ICON.exists() else None`
quietly handed PyInstaller no icon, and every Windows release shipped with the
default bootloader artwork on the desktop shortcut, the Start menu, the taskbar
and Add/Remove Programs. Nothing in the build, the tests or CI said a word. The
macOS spec carried the identical dangling `.icns`.

The structural tests below deliberately use only `struct` from the stdlib, so
they guard the assets on every CI leg whether or not Pillow is installed.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ICO = _REPO / "assets" / "yazses.ico"
_ICNS = _REPO / "assets" / "yazses.icns"

# Frames Windows picks between for 100/125/150/200% scaling, plus the large ones
# Explorer and the shell use. Kept in step with scripts/gen-icons.py::ICO_SIZES.
_REQUIRED_ICO_SIZES = {16, 20, 24, 32, 48, 64, 128, 256}


def _ico_directory(data: bytes) -> list[tuple[int, int, int, int]]:
    """Parse the ICONDIR into (width, height, byte length, payload offset)."""
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0, "ICONDIR reserved field must be zero"
    assert kind == 1, f"expected an icon (type 1), got type {kind}"
    entries = []
    for i in range(count):
        w, h, _colors, _res, _planes, _bpp, size, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * i : 22 + 16 * i]
        )
        # A zero byte means 256 — the field is only one byte wide.
        entries.append((w or 256, h or 256, size, offset))
    return entries


def test_the_windows_icon_exists() -> None:
    assert _ICO.is_file(), (
        "assets/yazses.ico is missing — run `uv run python scripts/gen-icons.py`. "
        "Without it the Windows build ships PyInstaller's default icon."
    )


def test_the_macos_icon_exists() -> None:
    assert _ICNS.is_file(), (
        "assets/yazses.icns is missing — run `uv run python scripts/gen-icons.py`."
    )


def test_ico_carries_every_required_frame() -> None:
    entries = _ico_directory(_ICO.read_bytes())
    assert {w for w, _h, _s, _o in entries} >= _REQUIRED_ICO_SIZES


def test_ico_frames_are_square_and_within_the_file() -> None:
    data = _ICO.read_bytes()
    for w, h, size, offset in _ico_directory(data):
        assert w == h, f"frame {w}x{h} is not square"
        assert offset + size <= len(data), f"{w}px frame runs past the end of the file"


def test_ico_frames_are_png_encoded() -> None:
    """Each frame is its own PNG payload, as Pillow and every Vista+ shell expect."""
    data = _ICO.read_bytes()
    for w, _h, _size, offset in _ico_directory(data):
        assert data[offset : offset + 4] == b"\x89PNG", f"{w}px frame is not a PNG"


def test_icns_is_a_well_formed_container() -> None:
    data = _ICNS.read_bytes()
    magic, declared = struct.unpack(">4sI", data[:8])
    assert magic == b"icns"
    assert declared == len(data), "the icns header length disagrees with the file size"


def test_icns_carries_the_retina_and_standard_chunks() -> None:
    data = _ICNS.read_bytes()
    seen, offset = set(), 8
    while offset < len(data):
        kind, length = struct.unpack(">4sI", data[offset : offset + 8])
        seen.add(kind)
        offset += length
    # ic07..ic10 are 128/256/512/1024; ic11..ic14 are the @2x variants.
    assert {b"ic07", b"ic08", b"ic09", b"ic10"} <= seen


class TestRegeneration:
    """The committed assets must still be what the generator produces."""

    @staticmethod
    def _generator():
        pytest.importorskip("PIL", reason="Pillow is a dev/win32 dependency")
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gen_icons", _REPO / "scripts" / "gen-icons.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_committed_ico_matches_the_generator(self) -> None:
        gen = self._generator()
        assert _ICO.read_bytes() == gen.build_ico(), (
            "assets/yazses.ico is stale — run `uv run python scripts/gen-icons.py`"
        )

    def test_committed_icns_matches_the_generator(self) -> None:
        gen = self._generator()
        assert _ICNS.read_bytes() == gen.build_icns(), (
            "assets/yazses.icns is stale — run `uv run python scripts/gen-icons.py`"
        )

    def test_ico_frames_are_natively_rendered_not_downscaled(self) -> None:
        """A downscaled 16 px frame smears the wave bars; a native one omits them."""
        pytest.importorskip("PIL")
        from PIL import Image

        from yazses.brandmark import render_mark

        ico = Image.open(_ICO)
        for px in (16, 32, 256):
            ico.size = (px, px)
            ico.load()
            assert ico.convert("RGBA").tobytes() == render_mark(px).tobytes(), (
                f"the {px}px frame is not this size's own render"
            )
