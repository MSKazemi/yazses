#!/usr/bin/env python3
"""Inspect a macOS `.dmg` from Linux — no Mac, no `hdiutil`, no 7z.

    uv run python scripts/inspect-dmg.py dist/YazSes-2.18.2.dmg
    uv run python scripts/inspect-dmg.py YazSes.dmg --expect-version 2.18.2 --expect-arch arm64

Why this exists
---------------
The project is developed on Linux and released for macOS, so the `.dmg` is the one
artefact nobody here can open. That gap is not theoretical. Two defects lived in it
for a long time and both were invisible until someone looked *inside* the shipped
bundle rather than at the build that produced it:

* every `.dmg` from v0.1.3 to v2.18.0 shipped an `.app` whose ``CFBundleVersion`` was
  the literal string ``0.1.2`` — so Finder, ``mdls`` and any updater read an upgrade
  as a downgrade;
* the `.dmg` contains **no x86_64 slice at all** and cannot launch on an Intel Mac,
  while the install docs promised "Apple Silicon or Intel".

Neither is visible from CI logs: the build succeeds, the artefact is well formed, and
the wrong value is inside it. `--expect-version` and `--expect-arch` turn both into a
check that can run in a release job.

What it does
------------
Decodes the UDIF container that `create-dmg` produces (`koly` trailer → XML plist →
base64 `blkx` block tables → zlib chunks) into the raw disk image, then reads two
things out of the bytes: the bundle's ``Info.plist`` and every Mach-O header.

Deliberately stdlib-only, like `gen-sbom.py`, so it runs in a release job with
nothing installed.

Limits, stated plainly
----------------------
* Handles the **zlib (UDZO)** chunk type, which is what `create-dmg` emits by default,
  plus raw and zero-fill runs. bzip2/LZFSE/ADC chunks are skipped, so a `.dmg` built
  with other settings may decode partially — the tool says so rather than pretending.
* Reading a well-formed bundle is **not** proof the app runs. It cannot be: that needs
  a Mac. This answers "is the right thing inside the artefact", never "does it launch".
"""
from __future__ import annotations

import argparse
import base64
import collections
import plistlib
import re
import struct
import sys
import zlib
from pathlib import Path

SECTOR = 512

#: BLKX chunk entry types. See Apple's UDIF layout.
CHUNK_ZERO = 0x00000000
CHUNK_RAW = 0x00000001
CHUNK_IGNORE = 0x00000002
CHUNK_ZLIB = 0x80000005
CHUNK_TERMINATOR = 0xFFFFFFFF

#: Mach-O 64-bit little-endian magic, and the cputypes we care about.
MACHO_MAGIC = b"\xcf\xfa\xed\xfe"
FAT_MAGIC = b"\xca\xfe\xba\xbe"
CPU_TYPES = {0x0100000C: "arm64", 0x01000007: "x86_64", 0x0000000C: "arm", 0x00000007: "i386"}
#: MH_EXECUTE / MH_DYLIB / MH_BUNDLE — enough to reject random bytes that match the magic.
FILE_TYPES = {2: "MH_EXECUTE", 6: "MH_DYLIB", 8: "MH_BUNDLE"}

PLIST_KEYS = (
    "CFBundleShortVersionString",
    "CFBundleVersion",
    "CFBundleIdentifier",
    "LSMinimumSystemVersion",
    "NSMicrophoneUsageDescription",
)


def read_koly(data: bytes) -> tuple[int, int]:
    """Return (xml_offset, xml_length) from the 512-byte trailer."""
    if len(data) < SECTOR:
        raise ValueError("file is smaller than a UDIF trailer")
    trailer = data[-SECTOR:]
    if trailer[:4] != b"koly":
        raise ValueError("no 'koly' trailer — not a UDIF .dmg")
    xml_offset, xml_length = struct.unpack_from(">QQ", trailer, 0xD8)
    return xml_offset, xml_length


def inflate(data: bytes, xml_offset: int, xml_length: int) -> tuple[bytes, int]:
    """Rebuild the raw disk image. Returns (image, skipped_chunk_count)."""
    plist = plistlib.loads(data[xml_offset : xml_offset + xml_length])
    out = bytearray()
    skipped = 0

    for entry in plist["resource-fork"]["blkx"]:
        blob = entry["Data"]
        table = blob if isinstance(blob, bytes) else base64.b64decode(blob)
        if table[:4] != b"mish":
            continue
        start_sector = struct.unpack_from(">Q", table, 8)[0]
        chunk_count = struct.unpack_from(">I", table, 200)[0]

        for i in range(chunk_count):
            off = 204 + i * 40
            if off + 40 > len(table):
                break
            chunk_type, _comment, sector_number, sector_count, comp_off, comp_len = (
                struct.unpack_from(">IIQQQQ", table, off)
            )
            if chunk_type == CHUNK_TERMINATOR:
                break

            pos = (start_sector + sector_number) * SECTOR
            if len(out) < pos:
                out.extend(b"\0" * (pos - len(out)))

            if chunk_type == CHUNK_ZLIB:
                piece = zlib.decompress(data[comp_off : comp_off + comp_len])
            elif chunk_type == CHUNK_RAW:
                piece = data[comp_off : comp_off + comp_len]
            elif chunk_type in (CHUNK_ZERO, CHUNK_IGNORE):
                piece = b"\0" * (sector_count * SECTOR)
            else:
                skipped += 1
                continue
            out[pos : pos + len(piece)] = piece

    return bytes(out), skipped


def read_info_plist(image: bytes) -> dict[str, str]:
    """Pull the app bundle's Info.plist values straight out of the raw image.

    The plist is XML on disk, so the values are greppable without walking HFS+.
    """
    found: dict[str, str] = {}
    for key in PLIST_KEYS:
        m = re.search(
            rf"<key>{key}</key>\s*<string>([^<]*)</string>".encode(), image, re.S
        )
        if m:
            found[key] = m.group(1).decode("utf-8", errors="replace").strip()
    return found


def scan_macho(image: bytes) -> tuple[collections.Counter, int]:
    """Count Mach-O slices by CPU type. Returns (counter, fat_header_count)."""
    tally: collections.Counter = collections.Counter()
    for m in re.finditer(re.escape(MACHO_MAGIC), image):
        off = m.start()
        if off + 16 > len(image):
            continue
        _magic, cputype, _cpusub, filetype = struct.unpack_from("<IIII", image, off)
        name = CPU_TYPES.get(cputype)
        # Both filters matter: random bytes match a 4-byte magic surprisingly often.
        if name is None or filetype not in FILE_TYPES:
            continue
        tally[name] += 1
    return tally, len(re.findall(re.escape(FAT_MAGIC), image))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("dmg", type=Path)
    ap.add_argument("--expect-version", help="fail unless CFBundleShortVersionString matches")
    ap.add_argument(
        "--expect-arch",
        choices=sorted(set(CPU_TYPES.values())),
        help="fail unless every Mach-O slice is this architecture",
    )
    args = ap.parse_args(argv)

    if not args.dmg.is_file():
        print(f"ERROR: no such file: {args.dmg}", file=sys.stderr)
        return 1

    data = args.dmg.read_bytes()
    try:
        image, skipped = inflate(data, *read_koly(data))
    except (ValueError, KeyError, zlib.error) as exc:
        print(f"ERROR: could not decode {args.dmg.name}: {exc}", file=sys.stderr)
        return 1

    print(f"{args.dmg.name}: {len(data):,} bytes compressed -> {len(image):,} raw")
    if skipped:
        print(
            f"  WARNING: {skipped} chunk(s) used a compression this tool does not "
            "decode (not zlib/raw); results may be incomplete"
        )

    info = read_info_plist(image)
    if info:
        print("\nInfo.plist")
        for key in PLIST_KEYS:
            if key in info:
                value = info[key]
                shown = value if len(value) <= 60 else value[:57] + "..."
                print(f"  {key:<30} {shown}")
    else:
        print("\n  WARNING: no Info.plist values found")

    tally, fat = scan_macho(image)
    print("\nMach-O")
    print(f"  slices by CPU type             {dict(tally) or '{}'}")
    print(f"  universal/fat headers          {fat}")

    problems: list[str] = []
    if args.expect_version:
        actual = info.get("CFBundleShortVersionString")
        if actual != args.expect_version:
            problems.append(
                f"CFBundleShortVersionString is {actual!r}, expected "
                f"{args.expect_version!r}"
            )
    if args.expect_arch:
        wrong = {a: n for a, n in tally.items() if a != args.expect_arch}
        if wrong:
            problems.append(f"unexpected architectures present: {wrong}")
        if not tally.get(args.expect_arch):
            problems.append(f"no {args.expect_arch} slice found at all")

    if problems:
        print()
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1

    if args.expect_version or args.expect_arch:
        print("\nOK — the bundle matches what was expected.")
        print("(Well-formed is not the same as running. That still needs a Mac.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
