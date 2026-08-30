#!/usr/bin/env python3
"""Coverage-guided fuzzing of config loading, against a contract that says "never".

Run:  python fuzz/fuzz_config.py -atheris_runs=200000

`load_config` has the strongest oracle in the codebase: issue #52 makes loading
**total**. No config file, however malformed, may prevent the daemon starting -- a
truncated write, a UTF-16 save, a byte-order mark, a value of the wrong type, an
unknown section, unparseable TOML: each becomes a `ConfigProblem` the daemon lists at
startup, never an exception. `configcheck.py` repairs what it can (`"0.004"` -> `0.004`)
and falls back to the documented default otherwise.

That is a promise about *all* inputs, which is precisely the shape a coverage-guided
fuzzer can attack and a hand-written test cannot. Every assertion here is the contract
restated: it never raises, and it always returns a usable `Config` with the right types
on the fields the daemon reads before it has finished starting.

⚠ The project modules are imported inside `atheris.instrument_imports()`, in `_load()`,
and NOT at the top of this file -- a module already in `sys.modules` when that context
manager opens is never instrumented, and libFuzzer then searches uniformly at random
while exiting 0 and looking exactly like a fuzzer that found nothing. See the same note
in `fuzz_text_pipeline.py`.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
from typing import Any

_LOADED: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    """Import the loaders. Must be called inside `atheris.instrument_imports()`."""
    if not _LOADED:
        from yazses.config import load_config, load_config_checked
        from yazses.system.vocabulary import parse_vocab
        from yazses.tomlio import loads as toml_loads

        _LOADED.update(
            load_config=load_config,
            load_config_checked=load_config_checked,
            parse_vocab=parse_vocab,
            toml_loads=toml_loads,
        )
    return _LOADED


def one_input(raw: bytes) -> None:
    """Load *raw* as a config file. Raises only if the totality contract is broken."""
    p = _load()
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "config.toml"
        path.write_bytes(raw)

        loaded = p["load_config_checked"](path)
        config = loaded.config

        # The fields the daemon reads before it can report anything to anyone. A wrong
        # type here is not a config problem, it is a crash three frames later in a
        # place that no longer knows which key caused it.
        if not isinstance(config.stt.model, str):  # pragma: no cover
            raise TypeError(f"stt.model is {type(config.stt.model).__name__}")
        if not isinstance(config.hotkey.key, str):  # pragma: no cover
            raise TypeError(f"hotkey.key is {type(config.hotkey.key).__name__}")
        if not isinstance(config.accessibility.vad_threshold, (int, float)):  # pragma: no cover
            raise TypeError("accessibility.vad_threshold is not a number")

        # The plain loader is what the daemon actually calls, and it has the same
        # promise with none of the reporting. Fuzz it too rather than assuming the
        # checked wrapper is the only path.
        p["load_config"](path)

    # Two smaller loaders on the same file bytes, for the same reason: a hand-edited
    # file arrives through a foreign editor's encoding, and neither of these may raise
    # into the daemon either.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        p["toml_loads"](text)
    except ValueError:
        # A real syntax error IS reportable here -- `tomlio.loads` widens what parses,
        # it does not widen what is accepted. `UnicodeDecodeError` is a `ValueError`.
        pass
    p["parse_vocab"](text)


def test_one_input(data: bytes) -> None:
    one_input(data)


def main() -> int:
    import atheris  # noqa: PLC0415 - optional, Linux/x86_64 only; see fuzz/README.md

    with atheris.instrument_imports(include=["yazses"]):
        _load()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
