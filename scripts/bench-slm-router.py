#!/usr/bin/env python3
"""Synthetic accuracy benchmark for the Tier-2 SLM router, with and without the grammar.

Needs a local GGUF model and ``llama-cpp-python``; neither is a project dependency, and
nothing here downloads anything. Every utterance is generated from the templates below
-- no real user audio or transcript is involved -- so the numbers say how a model copes
with paraphrase, not how it copes with you. No result is committed: run it yourself.

    python scripts/bench-slm-router.py --model ~/models/qwen2.5-0.5b-instruct-q4.gguf

Scored per utterance: a paraphrased command is right when the router returns its
expected action; a prose sentence is right when the router returns nothing (it stays
dictation). Reports accuracy and median latency for each mode.
"""
from __future__ import annotations

import argparse
import itertools
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yazses.commands.slm_router import SLMRouter  # noqa: E402

# (template, expected action). "{x}" takes each filler in turn.
_COMMAND_TEMPLATES: list[tuple[str, str]] = [
    ("could you {x} save the file", "save"),
    ("{x} write my changes to disk", "save"),
    ("{x} take back what I just did", "undo"),
    ("{x} copy what I selected", "copy"),
    ("{x} drop the clipboard in here", "paste"),
    ("{x} highlight everything", "select_all"),
    ("{x} hit the enter key", "press_enter"),
    ("{x} scroll a page down", "page_down"),
    ("{x} scroll a page up", "page_up"),
    ("{x} kick off the test suite", "run_tests"),
    ("{x} start a build", "run_build"),
    ("{x} turn this line into a comment", "comment"),
    ("{x} jump to the start of the line", "line_home"),
    ("{x} jump to the end of this line", "line_end"),
    ("{x} cut that out", "cut"),
    ("{x} get rid of the last word", "delete_words"),
    ("{x} take me to line two hundred", "go_to_line"),
    ("{x} find the function called parse args", "go_to_function"),
    ("{x} open up the file named readme", "go_to_file"),
    ("{x} rename this symbol to total count", "rename_symbol"),
]
_COMMAND_FILLERS = ["", "please", "okay", "hey", "can you", "now", "go ahead and",
                    "quickly", "I'd like you to", "just"]

_PROSE_TEMPLATES = [
    "{x} the meeting moved to Thursday afternoon",
    "{x} we should save some money for the trip",
    "{x} I copied the recipe from my grandmother",
    "{x} the build quality of this chair is excellent",
    "{x} let's run through the slides one more time",
    "{x} she renamed her blog last spring",
    "{x} the tests at school were harder than expected",
    "{x} page twelve has a typo in the second paragraph",
    "{x} undo the knot carefully or the rope will fray",
    "{x} the line at the bakery was around the block",
    "{x} enter the building through the side door",
    "{x} he pasted the poster onto the wall",
    "{x} our class trip is on the first of May",
    "{x} the file cabinet in the hall is full",
    "{x} select a ripe avocado by pressing it gently",
    "{x} commenting on the draft took all morning",
    "{x} ignore the noise outside, it is only the wind",
    "{x} the function of the committee is to advise",
    "{x} cut the onions into thin slices",
    "{x} delete nothing until we have a backup",
]
_PROSE_FILLERS = ["", "honestly", "so", "anyway", "I think", "remember",
                  "by the way", "also", "well", "note that"]


def _expand(templates, fillers) -> list:
    out = []
    for item, filler in itertools.product(templates, fillers):
        template, label = item if isinstance(item, tuple) else (item, None)
        out.append((" ".join(template.format(x=filler).split()), label))
    return out


def _run(router: SLMRouter, cases: list) -> tuple[float, float]:
    right, times = 0, []
    for text, expected in cases:
        t0 = time.perf_counter()
        got = router.classify(text)
        times.append(time.perf_counter() - t0)
        right += (got is None) if expected is None else (got is not None and got.action == expected)
    return right / len(cases), statistics.median(times) * 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, help="path to a local GGUF model")
    ap.add_argument("--threshold", type=float, default=0.75)
    ns = ap.parse_args()

    commands = _expand(_COMMAND_TEMPLATES, _COMMAND_FILLERS)
    prose = _expand(_PROSE_TEMPLATES, _PROSE_FILLERS)
    router = SLMRouter(ns.model, threshold=ns.threshold)
    if not router.enabled:
        print("router disabled: model missing or llama-cpp-python not installed",
              file=sys.stderr)
        return 1

    grammar = router._grammar
    modes = [("grammar", grammar), ("no grammar", None)] if grammar is not None else [
        ("no grammar (binding has none)", None)]
    print(f"{len(commands)} synthetic commands, {len(prose)} synthetic prose sentences")
    for label, g in modes:
        router._grammar = g
        cmd_acc, cmd_ms = _run(router, commands)
        prose_acc, prose_ms = _run(router, prose)
        print(f"{label:>30}: commands {cmd_acc:6.1%} ({cmd_ms:.0f} ms median), "
              f"prose kept as dictation {prose_acc:6.1%} ({prose_ms:.0f} ms median)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
