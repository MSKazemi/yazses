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

**Where this runs — and why that changed.** `paper/results/*.json` used to be
gitignored, so it existed on the machine that ran the harness and nowhere else, CI
included. This module skipped when a results file was absent, and that skip was
honest: there was genuinely nothing to compare against.

The results are now committed (see `test_benchmark_results_are_archived.py`), which
turns the same skip into a hole. A file that is *supposed* to be in the checkout and
is not is a deleted artifact, not an absent environment — and a guard that skips on
it would report a green page whose numbers trace to nothing. So a missing result is
now a failure with a message saying which file, and the skip is gone. The first
version of the module went the other way and asserted presence while the files were
still ignored, turning every CI job on every OS red; both mistakes are the same one,
which is a guard assuming an environment instead of reading it.
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
    assert path.is_file(), (
        f"{path.relative_to(ROOT)} is missing. This file is committed -- every figure "
        "on the page is supposed to trace back to it -- so its absence means it was "
        "deleted, not that this checkout lacks an environment. Restore it or re-run "
        "the harness; do not restore the skip that used to hide this."
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_page_exists_and_quotes_numbers() -> None:
    """Guard the guard: a missing or numberless page makes everything below vacuous.

    Asserted on the page only. The results files are gitignored and legitimately
    absent in CI — requiring them here is what reddened every job.
    """
    assert DOC.is_file()
    assert re.search(r"\d+\.\d+\s*%", _doc()), "the page quotes no figures at all"
    # And the archive the page is checked against. Every assertion below reads a
    # results file; if the directory were empty they would all fail with the same
    # message, and this one says the real cause once.
    assert list(RESULTS.glob("*.json")), (
        "paper/results/ holds no archived result at all -- nothing on the page can "
        "be checked against anything"
    )


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


def _beam_rows() -> list[tuple[str, dict]]:
    """Every measured beam-size row, from every split that was archived.

    A *measurement* carries `rows`; an *analysis* of one -- `beam-test-clean-significance
    .json` and its `-vs-beam2` companion -- carries `comparisons` and lives beside it
    under the same prefix. Selecting on the filename alone swept those in and the reader
    died on a missing key, so the shape is what decides: a file with no `rows` is not a
    measurement of the table, and skipping it here is not a hole because
    `test_results_manifest_is_current` accounts for every file in the directory.
    """
    rows = []
    for path in sorted(RESULTS.glob("beam-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("rows", ()):
            rows.append((path.name, row))
    return rows


def test_the_beam_table_is_backed_by_an_archive() -> None:
    """Guard the guard. The beam section is prose plus a table; if the archive were
    absent the parametrized check below would collect zero cases and pass."""
    assert "beam_size" in _doc(), "the page no longer documents the beam-size sweep"
    assert _beam_rows(), (
        "docs/benchmarks.md publishes a beam-size table and paper/results/ holds no "
        "beam-*.json to check it against"
    )


@pytest.mark.parametrize(
    "source,row",
    _beam_rows(),
    ids=lambda x: x if isinstance(x, str) else f"{x['model']}-{x['split']}-beam{x['beam_size']}",
)
def test_every_measured_beam_row_is_published(source: str, row: dict) -> None:
    """A row measured and then left off the page is the quiet half of drift.

    Both figures, not just WER. The RTF column is the entire argument of that
    section -- that greedy decoding buys 11-16 %, not a category change -- and it is
    the column most likely to be quoted from an older run, because WER reproduces
    bit-for-bit across machines while RTF does not.
    """
    text = _doc()
    wer = row["wer_pct"]
    assert f"{wer} %" in text or f"{wer}%" in text, (
        f"{source} measured {wer} % WER for {row['model']} at beam={row['beam_size']} "
        f"on {row['split']}, and docs/benchmarks.md does not say so"
    )
    # RTF is written to four decimals by the harness and json drops trailing zeros,
    # so `0.031` and `0.0310` are the same measurement and either spelling counts.
    #
    # The lookahead is not decoration. A plain substring test passes `0.037` against
    # a page that says `0.0377` -- a different measurement, off by 2 % -- and it did:
    # one row of this table reported itself published while the page quoted the
    # figure from a different run. Any check on a decimal by substring has that hole.
    rtf = row["rtf"]
    pattern = rf"(?<![\d.]){re.escape(f'{rtf:.4f}'.rstrip('0'))}0*(?![\d])"
    assert re.search(pattern, text), (
        f"{source} measured RTF {rtf} for {row['model']} at beam={row['beam_size']} "
        f"on {row['split']}, and docs/benchmarks.md quotes a different figure"
    )


def test_a_beam_analysis_is_not_mistaken_for_a_beam_measurement() -> None:
    """Both live under `beam-*`, and only one has rows to check the table against.

    Asserted rather than left to the shape check above: if an analysis ever grew a
    `rows` key, its bootstrap comparisons would be silently checked against the
    published grid as though they were measured cells.
    """
    analyses = sorted(RESULTS.glob("beam-*significance*.json"))
    assert analyses, "the paired beam verdicts are gone from the archive"
    for path in analyses:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "rows" not in data, f"{path.name} looks like a measurement and is not"
        assert "comparisons" in data, f"{path.name} carries no comparisons"
    measured = {name for name, _ in _beam_rows()}
    assert measured, "no beam measurement left to check the table against"
    assert not (measured & {p.name for p in analyses})


# --- the large-v3 instability distribution --------------------------------------
#
# This table is the one place on the page where the *error breakdown* is the claim
# rather than colour on a WER. The headline -- substitutions, deletions and hits
# bit-identical across five decodes, insertions the only thing that moves -- is
# falsified by a single digit, and it is quoted in prose two paragraphs earlier as
# well ("101 to 184"). Checking WER alone would let the breakdown rot underneath a
# correct-looking summary.

LV3 = RESULTS / "probes" / "largev3-instability-test-other.json"


def _lv3_runs() -> list[dict]:
    if not LV3.is_file():
        return []
    return json.loads(LV3.read_text(encoding="utf-8"))["result"]["runs"]


def test_the_instability_table_is_backed_by_an_archive() -> None:
    """Guard the guard: no artifact means the parametrized check collects nothing."""
    assert "The distribution, measured" in _doc(), (
        "docs/benchmarks.md no longer carries the large-v3 distribution section"
    )
    assert _lv3_runs(), f"{LV3.relative_to(ROOT)} is missing or has no runs"


def _lv3_table() -> list[list[str]]:
    """The rows of the distribution table, as lists of stripped cells.

    Parsed rather than substring-matched, and the difference is not academic: every
    figure in this table is also quoted in the prose around it, so a page-wide
    `"5.46 %" in text` passes against a table cell that has drifted to 5.47 %. It
    was written that way first and a deliberate one-digit mutation went green.
    """
    lines = _doc().splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if "The distribution, measured" in ln)
    except StopIteration:
        return []
    rows = []
    for line in lines[start:]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and not set("".join(cells)) <= set("-: "):
                rows.append(cells)
        elif rows:
            break  # the table ended
    return rows


@pytest.mark.parametrize("run", _lv3_runs(), ids=lambda r: f"repeat{r.get('run')}")
def test_every_instability_repeat_is_published(run: dict) -> None:
    """Each measured repeat must appear as one *complete row*, not as five loose
    numbers scattered over the page. A row is the claim; the breakdown only means
    anything read across."""
    table = _lv3_table()
    assert table, "the distribution table is gone from docs/benchmarks.md"
    wanted = [
        f"{run['wer']} %",
        str(run["insertions"]),
        str(run["substitutions"]),
        str(run["deletions"]),
        str(run["hits"]),
    ]
    def matches(row: list[str]) -> bool:
        # Cells carry markdown emphasis on the extremes; compare on the digits.
        plain = [c.replace("*", "").strip() for c in row]
        return all(any(w == c for c in plain) for w in wanted)

    assert any(matches(row) for row in table), (
        f"repeat {run.get('run')} measured WER={run['wer']} % ins={run['insertions']} "
        f"sub={run['substitutions']} del={run['deletions']} hits={run['hits']}, and no "
        f"single row of the published table says that. Rows on the page: {table}"
    )


def test_the_published_identity_holds_for_every_run() -> None:
    """The page claims every WER is exactly ``(102 + insertions) / 3721``.

    That is not a rounding-tolerant summary but an arithmetic identity, and it is
    the whole reason the section can say the spread *is* the insertion count. If a
    future run moves a substitution the identity breaks, and the sentence asserting
    it becomes false while every individual number on the page stays correct --
    which is precisely the drift a per-figure check cannot see.
    """
    runs = _lv3_runs()
    assert runs, "no runs to check"
    reference_words = 3721
    constant = 102
    assert f"(102 + insertions) / {reference_words}" in _doc(), (
        "the page no longer states the identity this test exists to hold it to"
    )
    for run in runs:
        assert run["hits"] + run["substitutions"] + run["deletions"] == reference_words
        assert run["substitutions"] + run["deletions"] == constant
        derived = round((constant + run["insertions"]) / reference_words * 100, 2)
        assert derived == run["wer"], (
            f"repeat {run.get('run')}: (102 + {run['insertions']}) / {reference_words} "
            f"= {derived} %, but the run recorded {run['wer']} %"
        )


# --- the two AMI aggregates -----------------------------------------------------
#
# The page now quotes a corpus DER *and* a per-recording mean, one sentence apart,
# and says which to compare against published work. Getting those two the wrong way
# round is the exact error the sentence exists to prevent, and both figures are
# derivable from the same rows -- so both are checked against them, not against the
# summary block that could itself have drifted.

AMI = RESULTS / "diarization-ami16_corpus-der.json"


def test_both_ami_aggregates_are_published_and_derive_from_the_rows() -> None:
    assert AMI.is_file(), f"{AMI.relative_to(ROOT)} is missing"
    data = json.loads(AMI.read_text(encoding="utf-8"))
    rows, summary = data["meetings"], data["summary"]
    text = _doc()

    mean = round(sum(r["strict"]["der"] for r in rows) / len(rows), 2)
    assert mean == summary["der_strict"], (
        f"the summary's per-recording mean ({summary['der_strict']}) is not the mean "
        f"of its own rows ({mean})"
    )

    scored = sum(r["strict"]["scored_seconds"] for r in rows)
    weighted = round(
        sum(r["strict"]["der"] / 100 * r["strict"]["scored_seconds"] for r in rows)
        / scored * 100, 2)
    assert weighted == summary["der_strict_time_weighted"], (
        f"the summary's time-weighted DER ({summary['der_strict_time_weighted']}) is "
        f"not Σ(error time)/Σ(scored time) over its own rows ({weighted})"
    )

    for value in (summary["der_strict"], summary["der_strict_time_weighted"],
                  summary["der_collar250ms_time_weighted"]):
        assert f"{value} %" in text or f"{value}%" in text, (
            f"{value} is measured and docs/benchmarks.md does not quote it"
        )


def test_the_page_says_which_aggregate_to_compare_with_the_literature() -> None:
    """Publishing two DERs without saying which is which is worse than one.

    A reader placing the per-recording mean beside a published AMI table is
    comparing two different quantities and cannot tell -- the numbers are only
    0.66 points apart here, which is small enough to look like agreement.
    """
    text = _doc()
    assert "time-weighted" in text
    assert "md-eval" in text.lower(), "the page must name the reference scorer"
