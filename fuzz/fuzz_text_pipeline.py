#!/usr/bin/env python3
"""Coverage-guided fuzzing of everything between the decoder and the keyboard.

Run:  python fuzz/fuzz_text_pipeline.py -atheris_runs=200000

The invariant under test is narrow and load-bearing: **no transcript may raise.**
`core/daemon.py::_on_hold_end` calls this chain inside the hot path of a key release,
and an exception there is a dictation session that stops mid-sentence with the user
still holding the key. The functions are pure, so the oracle can be exact rather than
statistical -- there is no state to make a crash "sometimes".

Two further properties are checked because a silent violation of either is worse than
a crash: the cleaner must return a `str` (a `None` reaching the injector types the word
"None"), and classification must return an intent rather than `None` (the dispatcher
branches on `.intent` and would raise one frame later, where the traceback no longer
names the input).

⚠ The project modules are imported inside `atheris.instrument_imports()`, in `_load()`,
and NOT at the top of this file. That is not style. Atheris instruments a module as it
is imported, by hooking the import machinery; a module already in `sys.modules` when
the context manager opens is never instrumented, so libFuzzer gets an empty coverage
map and degrades to uniform random input while reporting nothing worse than

    WARNING: no interesting inputs were found so far. Is the code instrumented?

A blind fuzzer still runs, still exits 0, and still looks in every summary exactly like
a fuzzer that searched properly and found nothing -- which is the worst failure mode a
check can have. `-print_final_stats=1` in the CI job is there so the corpus growth is
visible rather than assumed.
"""

from __future__ import annotations

import sys
from typing import Any

# The grammars are per-editor and each carries its own rule set, so fuzzing only the
# default profile would leave most of the regexes unreached.
PROFILES = ("default", "vim", "emacs", "vscode")

_LOADED: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    """Import the pipeline. Must be called inside `atheris.instrument_imports()`."""
    if not _LOADED:
        from yazses.commands.grammar import classify
        from yazses.config import DisfluencyConfig
        from yazses.postprocess.cleaner import clean_text
        from yazses.postprocess.voice_punctuation import apply_voice_punctuation
        from yazses.stt.filters.disfluency import filter_transcript

        _LOADED.update(
            classify=classify,
            disfluency_config=DisfluencyConfig(),
            clean_text=clean_text,
            apply_voice_punctuation=apply_voice_punctuation,
            filter_transcript=filter_transcript,
        )
    return _LOADED


def one_input(text: str) -> None:
    """The pipeline, in the order `_on_hold_end` runs it. Raises what it raises."""
    p = _load()

    cleaned = p["clean_text"](text)
    if not isinstance(cleaned, str):  # pragma: no cover - the assertion is the point
        raise TypeError(f"clean_text returned {type(cleaned).__name__}, not str")

    filtered = p["filter_transcript"](cleaned, p["disfluency_config"])
    if not isinstance(filtered.text, str):  # pragma: no cover
        raise TypeError(f"filter_transcript returned {type(filtered.text).__name__}")

    punctuated = p["apply_voice_punctuation"](filtered.text)
    if not isinstance(punctuated, str):  # pragma: no cover
        raise TypeError(f"apply_voice_punctuation returned {type(punctuated).__name__}")

    for profile in PROFILES:
        intent = p["classify"](punctuated, profile)
        if intent is None:  # pragma: no cover
            raise TypeError(f"classify returned None for profile {profile!r}")


def test_one_input(data: bytes) -> None:
    """Atheris entry point.

    `errors="surrogatepass"` rather than `"replace"`: a decoder can and does emit lone
    surrogates, and replacing them here would fuzz a sanitised string the daemon never
    sees. The whole point is to hand the pipeline what actually reaches it.
    """
    try:
        text = data.decode("utf-8", errors="surrogatepass")
    except UnicodeDecodeError:
        return
    one_input(text)


def main() -> int:
    import atheris  # noqa: PLC0415 - optional, Linux/x86_64 only; see fuzz/README.md

    # `include=["yazses"]` keeps the coverage map to this project's own branches.
    # Instrumenting `re` and the standard library fills it with edges the fuzzer cannot
    # act on and slows every execution.
    with atheris.instrument_imports(include=["yazses"]):
        _load()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
