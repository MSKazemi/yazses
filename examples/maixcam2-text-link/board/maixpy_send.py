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
for MaixCAM and does not state it for MaixCAM2. The adapter must match it. The board's USB-C port is a USB *function* port and is not a
serial bridge. The wire format is ``design/specs/textlink-wire-protocol.md`` in the YazSes
repository; the encoder below is a minimal inline copy of ``textlink.py``.

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

# Same rules as textlink.decode_text: refuse C0/C1/DEL, U+2028/9 and bidi controls.
_REFUSED = set("  ‎‏؜")
_REFUSED.update(chr(c) for c in range(0x202A, 0x202F))
_REFUSED.update(chr(c) for c in range(0x2066, 0x206A))


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


def clean_text(text):
    """NFC, drop forbidden characters (newlines become spaces), strip, cap at 512 UTF-8 bytes.

    The host refuses a whole frame that contains a forbidden character, so the board
    removes them first (a Whisper transcript has no business containing them). Returns
    None when nothing is left to send.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")  # keep words apart
    text = "".join(
        ch for ch in text if unicodedata.category(ch) != "Cc" and ch not in _REFUSED
    ).strip()
    data = text.encode("utf-8")
    while len(data) > MAX_TEXT_BYTES:  # cut on a character boundary, never mid-character
        text = text[:-1]
        data = text.encode("utf-8")
    text = text.strip()
    return text or None


def text_frame(text, seq):
    """A TEXT frame for ``text``, or None if there is nothing to send."""
    text = clean_text(text)
    if text is None:
        return None
    return encode(TYPE_TEXT, seq, text.encode("utf-8"))


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
    seq = 0
    # TODO(verify on device): loop/trigger design (button? voice activity?) is not decided.
    # One utterance per run is the smallest thing that exercises the whole path.
    if RECORD_FIRST:
        record_wav(WAV_PATH, RECORD_SECONDS)
    # TODO(verify on device): the wiki shows `text = whisper.transcribe(wav_path)` and
    # prints it, but does not state the return type; str is assumed here.
    result = whisper.transcribe(WAV_PATH)
    frame = text_frame(str(result), seq)
    if frame is not None:
        serial.write(frame)  # `.write(bytes)` per the UART wiki page
        # TODO(verify on device): whether write() blocks until the bytes are on the wire.
        seq = (seq + 1) & 0xFF
    print("sent seq", (seq - 1) & 0xFF, "bytes", len(frame) if frame else 0)


if __name__ == "__main__":
    main()
