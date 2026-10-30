#!/usr/bin/env python3
"""Coverage-guided fuzzing of the XR companion wire decoder, against a "only WireError" contract.

Run:  python fuzz/fuzz_xr_wire.py -atheris_runs=200000

`yazses.xr.wire.decode_frame` reads bytes that arrive from a *separate device on a
network link* (the headset or phone companion), so every frame is hostile input. Its
documented contract is total in one precise sense: whatever is wrong with a frame, the
decoder raises `WireError` and **nothing else**; the caller drops the frame and counts
it. Any other exception (`KeyError`, `TypeError`, `RecursionError`, `OverflowError`, a
bare `ValueError` from a constructor, `UnicodeError`...) is a defect: it would escape
into the receive loop and kill the session on one malformed packet.

The oracle is exact, so the harness restates it and nothing more:

* `decode_frame` returns a frame or raises `WireError`;
* an accepted frame survives `encode_frame` -> `decode_frame` unchanged (the decoder
  only ever returns values its own encoder can reproduce exactly);
* both `bytes` and `str` front doors obey the same rule.

⚠ The project modules are imported inside `atheris.instrument_imports()`, in `_load()`,
and NOT at the top of this file -- a module already in `sys.modules` when that context
manager opens is never instrumented, and libFuzzer then searches uniformly at random
while exiting 0 and looking exactly like a fuzzer that found nothing. See the same note
in `fuzz_text_pipeline.py`.
"""

from __future__ import annotations

import sys
from typing import Any

_LOADED: dict[str, Any] = {}

# Valid frames, one per frame type, kept here (not in fuzz/corpus/) so the ordinary
# pytest in tests/test_xr_properties.py can mutate the very same seeds.
SEED_FRAMES: tuple[bytes, ...] = (
    b'{"v":1,"t":"sample","device_time_s":12.5,"source":"eye",'
    b'"origin":[0,1.6,0],"direction":[0,0,-1],"confidence":0.9}',
    b'{"v":1,"t":"gesture","device_time_s":12.6,"kind":"pinch_start","confidence":1}',
    b'{"v":1,"t":"panel","panel_id":"p1","center":[0,1.5,-2],"normal":[0,0,1],'
    b'"up":[0,1,0],"width":1.2,"height":0.8,"label":"notes"}',
    b'{"v":1,"t":"panel_gone","panel_id":"p1"}',
)


def _load() -> dict[str, Any]:
    """Import the decoder. Must be called inside `atheris.instrument_imports()`."""
    if not _LOADED:
        from yazses.xr.wire import WireError, decode_frame, encode_frame

        _LOADED.update(WireError=WireError, decode_frame=decode_frame, encode_frame=encode_frame)
    return _LOADED


def one_input(raw: bytes) -> None:
    """Decode *raw* as a frame. Raises only if the totality contract is broken."""
    p = _load()
    wire_error = p["WireError"]
    decode_frame = p["decode_frame"]

    frame = None
    try:
        frame = decode_frame(raw)
    except wire_error:
        pass  # the one allowed outcome besides success

    # The text front door has the same contract. A str that is not valid UTF-8 (lone
    # surrogates) must also be a WireError, not a UnicodeEncodeError.
    try:
        text = raw.decode("utf-8", errors="surrogateescape")
    except UnicodeDecodeError:  # pragma: no cover - surrogateescape never raises
        return
    try:
        decode_frame(text)
    except wire_error:
        pass

    if frame is not None:
        again = decode_frame(p["encode_frame"](frame))
        if again != frame:  # pragma: no cover - a real defect if it ever fires
            raise AssertionError(f"decode(encode(decode(x))) != decode(x): {frame!r} vs {again!r}")


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
