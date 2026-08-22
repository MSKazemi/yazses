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


def test_json_mode_is_machine_readable_and_still_enforces_expectations(mod, tmp_path, capsys):
    """A release job wants the findings recorded, not just a pass/fail."""
    import json

    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--json", "--expect-arch", "arm64"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["macho_slices"] == {"arm64": 1}
    assert payload["info_plist"]["CFBundleShortVersionString"] == "2.18.2"
    assert payload["undecodable_chunks"] == 0

    # The expectations must gate the exit code in JSON mode too, not just in text mode.
    assert mod.main([str(dmg), "--json", "--expect-arch", "x86_64"]) == 1


# --- --require-key: the permission strings ---------------------------------
#
# The #182 shape. macOS refuses a service whose `NS*UsageDescription` is absent
# **without prompting**, so the bundle is well formed, the build is green, and the
# feature is simply dead. Version and architecture were the only things this tool
# could fail on, and neither would have caught it.

_INPUT_MONITORING = (
    b"<key>NSInputMonitoringUsageDescription</key>"
    b"<string>Watches the dictation key.</string>"
)


def _plist_with(extra: bytes) -> bytes:
    return INFO_PLIST.replace(b"</dict></plist>", extra + b"</dict></plist>", 1)


def test_a_required_permission_string_that_is_present_passes(mod, tmp_path):
    raw = _plist_with(_INPUT_MONITORING) + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert (
        mod.main(
            [
                str(dmg),
                "--require-key",
                "NSMicrophoneUsageDescription",
                "--require-key",
                "NSInputMonitoringUsageDescription",
            ]
        )
        == 0
    )


def test_a_missing_permission_string_fails_the_command(mod, tmp_path):
    """The real defect: the app cannot ask for Input Monitoring, so the hotkey
    never fires and macOS never shows the microphone prompt either."""
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C)  # no Input Monitoring key
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--require-key", "NSInputMonitoringUsageDescription"]) == 1


def test_an_empty_permission_string_is_missing_too(mod, tmp_path):
    """`<string></string>` satisfies a presence check and satisfies no user: macOS
    shows this text in the dialog, and an empty prompt is an unanswerable one."""
    raw = _plist_with(
        b"<key>NSInputMonitoringUsageDescription</key><string></string>"
    ) + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--require-key", "NSInputMonitoringUsageDescription"]) == 1


def test_a_required_key_outside_plist_keys_is_still_looked_for(mod, tmp_path):
    """`--require-key` must not silently fail on a key this script does not list;
    otherwise the check reports a correct bundle as broken and gets removed."""
    raw = _plist_with(
        b"<key>NSCameraUsageDescription</key><string>Gaze targeting.</string>"
    ) + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert "NSCameraUsageDescription" not in mod.PLIST_KEYS
    assert mod.main([str(dmg), "--require-key", "NSCameraUsageDescription"]) == 0


def test_an_undecodable_bundle_reports_the_container_not_the_keys(mod, tmp_path, capsys):
    """No Info.plist at all is one fault, not one per key -- naming five missing
    permissions would send someone to the spec file, which is fine."""
    raw = b"\0" * 512 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    rc = mod.main(
        [
            str(dmg),
            "--require-key",
            "NSMicrophoneUsageDescription",
            "--require-key",
            "NSInputMonitoringUsageDescription",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert err.count("ERROR:") == 1, err
    assert "no Info.plist could be read" in err


def test_the_required_keys_are_printed_not_only_judged(mod, tmp_path, capsys):
    raw = _plist_with(_INPUT_MONITORING) + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    mod.main([str(dmg), "--require-key", "NSInputMonitoringUsageDescription"])
    out = capsys.readouterr().out
    assert "NSInputMonitoringUsageDescription" in out
    assert "Watches the dictation key." in out


# --- --require-keys-from-spec ---------------------------------------------


def test_the_real_spec_yields_the_permissions_the_app_actually_needs(mod):
    """Run against `packaging/macos/yazses.spec` itself, not a fabricated one.

    A parser tested only on its own fixture proves the fixture. The spec is the
    file that will change, so it is the file to read.
    """
    keys = mod.usage_description_keys(ROOT / "packaging" / "macos" / "yazses.spec")
    assert "NSMicrophoneUsageDescription" in keys
    assert "NSInputMonitoringUsageDescription" in keys, (
        "the grant the hold-to-talk CGEventTap needs on macOS 10.15+ (#182)"
    )


def test_a_spec_with_no_usage_descriptions_is_an_error_not_an_empty_list(mod, tmp_path):
    """"Required nothing" must never read as "all fine" -- an extraction that
    quietly returns [] turns the whole check into a no-op that stays green."""
    spec = tmp_path / "x.spec"
    spec.write_text("app = BUNDLE(coll, name='X.app', info_plist={'CFBundleName': 'X'})\n")
    with pytest.raises(ValueError, match="no NS.*UsageDescription"):
        mod.usage_description_keys(spec)


def test_a_spec_with_no_info_plist_is_an_error(mod, tmp_path):
    spec = tmp_path / "x.spec"
    spec.write_text("a = 1\n")
    with pytest.raises(ValueError, match="no info_plist"):
        mod.usage_description_keys(spec)


def test_the_spec_route_fails_a_bundle_missing_one_of_its_permissions(mod, tmp_path):
    """End to end: the real spec's key list against a bundle that lacks one."""
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C)  # microphone only
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    spec = ROOT / "packaging" / "macos" / "yazses.spec"
    assert mod.main([str(dmg), "--require-keys-from-spec", str(spec)]) == 1


def test_the_spec_route_passes_a_bundle_that_carries_them_all(mod, tmp_path):
    spec = ROOT / "packaging" / "macos" / "yazses.spec"
    extra = b"".join(
        f"<key>{k}</key><string>YazSes needs this.</string>".encode()
        for k in mod.usage_description_keys(spec)
    )
    raw = _plist_with(extra) + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--require-keys-from-spec", str(spec)]) == 0


def test_an_unreadable_spec_fails_the_command_rather_than_raising(mod, tmp_path, capsys):
    """This runs inside a release job. A traceback there is a red build with no
    statement of what was wrong."""
    raw = INFO_PLIST + b"\0" * 64 + _macho(0x0100000C)
    dmg = tmp_path / "T.dmg"
    dmg.write_bytes(_build_dmg(raw))

    assert mod.main([str(dmg), "--require-keys-from-spec", str(tmp_path / "nope.spec")]) == 1
    assert "ERROR:" in capsys.readouterr().err
