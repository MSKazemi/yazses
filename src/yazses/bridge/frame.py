"""Audio-frame framing for the bridge link (pure) — ADR-v2-013.

A minimal length-prefixed frame so audio chunks survive a byte stream:
``[magic:4][seq:4][len:4][payload:len]`` big-endian. Pure encode/decode with
partial-buffer handling — the socket layer feeds bytes and drains whole frames.
"""
from __future__ import annotations

import struct

_MAGIC = 0x59425249  # 'YBRI'
_HEADER = struct.Struct(">III")


def encode_frame(seq: int, payload: bytes) -> bytes:
    """Frame one audio chunk with a sequence number."""
    return _HEADER.pack(_MAGIC, seq & 0xFFFFFFFF, len(payload)) + bytes(payload)


def decode_frame(buf: bytes):
    """Decode the first frame in ``buf``.

    Returns ``(seq, payload, rest)`` when a whole frame is present, or ``None``
    when more bytes are needed. Raises ``ValueError`` on a bad magic (desync).
    """
    if len(buf) < _HEADER.size:
        return None
    magic, seq, length = _HEADER.unpack(buf[:_HEADER.size])
    if magic != _MAGIC:
        raise ValueError("bad bridge frame magic (stream desynchronised)")
    end = _HEADER.size + length
    if len(buf) < end:
        return None
    return seq, buf[_HEADER.size:end], buf[end:]
