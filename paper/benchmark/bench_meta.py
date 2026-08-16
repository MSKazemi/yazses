"""Meta metrics: dysfluency gate, model on-disk footprint, engineering scale.

- Dysfluency-Friendly Mode gate (ADR-015): re-computes false-collapse rate on clean
  control text and recall on labelled dysfluency spans, reusing the shipping
  _collapse_dysfluencies() and the same fixture the CI gate uses.
- Model footprint: size on disk of each faster-whisper model in the HF cache.
- Engineering scale: test-file count, test-function count, ADR count.
"""
from __future__ import annotations

import json

from _common import REPO_ROOT


def _dysfluency_gate() -> dict:
    from yazses.config import DisfluencyConfig
    from yazses.stt.filters.disfluency import _collapse_dysfluencies

    data = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "disfluency" / "dysfluency_eval.json").read_text()
    )
    cfg = DisfluencyConfig(collapse_repetitions=True, collapse_prolongations=True)
    controls = data["clean_control"]
    changed = [s for s in controls if _collapse_dysfluencies(s, cfg) != s]
    cases = data["dysfluent"]
    hits = [c for c in cases if _collapse_dysfluencies(c["in"], cfg) == c["out"]]
    return {
        "n_clean_control": len(controls),
        "n_dysfluent": len(cases),
        "false_collapse_rate_pct": round(100 * len(changed) / len(controls), 2),
        "recall_pct": round(100 * len(hits) / len(cases), 2),
        "pre_registered_gate": "false-collapse < 2% AND recall >= 60% (ADR-015 LOFA-1)",
    }


def _model_footprint() -> dict:
    from huggingface_hub import scan_cache_dir

    wanted = {"tiny.en", "base.en", "small.en"}
    sizes = {}
    try:
        cache = scan_cache_dir()
        for repo in cache.repos:
            # repo ids look like Systran/faster-whisper-small.en
            for w in wanted:
                if repo.repo_id.endswith(f"faster-whisper-{w}"):
                    sizes[w] = round(repo.size_on_disk / 1e6, 1)  # MB
    except Exception as e:  # pragma: no cover
        sizes["_error"] = str(e)
    return sizes


def _engineering_scale() -> dict:
    tests_dir = REPO_ROOT / "tests"
    test_files = list(tests_dir.rglob("test_*.py"))
    n_funcs = 0
    for f in test_files:
        try:
            n_funcs += sum(
                1 for ln in f.read_text().splitlines() if ln.lstrip().startswith("def test_")
            )
        except Exception:  # pragma: no cover
            pass
    adr_files = list((REPO_ROOT / "design" / "adr").glob("adr-*.md"))
    # source lines of code (src/yazses only)
    sloc = 0
    for f in (REPO_ROOT / "src" / "yazses").rglob("*.py"):
        try:
            sloc += sum(1 for _ in f.read_text().splitlines())
        except Exception:  # pragma: no cover
            pass
    return {
        "test_files": len(test_files),
        "test_functions": n_funcs,
        "adr_files": len(adr_files),
        "src_python_files": len(list((REPO_ROOT / "src" / "yazses").rglob("*.py"))),
        "src_lines": sloc,
    }


def run() -> dict:
    out = {
        "dysfluency_gate": _dysfluency_gate(),
        "model_footprint_mb": _model_footprint(),
        "engineering_scale": _engineering_scale(),
    }
    print(f"[meta] dysfluency: {out['dysfluency_gate']}", flush=True)
    print(f"[meta] footprint MB: {out['model_footprint_mb']}", flush=True)
    print(f"[meta] scale: {out['engineering_scale']}", flush=True)
    return out


if __name__ == "__main__":
    from _common import write_result

    write_result("meta", run())
