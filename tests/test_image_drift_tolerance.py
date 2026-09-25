"""The tolerance every artwork guard compares with must still catch a wrong image.

`scripts/imagediff.py` exists because exact comparison is the wrong test: PNG bytes are
not reproducible across platforms, and neither are the decoded pixels — `render_mark`
supersamples in floating point, and `ubuntu-24.04-arm` does not always land on the same
last bit as x86_64. Replacing an exact comparison with a tolerant one is also the easiest
way to delete a guard while appearing to keep it, so the tolerance is measured here
against both sides of the question it has to answer:

* a rendering difference an architecture can plausibly produce must be **accepted**;
* every drift these guards exist to catch must still be **rejected**.

The margin between the two is two orders of magnitude on the criterion that does the
work (the share of pixels moving further than a quantisation step), and this file fails
if that margin closes — from either direction. The numbers in `imagediff`'s docstring
are the ones produced here.

Pillow and the helper are imported inside the tests: this file must still *collect* on
the FreeBSD leg, where Pillow is installed best-effort and may be absent.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from tests.imageprobe import image_diff as _imagediff


@lru_cache(maxsize=None)
def _mark(size: int = 256, **kwargs):
    """A render of the mark. Cached: supersampling 256 px eight times over is the whole
    runtime of this file, and nothing here mutates what it is given."""
    pytest.importorskip("PIL", reason="rendering the mark needs Pillow")
    from yazses.brandmark import render_mark

    return render_mark(size, **kwargs)


def _jittered(img, amplitude: int, seed: int = 20260925):
    """The mark with every channel of every pixel moved by ±`amplitude`.

    This is the worst case of the failure mode the tolerance exists to absorb, not an
    average one: a float resampling difference between two architectures moves *some*
    edge pixels by one quantisation step, so moving *every* pixel by one — or two — is
    already more jitter than the real thing can produce.
    """
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(seed)
    arr = np.asarray(img.convert("RGBA")).astype(np.int16)
    noise = rng.choice(np.array([-amplitude, amplitude], dtype=np.int16), size=arr.shape)
    return Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8), "RGBA")


# Differences an architecture can produce. `describe` a case badly and the guard either
# fires on correct CI legs or stops firing at all, so each row says what it models.
JITTER = {
    "identical": lambda base: base.copy(),
    "±1 on every pixel": lambda base: _jittered(base, 1),
    "±2 on every pixel": lambda base: _jittered(base, 2),
}

# Differences that are drift. Every one of these has actually happened to an icon in
# this repository, or is the regression a committed asset would show if it had.
DRIFT = {
    # `contrib/icons/yazses-*.png`: the right design, drawn by an older `render_mark`.
    "an older renderer": lambda base: _mark(base.width, supersample=4),
    # `test_ico_frames_are_natively_rendered_not_downscaled` guards exactly this.
    "downscaled, not natively drawn": lambda base: _downscaled(base.width),
    "the mark shifted by one pixel": lambda base: _offset(base),
    "the wave bars missing": lambda base: _mark(base.width, wave=False),
    # `snap/gui/yazses.png` and the Store box art: a different logo entirely.
    "a flat blue badge, as the retired logo had": lambda base: _mark(
        base.width, fill=(30, 140, 230)
    ),
}


def _downscaled(size: int):
    from PIL import Image

    return _mark(size * 4).resize((size, size), Image.Resampling.LANCZOS)


def _offset(img):
    from PIL import ImageChops

    return ImageChops.offset(img, 1, 0)


@pytest.mark.parametrize("name", sorted(JITTER))
def test_architecture_jitter_is_accepted(name: str) -> None:
    """A guard that reddens on a correct arm64 render teaches people to ignore it."""
    imagediff = _imagediff()
    base = _mark()
    delta = imagediff.difference(base, JITTER[name](base))
    assert delta.within_tolerance, f"{name} was rejected as drift: {delta.describe()}"
    assert delta.hot == 0, (
        f"{name} moved {delta.hot} pixels past the jitter ceiling. The ceiling is what "
        "separates jitter from drift; if quantisation noise reaches it, the separation "
        f"is gone. {delta.describe()}"
    )


@pytest.mark.parametrize("name", sorted(DRIFT))
def test_real_drift_is_rejected(name: str) -> None:
    """The half a tolerance can silently delete."""
    imagediff = _imagediff()
    base = _mark()
    delta = imagediff.difference(base, DRIFT[name](base))
    assert not delta.within_tolerance, (
        f"'{name}' passed the drift guard: {delta.describe()}. A tolerance that accepts "
        "this accepts a stale asset, which is the whole thing these guards are for."
    )
    assert delta.hot_fraction > 5 * imagediff.HOT_FRACTION, (
        f"'{name}' is only just over the line ({delta.describe()}). The budget is meant "
        "to sit an order of magnitude below the faintest real drift."
    )


def test_the_mean_alone_would_not_separate_them() -> None:
    """Why the guard counts pixels rather than averaging them.

    An older `render_mark` moves a small share of pixels a long way, so its *mean* is
    lower than the mean of ±1 quantisation noise on every pixel. A mean-only tolerance
    wide enough to accept the jitter cannot reject the stale render — which is how a
    portable guard becomes an absent one.
    """
    imagediff = _imagediff()
    base = _mark()
    stale = imagediff.difference(base, _mark(base.width, supersample=4))
    jitter = imagediff.difference(base, _jittered(base, 1))

    assert stale.mean < jitter.mean, (
        f"stale render mean {stale.mean:.3f}, jitter mean {jitter.mean:.3f} — if this "
        "ever reverses, the second criterion can be reconsidered"
    )
    assert stale.hot_fraction > jitter.hot_fraction, stale.describe()
    assert not stale.within_tolerance and jitter.within_tolerance


def test_comparing_different_sizes_raises_rather_than_reporting_a_match() -> None:
    imagediff = _imagediff()
    with pytest.raises(ValueError, match="sizes differ"):
        imagediff.difference(_mark(64), _mark(32))


def test_comparing_an_empty_image_raises_rather_than_reporting_a_match() -> None:
    """Zero pixels is the shape that makes every averaging guard green."""
    pytest.importorskip("PIL")
    from PIL import Image

    imagediff = _imagediff()
    empty = Image.new("RGBA", (0, 0))
    with pytest.raises(ValueError, match="empty image"):
        imagediff.difference(empty, empty)


def test_matches_and_explain_agree_with_the_measurement() -> None:
    """The two convenience wrappers are what the callers use; neither may soften it."""
    imagediff = _imagediff()
    base = _mark(128)
    wrong = _mark(128, fill=(30, 140, 230))

    assert imagediff.matches(base, _jittered(base, 1))
    assert imagediff.explain(base, _jittered(base, 1)) is None
    assert not imagediff.matches(base, wrong)
    assert "mean" in (imagediff.explain(base, wrong) or "")
