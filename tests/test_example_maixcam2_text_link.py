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
import random
import subprocess
import sys
import threading
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
        blacklist_categories=("Cc", "Cs", "Cn"),
        blacklist_characters=[
            " ",
            " ",
            "‎",
            "‏",
            "؜",
            *map(chr, range(0x202A, 0x202F)),
            *map(chr, range(0x2066, 0x206A)),
        ],
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() != "")


@settings(max_examples=150, deadline=None)
@given(_SAFE_TEXT, st.integers(0, 255))
def test_round_trip_property(text, seq):
    import unicodedata

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


def test_duplicate_is_flagged_and_reader_drops_it():
    wire = tl.encode_text("same", 4) * 2 + tl.encode_text("next", 5)
    frames, stats = parse_all([wire])
    assert [f.duplicate for f in frames] == [False, True, False]
    assert stats["duplicates"] == 1 and stats["seq_gaps"] == 0
    assert reader.process(tl.FrameParser(), wire) == [(4, "same"), (5, "next")]
    assert reader.process(tl.FrameParser(), wire, allow_duplicates=True) == [
        (4, "same"),
        (4, "same"),
        (5, "next"),
    ]


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
    reader.run(reader.iter_file(str(capture)), out, err, rate=0.0)
    lines = out.getvalue().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"seq": s, "text": t} for s, t in sim.SCENARIO_BY_NAME["multibyte_split"].expected_texts
    ]
    assert all(line.isascii() for line in lines)  # ensure_ascii: the output line is inert
    assert "frames_ok" in err.getvalue()


def test_reader_replay_cli(tmp_path):
    capture = tmp_path / "hostile.bin"
    capture.write_bytes(sim.SCENARIO_BY_NAME["hostile"].stream)
    done = subprocess.run(
        [sys.executable, str(EXAMPLE / "host_reader.py"), "--replay", str(capture)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert [json.loads(line) for line in done.stdout.splitlines()] == [
        {"seq": 12, "text": "safe text after the hostile ones"}
    ]
    assert '"invalid_text": 12' in done.stderr


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
    reader.run(source, out, err, rate=0.0)
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
        rate=0.0,
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
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not any(n in text for n in needles), path


def test_example_files_carry_no_ai_attribution_or_personal_data():
    for path in [
        *EXAMPLE.rglob("*.py"),
        EXAMPLE / "README.md",
        ROOT / "design" / "specs" / "textlink-wire-protocol.md",
    ]:
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("co-authored-by", "generated by", "generated with"):
            assert needle not in text, f"{path}: {needle}"
