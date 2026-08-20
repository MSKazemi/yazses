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
import subprocess
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

    # Compared as images, never as bytes. PNG output is not reproducible across
    # platforms — zlib version and Pillow build change the compressed stream for
    # pixel-identical input — so a byte assertion here passes only on the machine
    # that produced the committed file and fails on every other CI leg. It did:
    # the Windows and macOS legs went red on assets that were perfectly correct.
    # Decoding first keeps what the test is actually for (the mark changed and
    # nobody regenerated) and drops the part that only measured the encoder.
    @staticmethod
    def _frames(blob: bytes) -> dict:
        import io

        from PIL import Image, ImageSequence

        out = {}
        with Image.open(io.BytesIO(blob)) as im:
            for frame in ImageSequence.Iterator(im):
                out[frame.size] = frame.convert("RGBA").tobytes()
        return out

    def test_committed_ico_matches_the_generator(self) -> None:
        gen = self._generator()
        assert self._frames(_ICO.read_bytes()) == self._frames(gen.build_ico()), (
            "assets/yazses.ico is stale — run `uv run python scripts/gen-icons.py`"
        )

    @staticmethod
    def _icns_sizes(blob: bytes) -> set:
        """The representation set an .icns declares.

        Not the pixels: ImageSequence yields a single (largest) frame for ICNS,
        and macOS decodes that one through a different path than Linux, so the
        RGBA bytes differ for an identical file. `info["sizes"]` is what the
        container actually declares and is stable across decoders.
        """
        import io

        from PIL import Image

        with Image.open(io.BytesIO(blob)) as im:
            return set(im.info.get("sizes", []))

    def test_committed_icns_matches_the_generator(self) -> None:
        """Structure only — see _icns_sizes. Pixel-level staleness is covered by
        the .ico test above: both are rendered from the same brandmark, so a
        changed mark that was not regenerated fails there."""
        gen = self._generator()
        assert self._icns_sizes(_ICNS.read_bytes()) == self._icns_sizes(gen.build_icns()), (
            "assets/yazses.icns is stale — run `uv run python scripts/gen-icons.py`"
        )

    def test_the_regeneration_check_still_detects_a_changed_mark(self) -> None:
        """Guards the guard: comparing decoded pixels must still fail when the
        artwork actually differs, or the relaxation above would be a no-op."""
        import io

        from PIL import Image

        different = io.BytesIO()
        Image.new("RGBA", (256, 256), (1, 2, 3, 255)).save(different, format="PNG")
        assert self._frames(_ICO.read_bytes()) != self._frames(different.getvalue())

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


# ---------------------------------------------------------------------------
# The Linux icons, which no generator owned until they had already drifted
# ---------------------------------------------------------------------------
#
# `assets/` was guarded from the day it existed. The Linux icons were not, and the
# difference showed:
#
# * `contrib/icons/yazses-<size>.png` — copied into `usr/share/icons/hicolor/` by
#   `scripts/build-deb.sh`, so they are the app-grid icon of every .deb install.
#   They were the right design rendered by an older `render_mark`: composited over
#   white they differed on 0.6–5.9% of pixels, max delta 30/255.
# * `snap/gui/yazses.png` — the `icon:` in `snapcraft.yaml`, so the Snap Store
#   listing and the app grid on every snap install. It was **a different logo
#   entirely**: a white square with a blue speech-bubble outline, a navy Y and a
#   violet-to-cyan waveform, against the purple-gradient badge on the website, in
#   the .exe, the .app, the .deb and the tray.
#
# A brand mark that differs per channel is not a rendering bug — it is the product
# looking like two products — and nothing anywhere would have reported it.

_DEB_ICON_DIR = _REPO / "contrib" / "icons"
_SNAP_ICON = _REPO / "snap" / "gui" / "yazses.png"
_CANONICAL_SVG = _REPO / "contrib" / "icons" / "yazses.svg"
_SNAP_SVG = _REPO / "snap" / "gui" / "yazses.svg"


@pytest.mark.parametrize("size", [48, 64, 128, 256])
def test_the_deb_icon_exists(size: int) -> None:
    path = _DEB_ICON_DIR / f"yazses-{size}.png"
    assert path.is_file(), (
        f"{path.relative_to(_REPO)} is missing and build-deb.sh copies it — "
        "run `uv run python scripts/gen-icons.py`"
    )


def test_the_snap_icon_exists() -> None:
    assert _SNAP_ICON.is_file(), (
        "snap/gui/yazses.png is missing and snapcraft.yaml names it as `icon:` — "
        "run `uv run python scripts/gen-icons.py`"
    )


def test_every_icon_the_build_scripts_copy_is_one_the_generator_owns() -> None:
    """The gap itself: a file can be shipped by a build script and generated by nothing.

    Read from `build-deb.sh` and `snapcraft.yaml` rather than from a list here, so
    adding a channel that ships a new icon fails until the generator learns about it.
    """
    gen = TestRegeneration._generator()
    owned = {p.resolve() for p in gen.wanted_assets()}

    # Read the sizes out of the shell loop rather than grepping for a literal
    # filename: the script builds the path from `${size}`, so `yazses-48.png` never
    # appears anywhere in it and a literal check passes on a script that ships
    # nothing. Parsing the list also catches the *other* direction — a size added to
    # the .deb that the generator does not produce, which would ship a missing file.
    import re

    deb = (_REPO / "scripts" / "build-deb.sh").read_text(encoding="utf-8")
    assert 'contrib/icons/yazses-${size}.png' in deb, (
        "build-deb.sh no longer copies the per-size icons from contrib/icons/"
    )
    loop = re.search(r"for size in ([\d\s]+);\s*do", deb)
    assert loop, "could not find the icon-size loop in build-deb.sh"
    shipped = tuple(int(n) for n in loop.group(1).split())
    assert shipped == tuple(gen.DEB_ICON_SIZES), (
        f"build-deb.sh ships {shipped} but the generator produces "
        f"{tuple(gen.DEB_ICON_SIZES)} — one of them will be a missing file"
    )
    for size in shipped:
        assert (_DEB_ICON_DIR / f"yazses-{size}.png").resolve() in owned

    snapcraft = (_REPO / "snap" / "snapcraft.yaml").read_text(encoding="utf-8")
    assert "snap/gui/yazses.png" in snapcraft, "snapcraft.yaml no longer names this icon"
    assert _SNAP_ICON.resolve() in owned


class TestLinuxIconsMatchTheMark:
    """Every shipped raster icon is the same mark, pixel for pixel."""

    @staticmethod
    def _rgba(path):
        pytest.importorskip("PIL", reason="Pillow is a dev/win32 dependency")
        from PIL import Image

        with Image.open(path) as im:
            return im.size, im.convert("RGBA").tobytes()

    @pytest.mark.parametrize("size", [48, 64, 128, 256])
    def test_the_deb_icons_are_the_canonical_mark(self, size: int) -> None:
        gen = TestRegeneration._generator()
        committed = self._rgba(_DEB_ICON_DIR / f"yazses-{size}.png")
        import io

        expected = self._rgba(io.BytesIO(gen.build_png(size)))
        assert committed == expected, (
            f"contrib/icons/yazses-{size}.png is stale — "
            "run `uv run python scripts/gen-icons.py`"
        )

    def test_the_snap_icon_is_the_canonical_mark(self) -> None:
        """The one that was a different logo. This is the test that would have said so."""
        gen = TestRegeneration._generator()
        import io

        committed = self._rgba(_SNAP_ICON)
        expected = self._rgba(io.BytesIO(gen.build_png(gen.SNAP_ICON_SIZE)))
        assert committed == expected, (
            "snap/gui/yazses.png is not the YazSes mark — the Snap Store and every "
            "snap install would show a different logo from the website, the .exe, "
            "the .app, the .deb and the tray. Run `uv run python scripts/gen-icons.py`"
        )

    def test_every_packaging_copy_of_the_svg_is_the_canonical_svg(self) -> None:
        """It sat beside the PNG carrying the old design, which is how the next
        person regenerates the wrong thing by hand.

        Swept rather than listed. Naming `snap/gui/yazses.svg` here covered the one copy
        that existed and would have said nothing about the next one -- and there is now a
        next one, `packaging/flatpak/com.mskazemi.YazSes.svg`, because a Flathub
        repository is flat and cannot reach into `contrib/`. Every packaging tree that
        needs the mark takes a copy; only the sweep notices when one arrives.

        `docs/` is excluded on a rule, not per file: its SVGs are page furniture --
        diagrams, the social preview, a simplified favicon -- while an SVG anywhere else
        is an app icon a store renders.
        """
        tracked = subprocess.run(
            ["git", "ls-files", "*.svg"],
            cwd=_REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        copies = [
            f
            for f in tracked
            if not f.startswith("docs/") and f != "contrib/icons/yazses.svg"
        ]
        assert copies, "the sweep found nothing to check -- it would pass on anything"
        canonical = _CANONICAL_SVG.read_text(encoding="utf-8")
        drifted = [
            f for f in copies if (_REPO / f).read_text(encoding="utf-8") != canonical
        ]
        assert not drifted, (
            f"{drifted} drifted from contrib/icons/yazses.svg -- the product would show "
            "a different logo per channel, which nothing else reports"
        )


def test_the_check_flag_covers_every_asset_the_writer_writes() -> None:
    """`--check` and the write path read one dict, so they cannot cover different sets.

    That asymmetry is precisely how the Linux icons ended up shipped-but-ungenerated,
    and a guard listing the paths itself would have to be remembered too.
    """
    source = (_REPO / "scripts" / "gen-icons.py").read_text(encoding="utf-8")
    assert source.count("wanted = wanted_assets()") == 1
    assert "wanted.items()" in source


# ---------------------------------------------------------------------------
# The tray-state images in the docs
# ---------------------------------------------------------------------------
#
# `docs/tray-and-overlay.md` explains five badge colours. It used to picture two, and
# said so itself: "🟡 Yellow (no text target) isn't pictured here" — which is the state
# meaning "your words went to the clipboard", i.e. the one a reader most needs to
# recognise and had never seen.
#
# They are rendered rather than captured, from `icon_spec` + `render_mark`, so a change
# to the colour policy must not leave the documentation showing the old colours. That is
# the same drift the .ico/.icns guards above exist for, on a surface a user reads.

_TRAY_STATE_DIR = _REPO / "docs" / "assets"


def _tray_state_generator():
    pytest.importorskip("PIL", reason="Pillow is a dev/win32 dependency")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_tray_states", _REPO / "scripts" / "gen-tray-states.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_documented_badge_state_has_an_image() -> None:
    gen = _tray_state_generator()
    assert len(gen.STATES) == 5, "the docs explain five colours"
    for path in gen.wanted_assets():
        assert path.is_file(), (
            f"{path.relative_to(_REPO)} is missing — "
            "run `uv run python scripts/gen-tray-states.py`"
        )


def test_the_badge_images_still_match_the_colour_policy() -> None:
    """Compared as pixels, never as bytes: PNG output is not reproducible across
    platforms, which has turned CI red on assets that were perfectly correct."""
    import io

    from PIL import Image

    gen = _tray_state_generator()

    def rgba(blob: bytes) -> bytes:
        with Image.open(io.BytesIO(blob)) as im:
            return im.convert("RGBA").tobytes()

    for path, data in gen.wanted_assets().items():
        assert rgba(path.read_bytes()) == rgba(data), (
            f"{path.relative_to(_REPO)} no longer matches what icon_spec/render_mark "
            "produce — run `uv run python scripts/gen-tray-states.py`"
        )


def test_the_five_states_are_five_distinct_colours() -> None:
    """If two states rendered the same, the page would be teaching a distinction the
    badge does not make."""
    gen = _tray_state_generator()
    from yazses.tray.menu import icon_spec

    colours = {icon_spec(status)[0] for _stem, status, _why in gen.STATES}
    assert len(colours) == 5, f"expected 5 distinct badge colours, got {sorted(colours)}"


def test_the_docs_page_shows_every_state_image() -> None:
    """An image nobody references is a file, not documentation."""
    gen = _tray_state_generator()
    page = (_REPO / "docs" / "tray-and-overlay.md").read_text(encoding="utf-8")
    missing = [p.name for p in gen.wanted_assets() if p.name not in page]
    assert not missing, f"generated but never shown on the tray page: {missing}"
