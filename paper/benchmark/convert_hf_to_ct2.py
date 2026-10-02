#!/usr/bin/env python3
"""Convert a Hugging Face Whisper checkpoint into a ctranslate2 model directory.

FA-05 measures models faster-whisper cannot download by name — every Persian
fine-tune in the candidate set ships as HF weights, not a CT2 snapshot — and the
issue is explicit about what that costs:

    Any non-CT2 checkpoint must be converted before measurement, with the
    conversion procedure pinned in provenance and the MANIFEST entry as well as
    the source repo, revision, and license recorded per candidate.

So this script does two things: converts, and **records what the conversion
was** — converter versions, source revision, per-file digests, the exact command.
The output's `conversion.json` sidecar is what a result's provenance stamps, which
is what makes a fine-tune's number auditable later. Without it, a CT2 directory is
an anonymous pile of weights and the benchmark inherits the defect it exists to
avoid: a claim that cannot be traced to a procedure.

The module is stdlib-only at import time and runs the heavy parts
(huggingface_hub, ct2-transformers-converter, both of which need torch) in a
**separate interpreter** whose path is passed in. That is deliberate: torch is
200 MB+ and has no business in the project venv or the CI harness job, and a
contract test must not need it. The tests here pin the parts that carry the risk
— which files get fetched, what refuses to overwrite, what the sidecar promises —
and the converter itself is a black box invoked by argv.

ROOT FILES ONLY, EVER: the first attempt at fetching a candidate used a snapshot
glob of `*.bin` and pulled eight mid-training `checkpoint-*/pytorch_model.bin`
into the cache — 6.5 GB of weights nobody would measure, on a machine with 66 GB
free and a decode running. `root_files()` is an allowlist for that reason and is
tested for it.

Usage:
    python convert_hf_to_ct2.py --repo steja/whisper-small-persian \
        --revision 8c600b6b69f552730abab77a6a46311d673ea584 \
        --out ~/fa_matrix/ct2_steja_small --python ~/fa_matrix/convert_venv/bin/python
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

#: Sidecar schema. Bump on any change to what `conversion()` records; a result
#: provenance that names version 1 must stay interpretable when version 2 lands.
CONVERSION_SCHEMA_VERSION = 1

#: The files a faster-whisper/CT2 conversion actually needs, at the repository
#: ROOT only. `pytorch_model.bin` is what a HF Whisper checkpoint ships as;
#: `.safetensors` is the modern equivalent and `weights.bin` what some repos use.
#: Anything matched here is fetched by exact name — never by pattern, never from
#: a `checkpoint-*/` subdirectory. See the module docstring for why.
#: The one apparent exception is `_SHARD_RE` below: a repo whose weights exceed
#: safetensors' 5 GB single-file ceiling ships `model-00001-of-00002.safetensors`
#: shards plus an index. That naming is a format contract (five digits, `-of-`,
#: total), not a glob — it still cannot spell `checkpoint-2500/…`, and the index
#: pins which shards belong to the model. Confirmed against the real tree of
#: nezamisafa/whisper-persian-v4 (15 root files, two shards) which the previous
#: allowlist silently excluded, breaking conversion of any large-v3 fine-tune.
ROOT_FILE_PATTERNS = (
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.json",
    "merges.txt",
    "normalizer.json",
    "added_tokens.json",
    "special_tokens_map.json",
    "pytorch_model.bin",
    "pytorch_model.bin.index.json",
    "model.safetensors",
    "model.safetensors.index.json",
    "weights.bin",
)


#: Weight shards from the safetensors multi-file layout: five digits, ``-of-``,
#: total, then the extension. Anchored both ends so it cannot match anything
#: outside the naming convention — `checkpoint-2500.safetensors` is not spelled
#: this way, and a subdir path never reaches this matcher at all.
_SHARD_RE = re.compile(r"model-\d{5}-of-\d{5}\.safetensors\Z")


def root_files(names) -> list[str]:
    """The repository-root files a conversion needs, from a listing of paths.

    *names* is anything path-like: a HF tree API listing, a `snapshot_download`
    result, or a plain list of relative paths. Exact-root-name matching only —
    `checkpoint-2500/pytorch_model.bin` is a checkpoint of a partially trained
    model, not the model, and fetching it is 967 MB of nothing.

    Returns sorted so the sidecar digest map is reproducible across platforms
    whose directory listings disagree on order.
    """
    out = []
    for name in names:
        name = str(name).replace("\\", "/")
        if "/" in name or name.startswith("."):
            continue
        if name in ROOT_FILE_PATTERNS or _SHARD_RE.match(name):
            out.append(name)
    return sorted(set(out))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _remote_listing(repo: str, revision: str, python: str) -> list[str]:
    """Paths in *repo* at *revision*, asked of the converter interpreter.

    Runs the HF Hub API through *python* rather than importing it here: this
    module stays stdlib-only so CI can import and test it without torch.
    """
    code = (
        "import json,sys;"
        "from huggingface_hub import list_repo_files;"
        f"print(json.dumps(list_repo_files({repo!r}, revision={revision!r})))"
    )
    r = subprocess.run([python, "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(
            f"could not list {repo}@{revision[:12]}: {r.stderr.strip()[-400:]}"
        )
    return json.loads(r.stdout.strip().splitlines()[-1])


def _tool_versions(python: str) -> dict:
    """Versions of everything that can change the output bytes.

    A CT2 directory is a function of the source weights AND the converter, so a
    number traceable to 'ctranslate2 (some version)' is not traceable at all.
    torch and transformers belong in the record too: the converter loads a
    `WhisperModel` through transformers, and its weight layout assumptions moved
    once already (the `safetensors` shard change) — that is exactly the kind of
    thing a provenance field exists to catch after the fact.
    """
    # A real script, not a semicolon chain: `def` is a compound statement and
    # cannot follow `;`, which is exactly how the first version of this shipped
    # a SyntaxError the stubbed contract test could not see. The test doubles
    # for _tool_versions exist so CI never imports torch — they do not license
    # this function going unexercised, so it is run for real in the FA-05 runs.
    code = (
        "import json\n"
        "def v(m):\n"
        "    try:\n"
        "        mod = __import__(m)\n"
        "        return getattr(mod, '__version__', '?')\n"
        "    except Exception:\n"
        "        return None\n"
        "print(json.dumps({k: v(k) for k in "
        "['ctranslate2', 'transformers', 'torch', 'huggingface_hub']}))\n"
    )
    r = subprocess.run([python, "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[-200:]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def convert(
    repo: str,
    revision: str,
    out_dir: Path,
    python: str,
    quantization: str = "int8",
) -> dict:
    """Convert *repo*@*revision* into a CT2 directory and write its sidecar.

    Refuses an existing *out_dir* unless empty: a converted directory is not
    idempotent in the sense a reader assumes (a half-finished conversion leaves
    a valid-looking `model.bin` from an older pass), and silently mixing two
    conversions in one path is the archive-corrupting kind of mistake.
    """
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(
            f"refusing to convert into a non-empty directory: {out_dir}\n"
            "Remove it or choose another path — a sidecar and weights from "
            "different passes in one directory cannot be told apart."
        )

    listing = _remote_listing(repo, revision, python)
    fetched = root_files(listing)
    missing = [f for f in ("config.json",) if f not in fetched]
    if missing:
        raise SystemExit(
            f"{repo}@{revision[:12]} has no {'/'.join(missing)} at its root "
            f"(saw: {fetched}); this is not a convertible HF checkpoint."
        )

    started = time.time()
    cmd = [
        python, "-m", "ctranslate2.converters.transformers",
        "--model", f"{repo}",
        "--revision", revision,
        "--output_dir", str(out_dir),
        "--quantization", quantization,
    ]
    # The converter CLI's real entry point is the console script; -m is the
    # same module invoked by path so the exact argv can be recorded verbatim.
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(
            "conversion failed:\n" + (r.stdout + r.stderr)[-2000:]
        )

    sidecar = {
        "conversion_schema": CONVERSION_SCHEMA_VERSION,
        "source_repo": repo,
        "source_revision": revision,
        "quantization": quantization,
        "root_files_fetched": fetched,
        "tools": _tool_versions(python),
        "command": " ".join(cmd),
        "seconds": round(time.time() - started, 1),
    }
    # Digest every output file. `model.bin` alone would miss a tokenizer or
    # config swap, and the config is part of what defines the decode.
    sidecar["output_sha256"] = {
        p.name: sha256_file(p)
        for p in sorted(out_dir.iterdir())
        if p.is_file() and p.name != "conversion.json"
    }
    (out_dir / "conversion.json").write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return sidecar


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter with torch+transformers+ctranslate2 installed "
        "(the converter runs there, not here)",
    )
    ap.add_argument("--quantization", default="int8")
    a = ap.parse_args(argv)
    sidecar = convert(a.repo, a.revision, a.out, a.python, a.quantization)
    print(
        f"converted {sidecar['source_repo']}@{sidecar['source_revision'][:12]} "
        f"-> {a.out} ({sidecar['seconds']}s, {len(sidecar['output_sha256'])} files)"
    )
    print(f"sidecar: {a.out / 'conversion.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
