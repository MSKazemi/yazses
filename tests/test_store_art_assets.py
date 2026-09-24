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

import importlib.util
import struct
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "gen-store-art.py"
STORE_DIR = ROOT / "packaging" / "store"
BOXART = STORE_DIR / "boxart-1080.png"
POSTER = STORE_DIR / "poster-720x1080.png"

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


@lru_cache(maxsize=1)
def generator():
    """`scripts/gen-store-art.py` as a module, so its guard can be tested directly."""
    pytest.importorskip("PIL", reason="the generator needs Pillow")
    spec = importlib.util.spec_from_file_location("gen_store_art", GEN)
    assert spec and spec.loader, f"cannot load {GEN}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def store_art_in(directory: Path) -> list[Path]:
    """Every PNG the Store directory ships.

    Raises rather than returning `[]`. Everything below iterates this list, and a loop
    over an empty list passes -- so a sweep that finds nothing must fail, or "every
    committed asset is generated" quietly degrades into "there are no committed assets".
    """
    found = sorted(directory.glob("*.png"))
    if not found:
        raise AssertionError(
            f"{directory} contains no PNG. This sweep exists to notice an asset the "
            "generator does not own; finding nothing means it is checking nothing."
        )
    return found


def test_the_sweep_fails_on_an_empty_directory(tmp_path: Path) -> None:
    """The guard that keeps the guard below from being vacuous."""
    with pytest.raises(AssertionError, match="no PNG"):
        store_art_in(tmp_path)


def test_every_committed_store_asset_is_one_the_generator_owns() -> None:
    """Swept, not listed: the box art rotted precisely because the thing that produced
    it and the thing that shipped it were two different lists."""
    owned = {path.resolve() for path, _build, _size, _region in generator().TARGETS}
    orphans = [p.name for p in store_art_in(STORE_DIR) if p.resolve() not in owned]
    assert not orphans, (
        f"{orphans} sit in packaging/store/ and no generator redraws them. An asset a "
        "listing ships and no script owns is the one that keeps the retired logo."
    )


def test_the_writer_and_the_check_read_the_same_list() -> None:
    """One loop over one tuple, so `--check` cannot verify a smaller set than the
    writer writes -- the asymmetry that left the Linux icons shipped but ungenerated."""
    source = GEN.read_text(encoding="utf-8")
    assert source.count("for path, build, size, region in TARGETS") == 1


def test_a_store_asset_the_guard_cannot_read_is_drift_not_compliance(tmp_path: Path) -> None:
    """A check that cannot parse its input must fail. Silence about an unreadable file
    reads exactly like silence about a correct one."""
    gen = generator()
    expected = gen.build_boxart()

    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(BOXART.read_bytes()[: BOXART.stat().st_size // 2])
    reason = gen.check_asset(truncated, expected, gen.BOXART_SIZE, None)
    assert reason and "unreadable" in reason, reason

    garbage = tmp_path / "garbage.png"
    garbage.write_bytes(b"\x89PNG\r\n\x1a\n this is not an image")
    reason = gen.check_asset(garbage, expected, gen.BOXART_SIZE, None)
    assert reason and "unreadable" in reason, reason

    missing = gen.check_asset(tmp_path / "absent.png", expected, gen.BOXART_SIZE, None)
    assert missing == "missing"


def test_the_drift_guard_rejects_artwork_that_is_not_the_mark(tmp_path: Path) -> None:
    """The half a tolerance can silently delete. The regression it exists to catch is a
    listing carrying a logo that appears nowhere else in the product."""
    Image = pytest.importorskip("PIL.Image", reason="pixel inspection needs Pillow")
    gen = generator()
    expected = gen.build_boxart()

    wrong = tmp_path / "wrong.png"
    Image.new("RGB", gen.BOXART_SIZE, (30, 140, 230)).save(wrong, "PNG")
    assert gen.check_asset(wrong, expected, gen.BOXART_SIZE, None) is not None

    off_size = tmp_path / "off-size.png"
    expected.resize((1000, 1000)).save(off_size, "PNG")
    reason = gen.check_asset(off_size, expected, gen.BOXART_SIZE, None)
    assert reason and "want" in reason, reason


def test_the_drift_guard_accepts_a_render_that_differs_the_way_an_arm_runner_does(
    tmp_path: Path,
) -> None:
    """The other half. `render_mark` supersamples in floating point, so arm64 does not
    always round the way x86_64 does -- on artwork with no text in it at all. A guard
    that reddens there is one every release learns to re-run rather than read."""
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image", reason="pixel inspection needs Pillow")
    gen = generator()
    expected = gen.build_boxart()

    rng = np.random.default_rng(20260925)
    arr = np.asarray(expected.convert("RGB")).astype(np.int16)
    noise = rng.choice(np.array([-1, 1], dtype=np.int16), size=arr.shape)
    jittered = tmp_path / "jittered.png"
    Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8), "RGB").save(jittered, "PNG")

    assert gen.check_asset(jittered, expected, gen.BOXART_SIZE, None) is None


def test_the_posters_text_is_excluded_from_the_comparison_but_its_mark_is_not(
    tmp_path: Path,
) -> None:
    """The scope is a decision, not an accident, so both sides of it are asserted.

    The wordmark is drawn with whatever system font exists, which differs in version or
    is absent between platforms; comparing it would make the guard report the runner's
    font catalogue. The mark above it is pure geometry and is fully compared.
    """
    ImageDraw = pytest.importorskip("PIL.ImageDraw", reason="pixel inspection needs Pillow")
    gen = generator()
    expected = gen.build_poster()
    region = gen.POSTER_DETERMINISTIC

    repainted_text = expected.copy()
    ImageDraw.Draw(repainted_text).rectangle(
        (0, region[3], gen.POSTER_SIZE[0], gen.POSTER_SIZE[1]), fill=(0, 0, 0)
    )
    below = tmp_path / "below.png"
    repainted_text.save(below, "PNG")
    assert gen.check_asset(below, expected, gen.POSTER_SIZE, region) is None, (
        "the wordmark region is compared after all -- the guard now depends on the "
        "runner's fonts"
    )

    repainted_mark = expected.copy()
    ImageDraw.Draw(repainted_mark).rectangle(region, fill=(0, 0, 0))
    above = tmp_path / "above.png"
    repainted_mark.save(above, "PNG")
    assert gen.check_asset(above, expected, gen.POSTER_SIZE, region) is not None, (
        "the mark region is not compared -- the guard would accept any artwork at all"
    )
