"""Glasses↔Desktop Bridge (ADR-v2-013) — pairing state machine + frame protocol."""
from __future__ import annotations

import pytest

from yazses.bridge.frame import decode_frame, encode_frame
from yazses.bridge.session import BridgeSession, BridgeState


# ---- pairing state machine -------------------------------------------------

def test_full_pairing_lifecycle():
    s = BridgeSession(token="secret")
    assert s.state == BridgeState.IDLE
    assert s.can_stream is False
    s.begin_pairing()
    assert s.try_pair("secret", device_name="Pixel") is True
    assert s.state == BridgeState.PAIRED
    assert s.device_name == "Pixel"
    assert s.activate() is True
    assert s.can_stream is True
    s.close()
    assert s.state == BridgeState.CLOSED


def test_pairing_rejects_wrong_token():
    s = BridgeSession(token="secret")
    s.begin_pairing()
    assert s.try_pair("wrong") is False
    assert s.state == BridgeState.PENDING


def test_pairing_requires_pending_state():
    s = BridgeSession(token="secret")
    # not pairing yet → reject
    assert s.try_pair("secret") is False


def test_empty_token_never_pairs():
    s = BridgeSession(token="")
    s.begin_pairing()
    assert s.try_pair("") is False


def test_activate_requires_paired():
    s = BridgeSession(token="t")
    assert s.activate() is False  # from IDLE
    s.begin_pairing()
    assert s.activate() is False  # from PENDING


# ---- frame protocol --------------------------------------------------------

def test_frame_roundtrip():
    data = b"\x01\x02audiochunk"
    seq, payload, rest = decode_frame(encode_frame(7, data))
    assert seq == 7
    assert payload == data
    assert rest == b""


def test_decode_partial_returns_none():
    frame = encode_frame(1, b"hello")
    assert decode_frame(frame[:8]) is None       # header incomplete
    assert decode_frame(frame[:-2]) is None       # payload incomplete


def test_decode_multiple_frames_leaves_remainder():
    buf = encode_frame(1, b"aa") + encode_frame(2, b"bbb")
    seq1, p1, rest = decode_frame(buf)
    assert (seq1, p1) == (1, b"aa")
    seq2, p2, rest2 = decode_frame(rest)
    assert (seq2, p2) == (2, b"bbb")
    assert rest2 == b""


def test_decode_bad_magic_raises():
    with pytest.raises(ValueError):
        decode_frame(b"\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00")


def test_bridge_feature_registered():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "bridge" in [f.slug for f in feature_status(Config())]
