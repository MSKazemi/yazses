"""The published benchmark figures must match the JSON they came from.

`docs/benchmarks.md` is the project's credibility page: it exists to say "here are
real numbers, here is the method, re-run it yourself". It stated the VAD gate was
tested against **200 LibriSpeech clips** with a **2.4× margin**, while
`paper/results/vad.json` — the harness's own output — recorded **40 speech clips,
5 silence clips, and 3.4×**. The prose had been edited, or the harness re-run, and
the two drifted apart with nothing to notice.

A page of measurements that disagrees with its measurements is worse than no page,
because the whole value on offer is that the numbers are real.

Scope note: this checks the figures that are *mechanically derivable* from a
results file. Plenty on that page legitimately is not — the narrative, the caveats,
the "what is not measured here" section — and asserting on prose would make the
guard a change-detector that fails on every honest edit.

**Where this runs.** `paper/results/*.json` is gitignored (`.gitignore`: `paper/*`),
so it exists on a machine that has run the harness and nowhere else — CI included.
The module therefore skips when the results are absent, and that skip is honest
rather than a hole: there is genuinely nothing to compare against, and the drift it
catches happens exactly where the files *do* exist, on the machine of whoever
re-ran the harness and then edited the page. The first version asserted the files
were present and turned every CI job on every OS red, which is a fair illustration
of how easily a guard can assume its own environment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "benchmarks.md"
RESULTS = ROOT / "paper" / "results"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _results(name: str) -> dict:
    path = RESULTS / f"{name}.json"
    if not path.is_file():
        pytest.skip(f"{path.relative_to(ROOT)} not present in this checkout")
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_page_exists_and_quotes_numbers() -> None:
    """Guard the guard: a missing or numberless page makes everything below vacuous.

    Asserted on the page only. The results files are gitignored and legitimately
    absent in CI — requiring them here is what reddened every job.
    """
    assert DOC.is_file()
    assert re.search(r"\d+\.\d+\s*%", _doc()), "the page quotes no figures at all"


def test_the_vad_clip_counts_match_the_data() -> None:
    """The specific drift that prompted this: the page claimed 200 clips."""
    config = _results("vad")["config"]
    speech = config["n_speech_clips"]
    silence = config["n_silence_clips"]
    text = _doc()

    assert f"({speech}/{speech})" in text, (
        f"the page does not report {speech}/{speech} speech clips, which is what "
        f"paper/results/vad.json records"
    )
    assert f"({silence}/{silence})" in text or f"{silence} negatives" in text, (
        f"the page does not report the {silence} negatives the run actually used"
    )


def test_the_vad_margin_matches_the_data() -> None:
    margin = _results("vad")["results"]["speech_rms_to_threshold_margin_x"]
    text = _doc()
    quoted = set(re.findall(r"(\d+\.\d+)×\s*margin", text))
    assert quoted, "the page no longer quotes a margin at all"
    assert f"{margin}" in quoted, (
        f"the page quotes {sorted(quoted)}× as the speech-to-threshold margin; "
        f"paper/results/vad.json measured {margin}×"
    )


def test_a_stale_clip_count_would_be_caught() -> None:
    """Red-green for the check itself, without editing the real page.

    A guard that only ever sees agreeing inputs has never demonstrated it can
    disagree — which is how the 200-vs-40 drift survived in the first place.
    """
    fake_doc = "| Speech detected | 100 % (200/200) |"
    config = {"n_speech_clips": 40}
    assert f"({config['n_speech_clips']}/{config['n_speech_clips']})" not in fake_doc


def test_the_wer_figures_match_the_data() -> None:
    """The headline accuracy table — the most quoted numbers in the project.

    The first version of this test guessed at the JSON shape (`results` /
    `wer_pct`), found nothing, and *skipped* — passing while checking zero
    numbers. That is the same silent-hole failure the VAD drift was, so the key
    names are asserted rather than probed.
    """
    models = _results("wer")["models"]
    assert models, "wer.json records no models"
    text = _doc()

    for model, payload in models.items():
        wer = payload["wer"]
        assert f"{wer} %" in text or f"{wer}%" in text, (
            f"{model} measured {wer} % WER in paper/results/wer.json, and "
            f"docs/benchmarks.md does not say so"
        )


def test_the_wer_table_covers_every_measured_model() -> None:
    """A model measured but not published is a quieter drift than a wrong number,
    and the same kind of gap."""
    text = _doc()
    for model in _results("wer")["models"]:
        assert model in text, f"{model} was measured but never appears on the page"
