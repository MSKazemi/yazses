#!/usr/bin/env python3
"""Offline check of the model provenance manifest (issue #694). Read-only, standard library only.

    uv run python scripts/check_model_manifest.py
    uv run python scripts/check_model_manifest.py --artifact-root .venv/lib/python3.12/site-packages

Validates ``design/hci-huggingface/model-manifest.json`` against
``design/hci-huggingface/model-manifest.schema.json``, resolves its cross-references and
``code_refs`` in this repository, and confirms that every Hub id, commit sha and hash in it is
quoted in ``design/hci-huggingface/model-provenance.md``. With ``--artifact-root`` it also
recomputes the sha256 of any listed artifact that is already on disk under that directory.

It never touches the network, never imports a Hugging Face package, never loads a model and
never downloads a file; ``tests/test_model_manifest.py`` asserts that. The logic lives in
``scripts/model_manifest.py``; this file only reads files and prints.

Exit status: 0 clean, 1 the manifest has problems, 2 a file could not be read or parsed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_manifest as mm  # noqa: E402  (sibling script, not a package)

REPO_ROOT = Path(__file__).resolve().parent.parent
HCI_DIR = REPO_ROOT / "design" / "hci-huggingface"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=HCI_DIR / "model-manifest.json")
    parser.add_argument("--schema", type=Path, default=HCI_DIR / "model-manifest.schema.json")
    parser.add_argument("--inventory", type=Path, default=HCI_DIR / "model-provenance.md")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="directory holding artifacts already on disk; their sha256 is recomputed",
    )
    args = parser.parse_args(argv)

    try:
        manifest = mm.loads_strict(args.manifest.read_text(encoding="utf-8"))
        schema = mm.loads_strict(args.schema.read_text(encoding="utf-8"))
        inventory = args.inventory.read_text(encoding="utf-8")
        errors = mm.check_all(
            manifest, schema, repo_root=args.repo_root, inventory_text=inventory
        )
    except (OSError, ValueError) as exc:  # ValueError covers JSON errors and SchemaError
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = mm.HashReport()
    if args.artifact_root is not None and not errors:
        report = mm.verify_local_hashes(manifest, args.artifact_root)
        errors += report.errors

    for line in errors:
        print(f"FAIL {line}")
    for line in report.checked:
        print(f"ok   hash verified: {line}")
    for line in report.skipped:
        print(f"skip {line}")
    if errors:
        print(f"{len(errors)} problem(s)")
        return 1
    print(f"ok: {len(manifest['models'])} model entries valid ({args.manifest.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
