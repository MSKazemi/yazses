"""The Microsoft Store artwork must be the current brand mark, not a retired one.

`packaging/store/boxart-1080.png` was the **old blue speech-bubble logo** -- the design
retired in 0e45007 ("the Snap Store showed a different logo from every other surface").
The fix reached `snap/gui/yazses.{svg,png}` on 2026-08-18 and never reached the Store
asset, which was last written on 2026-08-14 by a cairosvg snippet **pasted into a
README**. A build artefact that a human recipe produces and no script redraws is one
nobody re-runs, so the correction stopped one directory short and the listing would have
shipped a logo appearing nowhere else in the product.

These tests bind the committed assets to `yazses.brandmark.render_mark`, the same
renderer the tray, the .ico and the .icns already share, so the next brand change cannot
land in some surfaces and not others.
"""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "gen-store-art.py"
BOXART = ROOT / "packaging" / "store" / "boxart-1080.png"
POSTER = ROOT / "packaging" / "store" / "poster-720x1080.png"

# Partner Center rejects anything that is not exactly the declared aspect.
EXPECTED = {BOXART: (1080, 1080), POSTER: (720, 1080)}


def png_size(path: Path) -> tuple[int, int]:
    """Read a PNG's dimensions with the stdlib only.

    Pillow is deliberately not imported at module scope: the FreeBSD leg does not install
    it, and a module-scope import there is a *collection* error that fails the whole run
    before any test executes -- `tests/test_freebsd_job_can_import_the_suite.py` enforces
    exactly this, and caught it. `test_icon_assets.py` parses its containers with `struct`
    for the same reason, so the structural guards run everywhere and only the
    pixel-comparing ones need Pillow.
    """
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    assert head[12:16] == b"IHDR", f"{path.name}: first chunk is not IHDR"
    return struct.unpack(">II", head[16:24])


@pytest.mark.parametrize("path", list(EXPECTED), ids=lambda p: p.name)
def test_the_asset_exists(path: Path) -> None:
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing; run `make store-art`"


@pytest.mark.parametrize("path", list(EXPECTED), ids=lambda p: p.name)
def test_the_asset_has_the_exact_dimensions_the_store_demands(path: Path) -> None:
    assert png_size(path) == EXPECTED[path]


def test_the_generator_exists_and_is_the_single_source() -> None:
    assert GEN.is_file(), "the Store art must be generated, not hand-made"


def test_committed_assets_match_the_generator() -> None:
    """The drift guard, delegated to the generator's own --check.

    The comparison is deliberately tolerant and scoped, because an exact one is wrong
    three times over: PNG bytes are not reproducible across platforms, decoded *pixels*
    are not either (CI proved the text-free box art differs on ubuntu-24.04-arm), and the
    poster's wordmark uses a system font that differs or is absent between platforms. See
    `scripts/gen-store-art.py` for the measured tolerance.
    """
    pytest.importorskip("PIL", reason="the generator needs Pillow")
    result = subprocess.run(
        [sys.executable, str(GEN), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"Store art has drifted from the brand mark; run `make store-art`.\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_the_art_is_the_current_mark_not_the_retired_blue_logo() -> None:
    """The specific regression: the retired mark was blue/cyan, the current one purple.

    Sampling the mark's own plate rather than the whole image, because both designs sit
    on a white field -- an average over the full canvas is dominated by the background
    and cannot tell the two apart.
    """
    Image = pytest.importorskip("PIL.Image", reason="pixel inspection needs Pillow")
    img = Image.open(BOXART).convert("RGB")
    w, h = img.size
    # A point well inside the current mark's rounded plate: above the wave bars and
    # beside the Y stem. The retired logo's speech bubble does not cover this point at
    # all, so it reads as bare white there -- which is itself a failure, and a clearer
    # one than a colour-ratio complaint.
    r, g, b = img.getpixel((round(w * 0.24), round(h * 0.30)))

    assert not (r > 240 and g > 240 and b > 240), (
        f"sampled {(r, g, b)} -- bare white where the plate should be. The mark does not "
        "cover this point, which is the signature of the retired speech-bubble logo "
        "(a smaller, differently-placed shape) rather than the current rounded plate."
    )
    # Brand purple is (124, 77, 255) at the top stop and (69, 39, 160) at the bottom:
    # blue dominant, red clearly above green. The retired plate was a blue/cyan gradient,
    # where green ran *above* red.
    assert b > r > g, (
        f"plate sampled {(r, g, b)}: expected blue > red > green, the brand-purple "
        "signature. Green at or above red is the retired blue/cyan logo."
    )
