#!/usr/bin/env python3
"""Validate the example configs in `examples/`.

    uv run python scripts/check-app-profile.py
    uv run python scripts/check-app-profile.py --file examples/config.kitty.toml

The failure this exists to catch is silent. YazSes's config loader is deliberately total —
`configcheck.py` drops unknown keys and falls back to documented defaults rather than
refusing to start (issue #52). That is right for a user's own config and wrong for a
shipped example: a typo'd key in `examples/` does nothing, reports no error, and the
contributor who copied it concludes the feature is broken.

So this compares every key against the real config dataclasses in `src/yazses/config.py`,
which are the only authority on what exists. It also rejects a personal path, because
people write these by copying their own working config.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from campaign_preflight import scan_personal_data  # noqa: E402

EXAMPLES = ROOT / "examples"


def known_schema() -> dict[str, set[str]]:
    """`{section: {key, ...}}` built from the config dataclasses themselves.

    Derived, never hand-listed — a hand-copied key list is one more thing to drift.
    """
    import dataclasses

    from yazses import config as cfg

    schema: dict[str, set[str]] = {}
    for field in dataclasses.fields(cfg.Config):
        section_type = field.type
        if isinstance(section_type, str):  # postponed annotations
            section_type = getattr(cfg, section_type, None)
        if section_type is None or not dataclasses.is_dataclass(section_type):
            continue
        schema[field.name] = {f.name for f in dataclasses.fields(section_type)}
    return schema


def check_config(text: str, *, name: str, schema: dict[str, set[str]]) -> list[str]:
    """Every problem with one example config."""
    problems: list[str] = []
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [f"{name}: not valid TOML — {exc}"]

    for section, values in parsed.items():
        if section not in schema:
            problems.append(
                f"{name}: [{section}] is not a real config section. The loader silently "
                f"drops it, so this example would do nothing. Known: {sorted(schema)}"
            )
            continue
        if not isinstance(values, dict):
            problems.append(f"{name}: [{section}] must be a table")
            continue
        for key in values:
            if key not in schema[section]:
                problems.append(
                    f"{name}: [{section}] {key} is not a real key — the loader drops it "
                    "silently, so anyone copying this example gets nothing. "
                    f"Known: {sorted(schema[section])}"
                )

    for label, snippet, hint in scan_personal_data(text):
        problems.append(f"{name}: {label} — {snippet} — {hint}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, help="one config; default is every examples/*.toml")
    args = ap.parse_args(argv)

    files = [args.file] if args.file else sorted(EXAMPLES.glob("*.toml"))
    if not files:
        print("no example configs found", file=sys.stderr)
        return 1

    schema = known_schema()
    problems: list[str] = []
    for path in files:
        problems += check_config(
            path.read_text(encoding="utf-8"), name=path.name, schema=schema
        )

    if problems:
        print(f"✗ {len(problems)} problem(s) across {len(files)} file(s):\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"✓ {len(files)} example config(s) valid against src/yazses/config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
