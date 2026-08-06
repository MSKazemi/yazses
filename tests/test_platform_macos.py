"""Unit tests for the parts of platform.macos that don't need PyObjC.

PyObjC modules are only available on darwin; the integration with
CGEventTap / CGEvent / rumps is tested manually on a Mac. The parts here are
pure Python: hotkey-id resolution and UTF-16 chunk splitting.
"""

from __future__ import annotations

import pytest

from yazses.platform.macos.hotkey import (
    KVK_SPACE,
    NX_DEVICELALTKEYMASK,
    NX_DEVICERALTKEYMASK,
    NX_DEVICERCTLKEYMASK,
    resolve_key_id,
)
from yazses.platform.macos.injector import _utf16_chunks

# ---- Hotkey resolution -------------------------------------------------


def test_auto_resolves_to_right_option_by_default():
    name, kind, value = resolve_key_id("auto")
    assert name == "right_option"
    assert kind == "modifier"
    assert value == NX_DEVICERALTKEYMASK


def test_right_option_is_modifier():
    name, kind, value = resolve_key_id("right_option")
    assert (name, kind, value) == ("right_option", "modifier", NX_DEVICERALTKEYMASK)


def test_right_alt_aliases_right_option():
    # Linux compatibility — same flag mask, different canonical name.
    _, _, value = resolve_key_id("right_alt")
    assert value == NX_DEVICERALTKEYMASK


def test_right_ctrl_is_modifier():
    name, kind, value = resolve_key_id("right_ctrl")
    assert (name, kind, value) == ("right_ctrl", "modifier", NX_DEVICERCTLKEYMASK)


def test_left_option_distinct_from_right_option():
    _, _, value = resolve_key_id("left_option")
    assert value == NX_DEVICELALTKEYMASK
    assert value != NX_DEVICERALTKEYMASK


def test_space_is_keycode():
    name, kind, value = resolve_key_id("space")
    assert (name, kind, value) == ("space", "key", KVK_SPACE)


def test_unknown_hotkey_raises():
    with pytest.raises(ValueError):
        resolve_key_id("totally-fake")


# ---- UTF-16 chunking ---------------------------------------------------


def test_chunking_short_text_one_chunk():
    chunks = _utf16_chunks("hello world")
    assert len(chunks) == 1
    assert chunks[0] == [ord(c) for c in "hello world"]


def test_chunking_long_text_multiple_chunks():
    text = "x" * 50
    chunks = _utf16_chunks(text)
    # 50 BMP chars → 50 UTF-16 units → ceil(50/20) = 3 chunks
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == 50


def test_chunking_empty_text():
    assert _utf16_chunks("") == []


def test_chunking_handles_emoji_surrogate_pair_at_boundary():
    # Each emoji "🔴" is U+1F534 → encodes as a UTF-16 surrogate pair (2 units).
    # Place a surrogate pair right at the chunk boundary (positions 19+20 in
    # the first 20-unit window). 19 plain chars + 1 emoji forces the boundary
    # to fall between the high and low surrogate; the chunker must back off.
    text = ("a" * 19) + "🔴" + ("b" * 5)
    chunks = _utf16_chunks(text)
    # First chunk should NOT split the surrogate pair: it stops at 19 a's.
    assert len(chunks[0]) == 19
    # Surrogate pair starts the next chunk.
    assert 0xD800 <= chunks[1][0] <= 0xDBFF
    assert 0xDC00 <= chunks[1][1] <= 0xDFFF
