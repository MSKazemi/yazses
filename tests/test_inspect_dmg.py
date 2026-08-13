"""The .dmg inspector must work without a Mac, a fixture, or a network.

`scripts/inspect-dmg.py` exists because the macOS bundle is the one artefact nobody
here can open, and two defects hid in exactly that blind spot: an `.app` reporting
``CFBundleVersion`` ``0.1.2`` for every release from v0.1.3 to v2.18.0, and a `.dmg`
with no x86_64 slice while the docs promised Intel support.

A fixture `.dmg` would be ~70 MB, so these build a **minimal UDIF container in
memory** instead and round-trip it. That also tests the thing most likely to rot:
the container parsing, not the greps.
"""

from __future__ import annotations

import importlib.util
import plistlib
import struct
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SECTOR = 512


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "inspect_dmg", ROOT / "scripts" / "inspect-dmg.py"
    )
    m = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(m)
    return m


def _mish(chunks: list[tuple[int, int, int, bytes]], start_sector: int = 0) -> bytes:
    """One BLKX block table. `chunks` are (type, sector_number, sector_count, payload)."""
    table = bytearray(b"mish")
    table += b"\0" * (8 - len(table))
    table += struct.pack(">Q", start_sector)
    table += b"\0" * (200 - len(table))
    table += struct.pack(">I", len(chunks) + 1)

    blobs = bytearray()
    entries = bytearray()
    # Payload offsets are absolute into the file; the caller places the data region
    # right after the header, so track it as we go.
    for ctype, sector_number, sector_count, payload in chunks:
        entries += struct.pack(
            ">IIQQQQ", ctype, 0, sector_number, sector_count, len(blobs), len(payload)
        )
        blobs += payload
    entries += struct.pack(">IIQQQQ", 0xFFFFFFFF, 0, 0, 0, 0, 0)
    return bytes(table + entries), bytes(blobs)


def _build_dmg(image: bytes) -> bytes:
    """Wrap a raw image in a minimal single-chunk zlib UDIF container."""
    if len(image) % SECTOR:
        image += b"\0" * (SECTOR - len(image) % SECTOR)
    payload = zlib.compress(image)

    # Data region first so the absolute offsets in the table are simply its position.
    data_region = payload
    table, _ = _mish([(0x80000005, 0, len(image) // SECTOR, payload)])
    # Rewrite the single entry's compressed offset to point at the real location.
    header_len = 204
    entry = bytearray(table[header_len : header_len + 40])
    struct.pack_into(">Q", entry, 24, 0)  # compressedOffset = start of file
    table = table[:header_len] + bytes(entry) + table[header_len + 40 :]

    plist = plistlib.dumps({"resource-fork": {"blkx": [{"Data": table}]}})
    xml_offset = len(data_region)
    trailer = bytearray(b"\0" * SECTOR)
    trailer[0:4] = b"koly"
    struct.pack_into(">QQ", trailer, 0xD8, xml_offset, len(plist))
    return data_region + plist + bytes(trailer)


INFO_PLIST = b"""<?xml version="1.0"?><plist><dict>
<key>CFBundleShortVersionString</key><string>2.18.2</string>
<key>CFBundleVersion</key><string>2.18.2</string>
<key>CFBundleIdentifier</key><string>com.yazses.app</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSMicrophoneUsageDescription</key><string>Mic is used only while held.</string>
</dict></plist>"""


def _macho(cputype: int, filetype: int = 2) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<III", cputype, 0, filetype)


def test_round_trips_a_minimal_udif_container(mod, tmp_path):
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    data = dmg.read_bytes()
    image, skipped = mod.inflate(data, *mod.read_koly(data))
    assert skipped == 0
    assert INFO_PLIST in image


def test_reads_the_bundle_version_and_architecture(mod, tmp_path):
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C) + _macho(0x0100000C, 6)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--expect-version", "2.18.2", "--expect-arch", "arm64"]) == 0


def test_a_wrong_version_is_an_error_not_a_note(mod, tmp_path):
    """This is the 0.1.2 bug. It must fail the command, not print a remark."""
    raw = INFO_PLIST.replace(b"<string>2.18.2</string>", b"<string>0.1.2</string>", 1)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw + b"\0" * 64 + _macho(0x0100000C)))

    assert mod.main([str(dmg), "--expect-version", "2.18.2"]) == 1


def test_an_x86_64_slice_is_caught_when_arm64_was_expected(mod, tmp_path):
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C) + _macho(0x01000007)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--expect-arch", "arm64"]) == 1


def test_expecting_an_arch_that_is_absent_fails(mod, tmp_path):
    """The real defect's mirror image: docs promised Intel, the bundle had none."""
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--expect-arch", "x86_64"]) == 1


def test_random_bytes_matching_the_magic_are_not_counted(mod):
    """A 4-byte magic collides often; cputype and filetype must both be sane."""
    noise = b"\xcf\xfa\xed\xfe" + struct.pack("<III", 0xDEADBEEF, 0, 99)
    tally, fat = mod.scan_macho(noise)
    assert tally == {} and fat == 0


def test_a_file_that_is_not_a_dmg_fails_cleanly(mod, tmp_path):
    p = tmp_path / "nope.dmg"
    p.write_bytes(b"just some bytes" * 100)
    assert mod.main([str(p)]) == 1


def test_a_missing_file_fails_cleanly(mod, tmp_path):
    assert mod.main([str(tmp_path / "absent.dmg")]) == 1
