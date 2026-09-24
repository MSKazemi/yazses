"""How two renders of the same artwork are compared — and why never exactly.

Every drift guard in this repository asks the same question: *is the committed
artefact still what the generator draws?* The obvious implementation — compare the
bytes, or compare the decoded pixels — answers a different question, and the wrong
one, twice over:

* **PNG bytes are not reproducible.** A different zlib or Pillow build re-encodes
  identical pixels into a different stream. That turned the Windows and macOS release
  legs red on assets that were perfectly correct, and both `gen-icons.py` and
  `test_icon_assets.py` already carry the scar tissue from it.
* **Decoded pixels are not reproducible either.** `brandmark.render_mark` supersamples
  and downsamples in floating point, and `ubuntu-24.04-arm` does not always land on the
  same last bit as x86_64 — on artwork containing no text at all. The store box art
  proved it. The icon guards make the same exact-pixel assumption and are simply not
  read yet, because the arm64 leg is still `continue-on-error`.

So the comparison is a **tolerance**, and the tolerance has to be the right shape.
A mean alone is not: the drift these guards exist to catch is local (a changed mark,
a stale render, a shifted glyph), so it moves a small share of pixels a long way,
while architecture jitter moves nearly every pixel by one quantisation step. Measured
on this renderer at 48 px and 256 px, mean absolute difference alone cannot separate
them — an older `render_mark` differs by a *mean* of 0.28 at 256 px, well under the
0.96 that ±1 on every pixel produces:

| difference                          | mean  | pixels off by > 4 |
|-------------------------------------|-------|-------------------|
| identical                           | 0.00  | 0.000 %           |
| ±1 on every pixel (arch jitter)     | 0.96  | 0.000 %           |
| ±2 on every pixel (jitter, doubled) | 1.92  | 0.000 %           |
| older `render_mark` (supersample 4) | 0.28  | 1.671 %           |
| downscaled instead of natively drawn| 6.84  | 7.303 %           |
| mark shifted by one pixel           | 2.61  | 3.839 %           |
| wave bars missing                   | 18.70 | 11.057 %          |
| the retired blue logo's flat badge  | 70.97 | 91.486 %          |

(`>4` figures at 256 px; the 48 px table has the same two orders of magnitude between
the jitter rows and every drift row. Reproduced by
`tests/test_image_drift_tolerance.py`, which fails if that separation closes.)

Hence two criteria, and a difference fails on either:

* ``MEAN_TOLERANCE`` — catches a change that is *everywhere but small*, such as a
  colour-space or gamma shift, which the hot-pixel count would miss.
* ``HOT_FRACTION`` above ``JITTER_CEILING`` — catches a change that is *local but
  large*, which the mean would miss. This is the criterion that does the work.

Both numbers are measured, not guessed. `JITTER_CEILING` is four times the largest
per-channel step a resampling difference can plausibly produce (±1, occasionally ±2 if
two rounding ties flip in the same channel), and `HOT_FRACTION` sits six times below
the smallest real drift ever recorded here: the `.deb` icons rendered by an older
`render_mark` differed on 0.6 % of pixels (see `gen-icons.py`).

Pillow is imported inside the functions, never at module scope: this module is read by
test files that must still *collect* on the FreeBSD leg, where Pillow is installed
best-effort and may be absent (`tests/test_freebsd_job_can_import_the_suite.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

#: Largest per-channel mean absolute difference two correct renders may show.
#: ±2 on every pixel — twice the worst jitter step, everywhere — measures 1.92.
MEAN_TOLERANCE = 2.0

#: A per-channel difference above this is not resampling noise. Jitter is ±1, rarely
#: ±2; every real drift measured here moves its pixels by 16 or more.
JITTER_CEILING = 4

#: Share of pixels allowed to exceed JITTER_CEILING. The faintest real drift on record
#: (the .deb icons, rendered by an older mark) moved 0.6 % of pixels; jitter moves none.
HOT_FRACTION = 0.001


class Difference(NamedTuple):
    """What separates two renders of the same artwork."""

    mean: float
    """Largest per-channel mean absolute difference, over every band."""

    hot: int
    """Pixels whose difference exceeds JITTER_CEILING in at least one band."""

    pixels: int
    """Total pixels compared."""

    peak: int
    """Largest single per-channel difference anywhere."""

    @property
    def hot_fraction(self) -> float:
        return self.hot / self.pixels

    @property
    def within_tolerance(self) -> bool:
        return self.mean <= MEAN_TOLERANCE and self.hot_fraction <= HOT_FRACTION

    def describe(self) -> str:
        return (
            f"mean {self.mean:.3f} (tolerance {MEAN_TOLERANCE}), "
            f"{self.hot}/{self.pixels} pixels ({self.hot_fraction * 100:.3f} %) differ by "
            f"more than {JITTER_CEILING} (tolerance {HOT_FRACTION * 100:.3f} %), "
            f"peak {self.peak}"
        )


def difference(a: Image, b: Image) -> Difference:
    """Measure the difference between two same-size images.

    Raises `ValueError` when the images cannot be compared — different sizes, or no
    pixels at all. A comparison that cannot be performed is not a match: reporting
    "no difference" for an input this cannot read is how a guard comes to certify
    whatever it was pointed at.
    """
    from PIL import ImageChops, ImageStat

    if a.size != b.size:
        raise ValueError(f"cannot compare {a.size} with {b.size}: the sizes differ")
    if a.width == 0 or a.height == 0:
        raise ValueError("cannot compare an empty image")

    left, right = a.convert("RGBA"), b.convert("RGBA")
    delta = ImageChops.difference(left, right)

    # Per-pixel maximum across the bands, so one badly wrong channel cannot be
    # averaged away by three correct ones.
    bands = delta.split()
    worst = bands[0]
    for band in bands[1:]:
        worst = ImageChops.lighter(worst, band)
    histogram = worst.histogram()

    return Difference(
        mean=max(ImageStat.Stat(delta).mean),
        hot=sum(count for value, count in enumerate(histogram) if value > JITTER_CEILING),
        pixels=left.width * left.height,
        peak=max((value for value, count in enumerate(histogram) if count), default=0),
    )


def explain(committed: Image, expected: Image) -> str | None:
    """`None` when the two images are the same artwork; else why they are not."""
    delta = difference(committed, expected)
    if delta.within_tolerance:
        return None
    return delta.describe()


def matches(committed: Image, expected: Image) -> bool:
    """`True` when the difference is architecture jitter rather than drift."""
    return explain(committed, expected) is None
