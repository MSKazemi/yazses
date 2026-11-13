"""MaixPy script for a Sipeed MaixCAM2: transcribe a WAV with Whisper, send the text on UART4.

##########################################################################################
#  UNTESTED ON HARDWARE.  This file has been syntax-checked and its frame encoder is     #
#  byte-compared against the host codec in the test suite, on a PC. It has never run on  #
#  a MaixCAM2. Every MaixPy call that is not named on the two Sipeed pages below is left  #
#  as a TODO(verify on device) rather than guessed.                                      #
##########################################################################################

Sources (the only MaixPy APIs used here are the ones these pages show):

* Whisper:  https://wiki.sipeed.com/maixpy/doc/en/mllm/asr_whisper.html
  ``nn.Whisper(model=".../whisper-base.mud", language="en")`` and ``.transcribe(wav_path)``.
  The page gives the input as a mono, 16 kHz WAV and says Whisper-base on MaixCAM2 needs
  1 GB of memory. It does not document how to record audio.
* UART:     https://wiki.sipeed.com/maixpy/doc/en/peripheral/uart.html
  ``uart.UART(device, baud)``, ``.write(bytes)``, and for MaixCAM2 UART4 the pins
  A21 (TX) and A22 (RX) with ``pinmap.set_pin_function``.

Wiring: UART4 = ``/dev/ttyS4``, TX = pin A21, RX = pin A22. **Never use UART0**
(``/dev/ttyS0``): the wiki lists it as the system terminal and log port. A USB-to-UART
adapter goes between those pins and the PC; connect board TX to adapter RX, and the
grounds together. Check the logic level of your board revision: Sipeed documents 3.3 V
for MaixCAM and does not state it for MaixCAM2. The adapter must match it. Per Sipeed
support (2026-11-09 email, not reproducible from this repository) the USB-C port is a USB
*function* port and is not a serial bridge. The wire format is
``design/specs/textlink-wire-protocol.md`` in the YazSes repository; the encoder below is
a minimal inline copy of ``textlink.py``.

This file is a research example and is not part of YazSes.
"""

import unicodedata

UART_DEVICE = "/dev/ttyS4"  # UART4 on MaixCAM2 per the wiki. Never /dev/ttyS0 (console).
BAUD = 115200
PIN_FUNCTIONS = {"A21": "UART4_TX", "A22": "UART4_RX"}

MODEL_PATH = "/root/models/whisper-base/whisper-base.mud"  # path shown on the wiki page
LANGUAGE = "en"  # the wiki: "zh" for Chinese, "en" for English
WAV_PATH = "/maixapp/share/audio/demo.wav"  # the wiki's demo file: mono, 16 kHz WAV
RECORD_SECONDS = 5
RECORD_FIRST = False  # True needs record_wav() implemented; see the TODO there

# --- inline minimal copy of the TextLink encoder (kept in sync by a test) -----------------

SYNC = b"YS"
VERSION = 0x01
TYPE_TEXT = 0x01
TYPE_PING = 0x03
MAX_TEXT_BYTES = 512

# Same rules as textlink.decode_text (a test compares the two, character by character).
# Removed by unicode category: Cc (controls), Cf (format: zero-width, BOM, tags, bidi
# controls, ...) and Cs (lone surrogates), except ZWNJ/ZWJ, which are kept only beside a
# letter. _REFUSED lists what no category covers: U+2028/9, the noncharacters
# U+FFFE/U+FFFF, U+FFFD and the invisible fillers U+2800, U+3164, U+FFA0, U+115F, U+1160.
_REFUSED = set(chr(c) for c in (0x2028, 0x2029, 0xFFFE, 0xFFFF, 0xFFFD))
_REFUSED.update(chr(c) for c in (0x2800, 0x3164, 0xFFA0, 0x115F, 0x1160))
_JOINERS = (chr(0x200C), chr(0x200D))


def crc16_ccitt_false(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no xorout)."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode(frame_type, seq, payload=b""):
    """One frame: SYNC VER TYPE SEQ LEN(u16 BE) PAYLOAD CRC16(u16 BE over VER..PAYLOAD)."""
    body = bytes((VERSION, frame_type, seq & 0xFF)) + len(payload).to_bytes(2, "big") + payload
    return SYNC + body + crc16_ccitt_false(body).to_bytes(2, "big")


def _wanted(ch):
    """True for a character the host would accept (the joiners are handled separately)."""
    return ch in _JOINERS or (
        unicodedata.category(ch) not in ("Cc", "Cf", "Cs") and ch not in _REFUSED
    )


def clean_text(text):
    """Drop forbidden characters, NFC, strip, cap at 512 UTF-8 bytes; None if nothing is left.

    The host refuses a whole frame that contains a forbidden character, so the board
    removes them first (a Whisper transcript has no business containing them); newlines
    and tabs become spaces so words stay apart. Removal comes *before* NFC: normalising
    first could compose a character that the filter then no longer recognises. The 512
    byte cap applies after NFC (it can expand text), cutting on a character boundary.
    A ZWNJ/ZWJ is kept only when the text has a letter, and text with no visible
    character (a letter, number, punctuation or symbol) is not sent.
    """
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")  # keep words apart
    text = "".join(ch for ch in text if _wanted(ch))
    while True:  # settle: every step below can change what the next one sees
        before = text
        if not any(unicodedata.category(ch)[0] == "L" for ch in text):
            text = "".join(ch for ch in text if ch not in _JOINERS)  # joiners need a letter
        text = unicodedata.normalize("NFC", text).strip()
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            text = text[:-1]  # cut on a character boundary, never mid-character
        if text == before:
            break
    if not any(unicodedata.category(ch)[0] in "LNPS" for ch in text):
        return None
    return text


def text_frame(text, seq):
    """A TEXT frame for ``text``, or None if there is nothing to send."""
    text = clean_text(text)
    if text is None:
        return None
    return encode(TYPE_TEXT, seq, text.encode("utf-8"))


_seq = 0  # SEQ of the next frame; counts frames actually sent, wraps modulo 256


def send_text(serial, result):
    """Clean ``result`` and send it as one TEXT frame. Returns ``(seq, bytes)`` or None.

    Sends nothing, and does not advance SEQ, when ``result`` is not a ``str`` (the Whisper
    page does not state the return type) or when nothing sendable is left after cleaning.
    """
    global _seq
    if not isinstance(result, str):
        return None
    frame = text_frame(result, _seq)
    if frame is None:
        return None
    serial.write(frame)  # `.write(bytes)` per the UART wiki page
    # TODO(verify on device): whether write() blocks until the bytes are on the wire.
    sent = _seq
    _seq = (_seq + 1) & 0xFF
    return sent, len(frame)


# --- hardware parts: imported inside functions so this file imports on a PC ---------------


def setup_uart():
    """Route A21/A22 to UART4 and open it. Calls follow the wiki's UART4 example."""
    from maix import err, pinmap, uart  # type: ignore[import-not-found,unused-ignore]

    for pin, func in PIN_FUNCTIONS.items():
        err.check_raise(
            pinmap.set_pin_function(pin, func), "Failed set pin%s function to %s" % (pin, func)
        )
    return uart.UART(UART_DEVICE, BAUD)


def record_wav(path, seconds):
    """Record ``seconds`` of mono 16 kHz audio into a WAV file at ``path``.

    TODO(verify on device): the Whisper wiki page does not document recording and the UART
    page is unrelated, so no recording API is named here on purpose. Implement this with
    the MaixPy audio recorder after reading its documentation, and check the file is mono,
    16 kHz, 16-bit PCM, which is what the Whisper page says ``transcribe`` expects.
    """
    raise NotImplementedError("record_wav: TODO(verify on device)")


def main():
    from maix import nn  # type: ignore[import-not-found,unused-ignore]

    serial = setup_uart()
    whisper = nn.Whisper(model=MODEL_PATH, language=LANGUAGE)
    # TODO(verify on device): loop/trigger design (button? voice activity?) is not decided.
    # One utterance per run is the smallest thing that exercises the whole path.
    if RECORD_FIRST:
        record_wav(WAV_PATH, RECORD_SECONDS)
    # TODO(verify on device): the wiki shows `text = whisper.transcribe(wav_path)` and
    # prints it, but does not state the return type; send only if it is a str.
    result = whisper.transcribe(WAV_PATH)
    sent = send_text(serial, result)
    if sent is None:
        print("nothing sent")
    else:
        print("sent seq", sent[0], "bytes", sent[1])


if __name__ == "__main__":
    main()
