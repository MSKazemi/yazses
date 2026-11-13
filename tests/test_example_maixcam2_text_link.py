"""Guards for the device-free TextLink reference under ``examples/maixcam2-text-link/``.

The example is a research artifact (ADR-030 freezes new capabilities): a wire codec, a
simulated board and a host reader for a text string sent by a MaixCAM2 board over a
UART. No board exists in this repository, so what these tests prove is limited to what
a PC can prove: the codec matches independently computed vectors, the parser is
chunking-invariant and survives damage, text from the wire is refused when hostile,
and the example is isolated from the product (nothing imports it, it imports nothing
outside the standard library, it never types and never opens a socket).

The modules are loaded by path; the example folder is not put on ``sys.path``.
"""

from __future__ import annotations

import ast
import binascii
import importlib.util
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import types
import unicodedata
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "maixcam2-text-link"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


tl = _load("_test_maixcam2_textlink", EXAMPLE / "textlink.py")
sim = _load("_test_maixcam2_simulated_board", EXAMPLE / "simulated_board.py")
reader = _load("_test_maixcam2_host_reader", EXAMPLE / "host_reader.py")
board = _load("_test_maixcam2_maixpy_send", EXAMPLE / "board" / "maixpy_send.py")


def parse_all(chunks: list[bytes]) -> tuple[list[tl.Frame], dict[str, int]]:
    parser = tl.FrameParser()
    frames: list[tl.Frame] = []
    for chunk in chunks:
        frames += parser.feed(chunk)
    return frames, parser.stats()


# -- CRC and golden vectors -----------------------------------------------------------


def _bitwise_crc(data: bytes) -> int:
    """CRC-16/CCITT-FALSE, written bit by bit, independent of the table in textlink."""
    crc = 0xFFFF
    for byte in data:
        for bit in range(7, -1, -1):
            top = (crc >> 15) & 1
            crc = (crc << 1) & 0xFFFF
            if top ^ ((byte >> bit) & 1):
                crc ^= 0x1021
    return crc


def test_crc_standard_check_value():
    assert tl.crc16_ccitt_false(b"123456789") == 0x29B1
    assert tl.crc16_ccitt_false(b"") == 0xFFFF


def test_crc_agrees_with_two_independent_implementations():
    rng = random.Random(1)
    for _ in range(200):
        data = rng.randbytes(rng.randrange(0, 80))
        assert tl.crc16_ccitt_false(data) == _bitwise_crc(data) == binascii.crc_hqx(data, 0xFFFF)


def test_crc_can_be_continued():
    assert tl.crc16_ccitt_false(b"6789", tl.crc16_ccitt_false(b"12345")) == 0x29B1


# Each vector's CRC was cross-checked with binascii.crc_hqx and the bitwise function above.
GOLDEN = [
    ("hello seq 0", tl.FrameType.TEXT, 0, b"hello", "59 53 01 01 00 00 05 68 65 6c 6c 6f e5 3c"),
    ("trigger seq 1", tl.FrameType.TRIGGER, 1, b"", "59 53 01 02 01 00 00 61 05"),
    ("ping seq 255", tl.FrameType.PING, 255, b"", "59 53 01 03 ff 00 00 ef e2"),
    ("ping seq 0", tl.FrameType.PING, 0, b"", "59 53 01 03 00 00 00 20 81"),
    (
        "chinese seq 7",
        tl.FrameType.TEXT,
        7,
        "你好，世界".encode(),
        "59 53 01 01 07 00 0f e4 bd a0 e5 a5 bd ef bc 8c e4 b8 96 e7 95 8c 37 61",
    ),
    (
        "accent seq 255",
        tl.FrameType.TEXT,
        255,
        "Café".encode(),
        "59 53 01 01 ff 00 05 43 61 66 c3 a9 2c c2",
    ),
]


@pytest.mark.parametrize(("label", "ftype", "seq", "payload", "hexstr"), GOLDEN)
def test_golden_vectors(label, ftype, seq, payload, hexstr):
    wire = bytes.fromhex(hexstr)
    assert tl.encode(ftype, seq, payload) == wire
    assert int.from_bytes(wire[-2:], "big") == _bitwise_crc(wire[2:-2])
    frames, stats = parse_all([wire])
    assert [(f.type, f.seq, f.payload) for f in frames] == [(ftype, seq, payload)]
    assert stats["frames_ok"] == 1 and stats["resync_bytes"] == 0


def test_encode_text_matches_golden_and_normalises():
    assert tl.encode_text("hello", 0) == bytes.fromhex(GOLDEN[0][4])
    assert tl.encode_text("  hello  ", 0) == tl.encode_text("hello", 0)
    assert tl.encode_text("é", 0) == tl.encode_text("é", 0)


def test_encoder_refuses_what_the_wire_cannot_carry():
    with pytest.raises(ValueError):
        tl.encode(0x7F, 0)
    with pytest.raises(ValueError):
        tl.encode(tl.FrameType.TEXT, 256)
    with pytest.raises(ValueError):
        tl.encode(tl.FrameType.TEXT, 0, b"")
    with pytest.raises(ValueError):
        tl.encode(tl.FrameType.PING, 0, b"x")
    with pytest.raises(ValueError):
        tl.encode(tl.FrameType.TEXT, 0, b"a" * 513)
    assert len(tl.encode(tl.FrameType.TEXT, 0, b"a" * 512)) == tl.MAX_FRAME_LEN
    with pytest.raises(tl.InvalidText):
        tl.encode_text("two\nlines", 0)


# -- round trip -----------------------------------------------------------------------

_SAFE_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cc", "Cf", "Cs", "Cn"),
        blacklist_characters=[
            "\u2028",
            "\u2029",
            "\ufffd",
            "\u2800",
            "\u3164",
            "\uffa0",
            "\u115f",
            "\u1160",
        ],
    ),
    min_size=1,
    max_size=60,  # NFC can double a character, and the post-NFC text is capped at 512 bytes
).filter(lambda s: _has_visible_content(unicodedata.normalize("NFC", s)))


def _has_visible_content(text: str) -> bool:
    return any(unicodedata.category(c)[0] in "LNPS" for c in text)


@settings(max_examples=150, deadline=None)
@given(_SAFE_TEXT, st.integers(0, 255))
def test_round_trip_property(text, seq):
    expected = unicodedata.normalize("NFC", text).strip()
    wire = tl.encode_text(text, seq)
    frames, stats = parse_all([wire])
    assert [(f.seq, f.text) for f in frames] == [(seq, expected)]
    assert stats["frames_ok"] == 1 and sum(v for k, v in stats.items() if k != "frames_ok") == 0


# -- chunk-boundary invariance --------------------------------------------------------


@pytest.mark.parametrize("scenario", sim.SCENARIOS, ids=lambda s: s.name)
def test_scenario_expectations(scenario):
    texts: list[tuple[int, str]] = []
    parser = tl.FrameParser()
    for event in scenario.events:
        texts += reader.process(parser, event.data)
    want_counters = {k: 0 for k in tl.FrameParser.COUNTERS} | dict(scenario.expected_counters)
    assert texts == list(scenario.expected_texts)
    assert parser.stats() == want_counters


@pytest.mark.parametrize("scenario", sim.SCENARIOS, ids=lambda s: s.name)
def test_every_split_point_gives_the_same_result(scenario):
    stream = scenario.stream
    whole = parse_all([stream])
    for i in range(len(stream) + 1):
        assert parse_all([stream[:i], stream[i:]]) == whole, f"split at {i}"


@pytest.mark.parametrize("scenario", sim.SCENARIOS, ids=lambda s: s.name)
@pytest.mark.parametrize("size", [1, 2, 5])
def test_fixed_size_chunks_give_the_same_result(scenario, size):
    assert parse_all(sim.chunked(scenario.stream, size)) == parse_all([scenario.stream])


@settings(max_examples=120, deadline=None)
@given(
    parts=st.lists(
        st.one_of(
            st.binary(max_size=40),
            st.builds(
                tl.encode_text,
                st.sampled_from(["hi", "你好", "Café", "ok go"]),
                st.integers(0, 255),
            ),
            st.builds(tl.encode, st.sampled_from([2, 3]), st.integers(0, 255)),
        ),
        max_size=12,
    ),
    cuts=st.lists(st.integers(1, 30), min_size=1, max_size=8),
)
def test_arbitrary_streams_are_chunking_invariant(parts, cuts):
    stream = b"".join(parts)
    chunks: list[bytes] = []
    pos, i = 0, 0
    while pos < len(stream):
        step = cuts[i % len(cuts)]
        chunks.append(stream[pos : pos + step])
        pos, i = pos + step, i + 1
    assert parse_all(chunks) == parse_all([stream])


@settings(max_examples=100, deadline=None)
@given(st.binary(max_size=2000))
def test_parser_never_raises_and_buffer_stays_bounded(data):
    parser = tl.FrameParser()
    parser.feed(data)
    assert parser.buffered <= tl.MAX_FRAME_LEN


# -- resynchronisation, damage and refusals -------------------------------------------


def test_garbage_then_frames_resynchronises():
    garbage = bytes(range(0x80, 0xA0)) + b"YYY"
    frames, stats = parse_all([garbage + tl.encode_text("ok", 0)])
    assert [f.text for f in frames] == ["ok"]
    assert stats["resync_bytes"] == len(garbage)


def test_sync_split_across_chunks():
    wire = tl.encode_text("split sync", 0)
    frames, stats = parse_all([b"junk" + wire[:1], wire[1:]])
    assert [f.text for f in frames] == ["split sync"]
    assert stats["resync_bytes"] == 4


def test_multibyte_character_split_across_chunks():
    text = "漢字 café 😀"
    wire = tl.encode_text(text, 0)
    for size in (1, 2, 3):
        frames, stats = parse_all(sim.chunked(wire, size))
        assert [f.text for f in frames] == [text]
        assert stats["invalid_text"] == 0


def test_truncated_frame_does_not_swallow_the_next_ones():
    cut = tl.encode_text("a long sentence that is cut off mid way", 0)[:15]
    # The dead frame claims 48 bytes, so the parser waits until 48 bytes have arrived
    # (it cannot know the frame is dead sooner), then drops one byte and rescans.
    followers = b"".join(
        tl.encode_text(w, i + 1) for i, w in enumerate(["one", "two", "three", "four"])
    )
    frames, stats = parse_all([cut + followers])
    assert [f.text for f in frames] == ["one", "two", "three", "four"]
    assert stats["bad_crc"] == 1


def test_flush_partial_recovers_frames_behind_a_dead_one_without_more_input():
    cut = tl.encode_text("a long sentence that is cut off mid way", 0)[:15]
    parser = tl.FrameParser()
    assert parser.feed(cut + tl.encode_text("one", 1)) == []  # still waiting for the long frame
    assert parser.buffered > 0
    frames = parser.flush_partial()
    assert [f.text for f in frames] == ["one"]
    assert parser.buffered == 0
    assert parser.flush_partial() == []


def test_bad_crc_every_single_bit_flip_is_detected():
    wire = tl.encode_text("integrity", 3)
    for byte in range(2, len(wire)):  # SYNC bytes excluded: a flip there is just noise
        for bit in range(8):
            damaged = bytearray(wire)
            damaged[byte] ^= 1 << bit
            frames, _ = parse_all([bytes(damaged)])
            assert frames == [], f"flip byte {byte} bit {bit} was accepted"


def test_oversize_length_is_not_waited_for():
    header = b"YS\x01\x01\x00\xff\xff"  # LEN 65535
    parser = tl.FrameParser()
    parser.feed(header)
    assert parser.oversize == 1 and parser.buffered <= 1
    assert [f.text for f in parser.feed(tl.encode_text("next", 1))] == ["next"]


def test_unknown_frame_type_is_counted_and_ignored():
    body = bytes((1, 0x7E, 0)) + (3).to_bytes(2, "big") + b"abc"
    wire = b"YS" + body + tl.crc16_ccitt_false(body).to_bytes(2, "big")
    frames, stats = parse_all([wire + tl.encode_text("after", 1)])
    assert [f.text for f in frames] == ["after"]
    assert stats["unknown_type"] == 1 and stats["resync_bytes"] == 0


HOSTILE = {
    "newline": "a\nb",
    "carriage return": "a\rb",
    "tab": "a\tb",
    "nul": "a\x00b",
    "escape": "\x1b[2Jx",
    "del": "a\x7fb",
    "c1 nel": "a\u0085b",
    "c1 csi": "a\u009bb",
    "line separator": "a b",
    "paragraph separator": "a b",
    "lrm": "a‎b",
    "rlm": "a‏b",
    "alm": "a؜b",
    "lre": "a‪b",
    "rle": "a‫b",
    "pdf": "a‬b",
    "lro": "a‭b",
    "rlo": "a‮b",
    "lri": "a⁦b",
    "rli": "a⁧b",
    "fsi": "a⁨b",
    "pdi": "a⁩b",
    "blank": "   ",
    "zero width space": "a\u200bb",
    "word joiner": "a\u2060b",
    "bom": "a\ufeffb",
    "soft hyphen": "a\u00adb",
    "tag character": "a\U000e0041b",
    "deprecated format 206a": "a\u206ab",
    "annotation anchor": "a\ufff9b",
    "noncharacter fffe": "a\ufffeb",
    "noncharacter ffff": "a\uffffb",
    "replacement character": "a\ufffdb",
    "braille blank": "a\u2800b",
    "hangul filler": "a\u3164b",
    "halfwidth hangul filler": "a\uffa0b",
    "hangul choseong filler": "a\u115fb",
    "hangul jungseong filler": "a\u1160b",
    "zwnj alone": "\u200c",
    "zwj alone": "\u200d",
    "zwnj between digits": "1\u200c2",
    "zwj emoji sequence without a letter": "\U0001f468\u200d\U0001f469",
    "lone combining mark": "\u0301",
    "combining marks and spaces": " \u0301 \u0308 ",
    "zero width space only": "\u200b",
    "tag characters only": "\U000e0041\U000e0042",
    "nbsp only": "  ",
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_hostile_text_is_refused_and_counted(name):
    payload = HOSTILE[name].encode()
    frames, stats = parse_all(
        [tl.encode(tl.FrameType.TEXT, 0, payload) + tl.encode_text("fine", 1)]
    )
    assert [f.text for f in frames] == ["fine"]
    assert stats["invalid_text"] == 1


@pytest.mark.parametrize(
    "payload", [b"\xff", b"\xc0\xaf", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"ok\xe4\xbd"]
)
def test_invalid_utf8_is_refused_and_counted(payload):
    frames, stats = parse_all([tl.encode(tl.FrameType.TEXT, 0, payload)])
    assert frames == [] and stats["invalid_text"] == 1


def test_text_is_nfc_normalised_and_stripped_and_zwnj_survives():
    raw = tl.encode(tl.FrameType.TEXT, 0, "  école  ".encode())
    frames, _ = parse_all([raw])
    assert frames[0].text == "école"
    persian = "می‌خواهم"
    assert parse_all([tl.encode_text(persian, 0)])[0][0].text == persian


def test_decode_text_reasons():
    reasons = {}
    for payload in (b"a\nb", "a b".encode(), "a‮b".encode(), b"\xff", b"  "):
        with pytest.raises(tl.InvalidText) as info:
            tl.decode_text(payload)
        reasons[payload] = info.value.reason
    assert list(reasons.values()) == ["control", "separator", "bidi", "utf8", "empty"]


# -- counters, SEQ --------------------------------------------------------------------


def test_seq_wraps_255_to_0_without_a_gap():
    wire = b"".join(tl.encode_text(f"n{i}", i & 0xFF) for i in range(250, 262))
    frames, stats = parse_all([wire])
    assert [f.seq for f in frames] == [250, 251, 252, 253, 254, 255, 0, 1, 2, 3, 4, 5]
    assert stats["seq_gaps"] == 0


def test_seq_gap_is_measured_and_text_is_kept():
    frames, stats = parse_all([tl.encode_text("a", 10) + tl.encode_text("b", 14)])
    assert [f.text for f in frames] == ["a", "b"]
    assert [f.seq_skipped for f in frames] == [0, 3]
    assert stats["seq_gaps"] == 1


def test_identical_consecutive_frames_are_both_delivered_and_counted():
    wire = tl.encode_text("same", 4) * 2 + tl.encode_text("next", 5)
    frames, stats = parse_all([wire])
    assert [f.text for f in frames] == ["same", "same", "next"]
    assert [f.seq_repeat for f in frames] == [False, True, False]
    assert stats["seq_repeats"] == 1 and stats["seq_gaps"] == 0
    assert "duplicates" not in stats
    assert reader.process(tl.FrameParser(), wire) == [(4, "same"), (4, "same"), (5, "next")]


def test_reboot_is_one_discontinuity_not_a_loss_of_text():
    wire = tl.encode_text("x", 8) + tl.encode_text("y", 0)
    frames, stats = parse_all([wire])
    assert [f.text for f in frames] == ["x", "y"]
    assert stats["seq_gaps"] == 1


def test_ping_and_trigger_carry_no_text():
    frames, _ = parse_all([tl.encode(tl.FrameType.PING, 0) + tl.encode(tl.FrameType.TRIGGER, 1)])
    assert [(f.type, f.text) for f in frames] == [
        (tl.FrameType.PING, None),
        (tl.FrameType.TRIGGER, None),
    ]
    assert reader.process(tl.FrameParser(), tl.encode(tl.FrameType.TRIGGER, 0)) == []


# -- rate limiter ---------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_drops_excess_and_refills():
    clock = _Clock()
    limiter = tl.RateLimiter(2.0, clock=clock)
    assert [limiter.allow() for _ in range(4)] == [True, True, False, False]
    assert limiter.dropped == 2
    clock.now += 0.5  # one token at 2/s
    assert limiter.allow() is True and limiter.allow() is False
    clock.now += 60.0  # refill is capped at the bucket size
    assert [limiter.allow() for _ in range(3)] == [True, True, False]


def test_rate_limiter_one_per_second_and_validation():
    clock = _Clock()
    limiter = tl.RateLimiter(1.0, clock=clock)
    assert limiter.allow() and not limiter.allow()
    clock.now += 1.0
    assert limiter.allow()
    with pytest.raises(ValueError):
        tl.RateLimiter(0)
    with pytest.raises(ValueError):
        tl.RateLimiter(1.0, burst=0)


def test_reader_applies_rate_limit_to_text_only():
    clock = _Clock()
    limiter = tl.RateLimiter(1.0, clock=clock)
    wire = b"".join(tl.encode_text(f"t{i}", i) for i in range(3)) + tl.encode(tl.FrameType.PING, 3)
    assert reader.process(tl.FrameParser(), wire, limiter) == [(0, "t0")]
    assert limiter.dropped == 2


# -- bounded memory -------------------------------------------------------------------


def test_ten_megabytes_of_garbage_stays_bounded():
    rng = random.Random(7)
    block = bytes(b for b in rng.randbytes(65536) if b != 0x59)  # no 'Y': never a SYNC
    parser = tl.FrameParser()
    peak = 0
    total = 0
    for _ in range(160):  # ~10 MB
        parser.feed(block)
        total += len(block)
        peak = max(peak, parser.buffered)
    assert peak <= tl.MAX_FRAME_LEN
    assert parser.resync_bytes + parser.buffered == total
    assert parser.feed(tl.encode_text("still alive", 0))[0].text == "still alive"


def test_adversarial_sync_spam_is_linear_and_bounded():
    parser = tl.FrameParser()
    spam = (b"YS\x01\x01\x00\x02\x01" + b"YS") * 20000  # oversize headers, back to back
    parser.feed(spam)
    assert parser.buffered <= tl.MAX_FRAME_LEN
    assert parser.oversize == 20000


def test_one_huge_chunk_does_not_balloon_the_buffer():
    parser = tl.FrameParser()
    parser.feed(b"\x00" * (3 * 1024 * 1024))
    assert parser.buffered == 0


# -- host reader ----------------------------------------------------------------------


def test_reader_selftest_passes(capsys):
    assert reader.selftest() == 0
    assert "selftest ok" in capsys.readouterr().out


def test_reader_selftest_fails_loudly_on_a_wrong_expectation():
    wrong = sim.Scenario("wrong", "x", sim.SCENARIOS[0].events, (), {})
    out = io.StringIO()
    assert reader.selftest(out, [wrong]) == 1
    assert "SELFTEST FAIL wrong" in out.getvalue()


def test_reader_selftest_cli_exit_code():
    done = subprocess.run(
        [sys.executable, str(EXAMPLE / "host_reader.py"), "--selftest"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "selftest ok" in done.stdout


def test_reader_replay_prints_json_lines(tmp_path):
    capture = tmp_path / "capture.bin"
    capture.write_bytes(sim.SCENARIO_BY_NAME["multibyte_split"].stream)
    out, err = io.StringIO(), io.StringIO()
    reader.run(reader.iter_file(str(capture)), out, err, rate=None)
    lines = out.getvalue().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"seq": s, "text": t} for s, t in sim.SCENARIO_BY_NAME["multibyte_split"].expected_texts
    ]
    assert all(line.isascii() for line in lines)  # ensure_ascii: the output line is inert
    assert "frames_ok" in err.getvalue()


def test_reader_replay_cli(tmp_path):
    capture = tmp_path / "hostile.bin"
    capture.write_bytes(sim.SCENARIO_BY_NAME["hostile"].stream)
    n_hostile = sim.SCENARIO_BY_NAME["hostile"].expected_texts[0][0]
    done = subprocess.run(
        [sys.executable, str(EXAMPLE / "host_reader.py"), "--replay", str(capture)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert [json.loads(line) for line in done.stdout.splitlines()] == [
        {"seq": n_hostile, "text": "safe text after the hostile ones"}
    ]
    assert f'"invalid_text": {n_hostile}' in done.stderr


def test_reader_cli_argument_errors(capsys):
    with pytest.raises(SystemExit) as info:
        reader.main([])
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        reader.main(["/dev/null", "--replay", "x.bin"])
    assert info.value.code == 2
    assert reader.main(["--replay", "/nonexistent/x.bin"]) == 2
    assert "host_reader:" in capsys.readouterr().err


def test_reader_idle_tick_recovers_a_stalled_frame():
    cut = tl.encode_text("a long sentence that is cut off mid way", 0)[:15]
    source = iter([cut + tl.encode_text("one", 1), None])
    out, err = io.StringIO(), io.StringIO()
    reader.run(source, out, err, rate=None)
    assert [json.loads(line)["text"] for line in out.getvalue().splitlines()] == ["one"]


# -- pseudo-terminal ------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals are POSIX only")
@pytest.mark.timeout(30)
def test_pty_end_to_end():
    names = ["clean", "multibyte_split", "hostile", "ping_heartbeats"]
    chosen = [sim.SCENARIO_BY_NAME[n] for n in names]
    ready = threading.Event()
    path: list[str] = []

    def on_ready(p: str) -> None:
        path.append(p)
        ready.set()

    server = threading.Thread(
        target=sim.serve_pty,
        args=(chosen,),
        kwargs={"delay_scale": 0.0, "linger_s": 0.5, "on_ready": on_ready, "out": io.StringIO()},
        daemon=True,
    )
    server.start()
    assert ready.wait(10)
    out, err = io.StringIO(), io.StringIO()
    reader.run(
        reader.iter_device(path[0], idle_s=0.2),
        out,
        err,
        rate=None,
        idle_exit_s=0.4,
        idle_tick_s=0.2,
    )
    server.join(10)
    want = [{"seq": s, "text": t} for sc in chosen for s, t in sc.expected_texts]
    assert [json.loads(line) for line in out.getvalue().splitlines()] == want


# -- the board script -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["hello", "你好，世界", "Café déjà vu", "é", "x" * 300])
def test_board_encoder_is_byte_identical_to_the_host_codec(text):
    assert board.text_frame(text, 5) == tl.encode_text(text, 5)


def test_board_encoder_other_frames_and_crc():
    assert board.crc16_ccitt_false(b"123456789") == 0x29B1
    assert board.encode(board.TYPE_PING, 255) == tl.encode(tl.FrameType.PING, 255)
    assert board.encode(board.TYPE_TEXT, 256 + 2, b"a") == tl.encode(tl.FrameType.TEXT, 2, b"a")


def test_board_cleans_text_the_way_the_host_would_refuse_it():
    assert board.clean_text("a\nb\x1b[0m ‮done") == "a b[0m done"
    assert board.clean_text("\x00\x1b  ") is None
    long = "漢" * 400
    cleaned = board.clean_text(long)
    assert cleaned is not None and len(cleaned.encode()) <= 512
    assert parse_all([board.text_frame(long, 0) or b""])[0][0].text == cleaned
    frame = board.text_frame("a\nb\x1b[0m ‮done", 1)
    assert frame is not None and parse_all([frame])[1]["invalid_text"] == 0


def test_board_script_imports_maix_only_inside_functions():
    tree = ast.parse((EXAMPLE / "board" / "maixpy_send.py").read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name.split(".")[0] for n in top for a in n.names} | {
        (n.module or "").split(".")[0] for n in top if isinstance(n, ast.ImportFrom)
    }
    assert "maix" not in names
    text = (EXAMPLE / "board" / "maixpy_send.py").read_text(encoding="utf-8")
    assert "UNTESTED ON HARDWARE" in text
    assert "https://wiki.sipeed.com/maixpy/doc/en/mllm/asr_whisper.html" in text
    assert "https://wiki.sipeed.com/maixpy/doc/en/peripheral/uart.html" in text
    assert '"/dev/ttyS4"' in text and 'UART_DEVICE = "/dev/ttyS0"' not in text


# -- isolation from the product --------------------------------------------------------


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_the_codec_imports_only_the_standard_library():
    assert _imports(EXAMPLE / "textlink.py") <= set(sys.stdlib_module_names) | {"__future__"}


@pytest.mark.parametrize("name", ["host_reader.py", "simulated_board.py"])
def test_reader_and_simulator_import_only_stdlib_siblings_and_lazy_pyserial(name):
    allowed = set(sys.stdlib_module_names) | {"__future__", "textlink", "serial"}
    assert _imports(EXAMPLE / name) <= allowed


def test_reader_never_types_and_never_touches_the_network():
    forbidden = {
        "yazses",
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "pyautogui",
        "pynput",
        "evdev",
        "keyboard",
        "xdotool",
        "subprocess",
        "asyncio",
    }
    for name in ("host_reader.py", "simulated_board.py", "textlink.py"):
        assert not (_imports(EXAMPLE / name) & forbidden), name
    # pyserial is imported lazily, inside a function, never at module level
    tree = ast.parse((EXAMPLE / "host_reader.py").read_text(encoding="utf-8"))
    top = {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    assert "serial" not in top


def test_nothing_in_the_product_imports_the_example():
    needles = ("maixcam2-text-link", "maixcam2_text_link", "textlink", "host_reader")
    sources = sorted((ROOT / "src").rglob("*.py"))
    assert len(sources) > 100  # the glob matched the product, so the loop below proves something
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not any(n in text for n in needles), path


def test_example_files_carry_no_ai_attribution_or_personal_data():
    examples = sorted(EXAMPLE.rglob("*.py"))
    assert len(examples) == 4
    for path in [
        *examples,
        EXAMPLE / "README.md",
        ROOT / "design" / "specs" / "textlink-wire-protocol.md",
    ]:
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("co-authored-by", "generated by", "generated with"):
            assert needle not in text, f"{path}: {needle}"


# -- review round 2: refusal rules, EOF flush, repeats, device handling ----------------

# Characters the board's cleaner must remove that no unicode *category* rule covers. Written
# out here on purpose: a test that read the board's own set would lose a case whenever
# someone deleted one from it.
UNCATEGORISED_REFUSED = [
    0x2028,  # line separator (Zl)
    0x2029,  # paragraph separator (Zp)
    0xFFFE,  # noncharacters (Cn)
    0xFFFF,
    0xFFFD,  # replacement character (So)
    0x2800,  # braille blank (So)
    0x3164,  # hangul filler (Lo)
    0xFFA0,  # halfwidth hangul filler (Lo)
    0x115F,  # hangul choseong filler (Lo)
    0x1160,  # hangul jungseong filler (Lo)
]


def _host_result(text: str) -> str | None:
    """What the host does with ``text`` on the wire: the decoded text, or None if refused."""
    try:
        return tl.decode_text(text.encode("utf-8", "surrogatepass"))
    except tl.InvalidText:
        return None


def test_the_refusal_constant_is_the_set_the_board_mirrors():
    assert set(tl.REFUSED_CHARS) == {chr(c) for c in UNCATEGORISED_REFUSED}
    assert set(board._REFUSED) == set(tl.REFUSED_CHARS)


@pytest.mark.parametrize("code", UNCATEGORISED_REFUSED, ids=lambda c: f"U+{c:04X}")
def test_every_character_of_the_boards_refused_set_is_removed(code):
    ch = chr(code)
    assert board.clean_text(f"a{ch}b") == "ab"
    assert _host_result(f"a{ch}b") is None


# ~60 representative code points: (code point, True when the host refuses it inside a word).
_AGREEMENT = [(c, True) for c in (0x00, 0x09, 0x0A, 0x0D, 0x1B, 0x7F, 0x80, 0x85, 0x9B, 0x9F)]
_AGREEMENT += [(c, True) for c in (0x00AD, 0x0600, 0x061C, 0x180E, 0x200B, 0x200E, 0x200F)]
_AGREEMENT += [(c, True) for c in (0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2060, 0x2066)]
_AGREEMENT += [(c, True) for c in (0x2067, 0x2068, 0x2069, 0x206A, 0x206F, 0xFEFF, 0xFFF9)]
_AGREEMENT += [(c, True) for c in (0xFFFB, 0xE0001, 0xE0041, 0xE007F)]
_AGREEMENT += [(c, True) for c in UNCATEGORISED_REFUSED]
_AGREEMENT += [(c, True) for c in (0xD800, 0xDBFF, 0xDFFF)]  # lone surrogates
_AGREEMENT += [(c, False) for c in (0x20, 0x2D, 0x2E, 0x31, 0x41, 0xA0, 0xE9, 0x200C, 0x200D)]
_AGREEMENT += [(c, False) for c in (0x3000, 0x0301, 0x0344, 0x0627, 0x0F73, 0x1100, 0x1161)]
_AGREEMENT += [(c, False) for c in (0x4F60, 0xAC00, 0xFE0F, 0x1F600, 0x2603, 0x10FFFF - 0x2)]


def test_the_agreement_table_is_about_sixty_code_points():
    assert 55 <= len({c for c, _ in _AGREEMENT}) <= 80


@pytest.mark.parametrize(("code", "refused"), _AGREEMENT, ids=lambda v: f"{v}")
def test_board_cleaner_and_host_decoder_agree_on_every_character(code, refused):
    ch = chr(code)
    text = f"a{ch}b"
    host = _host_result(text)
    cleaned = board.clean_text(text)
    assert cleaned is not None
    assert (host is None) is refused, f"host verdict for U+{code:04X}"
    if host is not None:
        assert cleaned == host  # the board keeps exactly what the host would accept
    else:
        assert ch not in cleaned  # the board removes what the host would refuse...
    assert _host_result(cleaned) == cleaned  # ...so whatever it sends is accepted


INVISIBLE_ONLY = [
    "\u200b",
    "\u2060",
    "\ufeff",
    "\U000e0041\U000e0042",
    "\u206a\u206f",
    "\ufff9\ufffa\ufffb",
    "\ufffe",
    "\uffff",
    "\ufffd",
    "\u2800",
    "\u3164",
    "\uffa0",
    "\u115f\u1160",
    "\u200c",
    "\u200d",
    "\u0301",
    "  \t ",
]


@pytest.mark.parametrize("text", INVISIBLE_ONLY, ids=lambda t: "+".join(f"{ord(c):04X}" for c in t))
def test_text_with_no_visible_content_is_refused_by_host_and_dropped_by_board(text):
    with pytest.raises(tl.InvalidText):
        tl.decode_text(text.encode())
    frames, stats = parse_all([tl.encode(tl.FrameType.TEXT, 0, text.encode())])
    assert frames == [] and stats["invalid_text"] == 1
    assert board.clean_text(text) is None
    assert board.text_frame(text, 0) is None


def test_zero_width_non_joiner_and_joiner_need_a_letter_beside_them():
    persian = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
    assert tl.decode_text(persian.encode()) == persian
    assert tl.decode_text("\u0915\u200d\u0937".encode()) == "\u0915\u200d\u0937"
    for no_letter in ("1\u200c2", "\U0001f468\u200d\U0001f469", "\u200c\u200c"):
        with pytest.raises(tl.InvalidText):
            tl.decode_text(no_letter.encode())
    assert board.clean_text("1\u200c2") == "12"  # the board drops them when there is no letter
    assert board.clean_text(persian) == persian


def test_invalid_text_reasons_for_the_new_rules():
    reasons = []
    for payload in ("a\u200bb", "a\u3164b", "\u0301", "1\u200c2"):
        with pytest.raises(tl.InvalidText) as info:
            tl.decode_text(payload.encode())
        reasons.append(info.value.reason)
    assert reasons == ["format", "invisible", "empty", "format"]


def test_nfc_expansion_past_512_bytes_is_refused_after_normalisation():
    # U+0344 normalises to U+0308 U+0301, doubling its UTF-8 size (2 bytes become 4).
    fits = ("1" + "\u0344" * 127).encode()
    grows = ("1" + "\u0344" * 128).encode()
    assert len(fits) <= 512 and len(grows) <= 512  # both are legal wire payloads
    assert len(unicodedata.normalize("NFC", fits.decode()).encode()) == 509
    assert len(unicodedata.normalize("NFC", grows.decode()).encode()) == 513
    assert tl.decode_text(fits) == unicodedata.normalize("NFC", fits.decode())
    with pytest.raises(tl.InvalidText):
        tl.decode_text(grows)
    frames, stats = parse_all([tl.encode(tl.FrameType.TEXT, 0, grows) + tl.encode_text("ok", 1)])
    assert [f.text for f in frames] == ["ok"] and stats["invalid_text"] == 1
    with pytest.raises(tl.InvalidText):
        tl.encode_text(grows.decode(), 0)
    cleaned = board.clean_text(grows.decode())
    assert cleaned is not None and len(cleaned.encode()) <= 512
    assert _host_result(cleaned) == cleaned


# -- duplicates are delivered ----------------------------------------------------------


def test_a_repeated_utterance_is_not_lost_end_to_end():
    out, err = io.StringIO(), io.StringIO()
    wire = tl.encode_text("yes", 0) + tl.encode_text("yes", 0)
    parser = reader.run(iter([wire]), out, err, rate=None)
    assert [json.loads(line)["text"] for line in out.getvalue().splitlines()] == ["yes", "yes"]
    assert parser.seq_repeats == 1
    assert '"seq_repeats": 1' in err.getvalue()


def test_the_reader_has_no_duplicate_dropping_option():
    with pytest.raises(SystemExit) as info:
        reader.main(["--replay", "x.bin", "--allow-duplicates"])
    assert info.value.code == 2


# -- end of input flushes the parser ---------------------------------------------------

_TRUNCATED_HEAD = bytes.fromhex("59 53 01 01 00 01 00") + b"xxxxx"  # claims LEN 256, 5 bytes follow


def test_run_flushes_at_end_of_input_so_a_frame_behind_a_dead_head_is_not_lost():
    out, err = io.StringIO(), io.StringIO()
    reader.run(iter([_TRUNCATED_HEAD + tl.encode_text("recovered", 1)]), out, err, rate=None)
    assert [json.loads(line)["text"] for line in out.getvalue().splitlines()] == ["recovered"]


def test_replay_cli_flushes_at_end_of_file(tmp_path):
    capture = tmp_path / "cut.bin"
    capture.write_bytes(_TRUNCATED_HEAD + tl.encode_text("recovered", 1))
    done = subprocess.run(
        [sys.executable, str(EXAMPLE / "host_reader.py"), "--replay", str(capture)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert [json.loads(line)["text"] for line in done.stdout.splitlines()] == ["recovered"]


@pytest.mark.parametrize("tail", [b"Y", b"abcY", b"YS", b"YS\x01\x01", b"YS\x01\x01\x00\x00"])
def test_final_flush_discards_a_tail_shorter_than_a_header(tail):
    parser = tl.FrameParser()
    parser.feed(tail)
    assert parser.flush_partial() == []
    assert parser.buffered == 0
    assert parser.resync_bytes == len(tail)  # every byte held was counted as discarded


# -- run(): the limiter, idle exit -------------------------------------------------------


def test_run_applies_the_rate_limit_and_reports_it():
    clock = _Clock()
    wire = b"".join(tl.encode_text(f"t{i}", i) for i in range(4))
    out, err = io.StringIO(), io.StringIO()
    reader.run(iter([wire]), out, err, rate=1.0, clock=clock)
    assert [json.loads(line)["text"] for line in out.getvalue().splitlines()] == ["t0"]
    assert '"rate_limited": 3' in err.getvalue()


def test_run_idle_exit_stops_reading_after_enough_silence():
    after = tl.encode_text("after the silence", 1)
    source = iter([tl.encode_text("before", 0), None, None, after])
    out, err = io.StringIO(), io.StringIO()
    reader.run(source, out, err, rate=None, idle_exit_s=2.0, idle_tick_s=1.0)
    assert [json.loads(line)["text"] for line in out.getvalue().splitlines()] == ["before"]
    assert next(source) == after  # the source was left unread past the exit


def test_run_idle_exit_is_reset_by_data():
    source = iter([None, tl.encode_text("a", 0), None, tl.encode_text("b", 1)])
    out, err = io.StringIO(), io.StringIO()
    reader.run(source, out, err, rate=None, idle_exit_s=2.0, idle_tick_s=1.0)
    assert [json.loads(line)["text"] for line in out.getvalue().splitlines()] == ["a", "b"]


def test_rate_limiter_survives_a_clock_that_goes_backwards():
    clock = _Clock()
    limiter = tl.RateLimiter(2.0, clock=clock)
    assert limiter.allow() and limiter.allow() and not limiter.allow()
    clock.now -= 100.0  # a wall-clock step back must not push the bucket into debt
    assert not limiter.allow()
    clock.now += 1.0  # one second later the bucket has refilled normally
    assert limiter.allow()


@pytest.mark.parametrize("rate", [0, 0.0, -5, float("nan"), float("inf"), float("-inf")])
def test_rate_limiter_rejects_a_rate_that_is_not_finite_and_positive(rate):
    with pytest.raises(ValueError):
        tl.RateLimiter(rate)


@pytest.mark.parametrize("rate", ["nan", "inf", "-inf", "-5", "0", "abc"])
def test_cli_rejects_a_bad_rate_cleanly(rate, capsys):
    with pytest.raises(SystemExit) as info:
        reader.main(["--replay", "x.bin", f"--rate={rate}"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "--rate" in err and "Traceback" not in err


def test_cli_rate_error_is_clean_in_a_real_process(tmp_path):
    done = subprocess.run(
        [sys.executable, str(EXAMPLE / "host_reader.py"), "--replay", "x.bin", "--rate", "nan"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2 and "Traceback" not in done.stderr


# -- feed() input types ---------------------------------------------------------------


def test_feed_accepts_any_bytes_like_object_including_a_strided_memoryview():
    wire = tl.encode_text("strided", 3)
    strided = memoryview(bytearray(b"".join(bytes((b, 0)) for b in wire)))[::2]
    assert not strided.contiguous
    for chunk in (strided, bytearray(wire), memoryview(wire), memoryview(wire).cast("B")):
        assert [f.text for f in tl.FrameParser().feed(chunk)] == ["strided"]


@pytest.mark.parametrize("bad", ["YS", 5, None, ["Y"]])
def test_feed_refuses_what_is_not_bytes_like(bad):
    with pytest.raises(TypeError):
        tl.FrameParser().feed(bad)


# -- device handling ------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals are POSIX only")
@pytest.mark.timeout(30)
def test_iter_device_restores_the_terminal_it_put_in_raw_mode():
    import pty
    import termios

    master, slave = pty.openpty()
    try:
        before = termios.tcgetattr(slave)
        gen = reader.iter_device(os.ttyname(slave), idle_s=0.1)
        assert next(gen) is None  # the first idle tick: the port is open and configured
        assert termios.tcgetattr(slave)[3] != before[3]  # it really was switched to raw
        os.write(master, b"hello")
        assert next(gen) == b"hello"
        gen.close()
        after = termios.tcgetattr(slave)
        # lflag (ICANON, ECHO, ISIG, ...). PENDIN is a status bit the kernel sets by itself
        # while input is pending (macOS leaves it set after the restore), so it is not part
        # of what the reader saved and must not be compared.
        pendin = getattr(termios, "PENDIN", 0) | 0x20000000  # 0x20000000 is PENDIN on Darwin
        assert after[3] & ~pendin == before[3] & ~pendin
        assert after[:3] == before[:3]  # iflag, oflag, cflag
        assert after[4:] == before[4:]  # speeds and control characters
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_a_fifo_with_no_writer_does_not_block_idle_exit(tmp_path):
    fifo = tmp_path / "link"
    os.mkfifo(fifo)
    try:
        done = subprocess.run(
            [sys.executable, str(EXAMPLE / "host_reader.py"), str(fifo), "--idle-exit", "0.5"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("host_reader blocked forever opening a FIFO that has no writer")
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
@pytest.mark.timeout(30)
def test_a_fifo_with_a_writer_delivers_frames_and_ends_at_eof(tmp_path):
    fifo = tmp_path / "link"
    os.mkfifo(fifo)
    proc = subprocess.Popen(
        [sys.executable, str(EXAMPLE / "host_reader.py"), str(fifo)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with open(fifo, "wb") as writer:  # returns once the reader has opened its end
            writer.write(tl.encode_text("over a pipe", 0))
        stdout, _ = proc.communicate(timeout=20)
    finally:
        proc.kill()
        proc.wait()
    assert [json.loads(line)["text"] for line in stdout.splitlines()] == ["over a pipe"]


# -- the board script, round 2 ----------------------------------------------------------


class _FakeSerial:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(bytes(data))


@pytest.fixture
def fake_maix(monkeypatch):
    """A stand-in for the MaixPy ``maix`` package, so ``setup_uart`` and ``main`` run on a PC."""
    state = types.SimpleNamespace(pins=[], uart_args=None, serial=_FakeSerial(), transcript="hi")

    def make_uart(device, baud):
        state.uart_args = (device, baud)
        return state.serial

    class Whisper:
        def __init__(self, model, language):
            state.whisper_args = (model, language)

        def transcribe(self, wav):
            return state.transcript

    def set_pin(pin, func):
        state.pins.append((pin, func))
        return 0

    module = types.ModuleType("maix")
    module.err = types.SimpleNamespace(check_raise=lambda code, msg: None)
    module.pinmap = types.SimpleNamespace(set_pin_function=set_pin)
    module.uart = types.SimpleNamespace(UART=make_uart)
    module.nn = types.SimpleNamespace(Whisper=Whisper)
    monkeypatch.setitem(sys.modules, "maix", module)
    monkeypatch.setattr(board, "_seq", 0)
    return state


def test_board_opens_uart4_at_the_baud_the_host_and_the_spec_use(fake_maix):
    board.setup_uart()
    assert fake_maix.uart_args == ("/dev/ttyS4", 115200)
    assert fake_maix.pins == [("A21", "UART4_TX"), ("A22", "UART4_RX")]
    assert board.BAUD == reader.DEFAULT_BAUD == 115200
    assert "115200" in (ROOT / "design" / "specs" / "textlink-wire-protocol.md").read_text(
        encoding="utf-8"
    )


def test_board_seq_increments_per_frame_actually_sent(fake_maix):
    for _ in range(3):
        assert board.send_text(fake_maix.serial, "yes") is not None
    assert board.send_text(fake_maix.serial, "\x00") is None  # nothing sendable: no frame, no SEQ
    assert board.send_text(fake_maix.serial, "after") is not None
    frames, stats = parse_all(fake_maix.serial.written)
    assert [(f.seq, f.text) for f in frames] == [(0, "yes"), (1, "yes"), (2, "yes"), (3, "after")]
    assert stats["seq_gaps"] == 0 and stats["seq_repeats"] == 0


def test_board_seq_wraps_modulo_256(fake_maix, monkeypatch):
    monkeypatch.setattr(board, "_seq", 255)
    board.send_text(fake_maix.serial, "one")
    board.send_text(fake_maix.serial, "two")
    frames, stats = parse_all(fake_maix.serial.written)
    assert [f.seq for f in frames] == [255, 0] and stats["seq_gaps"] == 0
    assert board._seq == 1  # the counter itself wrapped, not just the byte on the wire


@pytest.mark.parametrize("result", [None, 5, b"bytes", ["x"], "", "   ", "\x00\x1b", "\u200b"])
def test_board_sends_nothing_when_there_is_no_text(fake_maix, capsys, result):
    fake_maix.transcript = result
    board.main()
    out = capsys.readouterr().out
    assert fake_maix.serial.written == []
    assert "nothing sent" in out and "sent seq" not in out
    assert board._seq == 0


def test_board_main_reports_what_it_sent(fake_maix, capsys):
    fake_maix.transcript = "hello"
    board.main()
    assert capsys.readouterr().out.strip() == "sent seq 0 bytes 14"
    assert fake_maix.serial.written == [tl.encode_text("hello", 0)]


def test_board_removes_forbidden_characters_before_it_normalises():
    # Removing the zero-width space first lets "a" + U+0301 compose; the result is what the
    # host will produce from the same text, so the two agree.
    text = "a" + chr(0x200B) + chr(0x0301)
    assert board.clean_text(text) == "\xe1"
    assert _host_result(board.clean_text(text)) == "\xe1"


def test_board_strips_lone_surrogates_instead_of_raising():
    assert board.clean_text("a\ud800b") == "ab"
    assert board.text_frame("\udfff", 0) is None
    assert board.text_frame("x\ud83dy", 0) == tl.encode_text("xy", 0)


def _board_pool() -> list[str]:
    pool = [chr(c) for c in range(0x00, 0x20)] + [chr(0x7F), chr(0x85), chr(0x9F)]
    pool += [chr(c) for c in range(0x0300, 0x0310)] + ["\u0344", "\u0345", "\u0f73", "\u0f71"]
    pool += [chr(c) for c in (0x1100, 0x1101, 0x1161, 0x1162, 0x11A8, 0x115F, 0x1160)]
    pool += [
        "\u6f22",
        "\u5b57",
        "\u4f60",
        "\u597d",
        "\u00e9",
        "\u00e8",
        "\u00f1",
        "\u01c6",
        "\u00c5",
        "\u00c5",
        "\u00aa",
        "\u00df",
        "x",
        "Y",
        "7",
        ".",
        " ",
    ]
    pool += [
        "\u200b",
        "\u200c",
        "\u200d",
        "\u2060",
        "\ufeff",
        "\u2028",
        "\u2029",
        "\u202e",
        "\u3164",
    ]
    pool += ["\uffa0", "\ufffd", "\uffff", "\U000e0041", "\ud800", "\u2800", "\u00a0", "\u0627"]
    return pool


def test_board_output_is_always_accepted_by_the_host_unchanged():
    rng = random.Random(20261113)
    pool = _board_pool()
    sent = 0
    for i in range(2500):
        n = rng.choice([1, 2, 3, 5, 8, 20, 60, 60, 60, 600])
        text = "".join(rng.choice(pool) for _ in range(n))
        cleaned = board.clean_text(text)
        frame = board.text_frame(text, i & 0xFF)
        if cleaned is None:
            assert frame is None, repr(text)
            continue
        assert frame is not None
        sent += 1
        assert _host_result(cleaned) == cleaned, repr(text)
        frames, stats = parse_all([frame])
        assert [f.text for f in frames] == [cleaned] and stats["invalid_text"] == 0, repr(text)
    assert sent > 600  # the pool is mostly sendable, so the loop above proved something


# -- the spec file is the other half of the golden vectors --------------------------------

SPEC = ROOT / "design" / "specs" / "textlink-wire-protocol.md"


def _spec_vectors() -> list[tuple[str, str, str, str]]:
    rows = []
    in_section = False
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == "## Golden vectors"
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        match = re.fullmatch(r"`((?:[0-9a-f]{2} ?)+)`", cells[1]) if len(cells) >= 4 else None
        if match:
            rows.append((cells[0], match.group(1), cells[2], cells[3]))
    return rows


def test_every_golden_vector_in_the_spec_is_reproduced_byte_for_byte_by_encode():
    rows = _spec_vectors()
    assert len(rows) >= 6
    for label, hexstr, length, crc in rows:
        wire = bytes.fromhex(hexstr)
        ftype, seq, payload = wire[3], wire[4], wire[7:-2]
        assert tl.encode(ftype, seq, payload) == wire, label
        assert f"SEQ {seq}" in label, label
        assert int(length) == len(wire), label
        assert crc.strip("`") == f"0x{wire[-2:].hex().upper()}", label
        assert _bitwise_crc(wire[2:-2]) == int.from_bytes(wire[-2:], "big"), label
    assert {r[1] for r in rows} == {
        g[4] for g in GOLDEN
    }  # the spec and the tests list the same vectors


def test_the_docs_describe_repeats_as_delivered_and_counted_not_dropped():
    docs = {
        "spec": SPEC,
        "readme": EXAMPLE / "README.md",
        "adr": ROOT / "design" / "adr" / "adr-v2-156-maixcam2-text-link.md",
    }
    for name, path in docs.items():
        text = path.read_text(encoding="utf-8")
        assert "drops an exact immediate repeat" not in text, name
        assert "an exact immediate repeat" not in text or "not dropped" in text, name
        if name != "adr":
            assert "seq_repeats" in text and "Not handled" in text, name
    spec_text = SPEC.read_text(encoding="utf-8")
    assert "512 bytes" in spec_text and "slightly" not in spec_text
