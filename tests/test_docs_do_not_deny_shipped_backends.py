"""Docs and help text must not say a *backend* is unshipped after it has shipped.

`test_docs_do_not_deny_wired_features.py` guards the same failure one level up, and
could not see this one: it keys on capability slugs from `system/features.py`, and a
pluggable backend is not a capability. It is a **config value** — `[recimport]
backend = "pyannote"` — so nothing in the feature registry ever mentions it and no
guard asked whether the prose about it was still true.

The instance this was written for: the `pyannote` diarization adapter shipped in
90c801f (2026-08-13) behind the `diarization-pyannote` extra, and five live surfaces
went on telling users it was "not shipped in this build" — the `--min-speakers`
option help, the runtime note that fires when you pass it, `system/depsize.py` (which
cited `system/backends.py` as its authority while `system/backends.py` said the
opposite), the transcribe tutorial, and `CLAUDE.md`. The consequence is specific: a
user who needs a lower speaker bound is told no backend provides one, so they never
install the extra that does.

The shipped set is *derived*, never listed here: a backend is shipped when the
adapter module named at its `probe_backend` call site exists in the tree. Shipping an
adapter therefore arms this guard the same day, and deleting one disarms it, with no
list to remember — the failure mode of a hand-written set is itself recorded twice in
this suite.

Release notes are archives of what a version said and are skipped. If a legitimate
sentence trips this, it is ambiguous to a reader too; rewording is the fix.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"
DOCS = ROOT / "docs"

#: Release notes describe what a version did at the time and must not be rewritten.
SKIP_DIRS = {"releases"}

#: Phrasings that assert an adapter is absent from the build, as opposed to its
#: optional dependency being absent -- a distinction `system/backends.py` exists to
#: make, and the one that decides whether installing anything can help.
DENIALS = re.compile(
    r"(not shipped|does not ship|doesn't ship|never shipped|unshipped|"
    r"not implemented in this build|no adapter)",
    re.IGNORECASE,
)


def _shipped_backends() -> dict[str, str]:
    """Map backend name -> adapter module, for adapters that exist in the tree.

    Read out of the `probe_backend` call sites and the adapter tables beside them
    rather than declared here. Two shapes occur: a literal `adapter="yazses.x.y"`
    keyword, and a `{name: (adapter, requires, extra)}` table the call site indexes.
    """
    found: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            # {"pyannote": ("yazses.recimport.pyannote_backend", (...), "extra")}
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                        continue
                    if not isinstance(value, ast.Tuple) or not value.elts:
                        continue
                    first = value.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                            and first.value.startswith("yazses."):
                        found[key.value] = first.value
            # probe_backend("spectral", adapter="yazses.denoise.spectral", ...)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "probe_backend":
                adapter = next(
                    (kw.value.value for kw in node.keywords
                     if kw.arg == "adapter" and isinstance(kw.value, ast.Constant)),
                    None,
                )
                name = (node.args[0].value
                        if node.args and isinstance(node.args[0], ast.Constant)
                        else None)
                if adapter and isinstance(name, str):
                    found[name] = adapter
    return {
        name: adapter for name, adapter in found.items()
        if (SRC.parent / (adapter.replace(".", "/") + ".py")).is_file()
    }


def _live_files() -> list[Path]:
    docs = [p for p in DOCS.rglob("*.md")
            if not SKIP_DIRS.intersection(p.relative_to(DOCS).parts)]
    return sorted(docs + list(SRC.rglob("*.py")))


def test_the_shipped_set_is_derived_and_not_empty() -> None:
    """Guard the guard: an empty set would make every check below vacuous."""
    shipped = _shipped_backends()
    assert shipped, "no shipped backend adapters found -- the AST walk stopped working"
    # The two this guard was written for. Named as a canary, not as the list: if
    # either is genuinely removed, this line is the reminder to update the docs too.
    assert "pyannote" in shipped, shipped
    assert "resemblyzer" in shipped, shipped


def test_an_unshipped_backend_is_still_allowed_to_be_called_unshipped() -> None:
    """`deepfilternet` has no adapter and cannot get one (it caps numpy<2.0).

    Saying so is correct and must stay sayable, or the guard would push the docs
    into a second, opposite falsehood.
    """
    assert "deepfilternet" not in _shipped_backends()


def test_no_live_surface_denies_a_shipped_backend() -> None:
    shipped = _shipped_backends()
    offences: list[str] = []
    for path in _live_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not DENIALS.search(line):
                continue
            for name in shipped:
                if re.search(rf"\b{re.escape(name)}\b", line):
                    offences.append(
                        f"{path.relative_to(ROOT)}:{number} says a shipped backend "
                        f"({name}, adapter {shipped[name]}) is not shipped:\n    "
                        f"{line.strip()}"
                    )
    assert not offences, (
        "these lines deny a backend this build ships. Installing the named extra is "
        "what fixes an unavailable backend; telling the user nothing can is what "
        "stops them trying.\n\n" + "\n".join(offences)
    )
