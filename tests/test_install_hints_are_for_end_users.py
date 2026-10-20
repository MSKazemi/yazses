"""No string under src/ tells an end user to run a source-checkout install command.

`uv sync --extra <x>` only does anything inside a clone of this repository; for
everyone who installed YazSes with uv tool, pipx, pip, a snap or a bundle it fails or
syncs some other project. `pip install 'yazses[x]'` is subtler and just as wrong: on
a uv tool or pipx install it installs into a different environment (or is dropped by
the next upgrade). Eight messages said one or the other. They now get their remedy
from `system/remedy.install_hint`, and this test keeps it that way by scanning every
string literal under `src/` — docstrings included, since a Typer command's docstring
*is* its `--help` text — through the AST.

The allowlist below is the only exception, and each entry says why it is not a
user-facing instruction. An entry that no longer matches fails too, so the list
cannot quietly outlive what it excused.

Two companion checks close the loop the hand-written messages left open:

* every `install_hint(...)` call names an extra `pyproject.toml` declares, and a
  capability whose registry packages are part of that extra (or the helper would
  silently fall back and the pairing would be dead code);
* every `yazses features enable|install <slug>` written anywhere under `src/` names
  a slug that exists. Two did not (`voiceprint`, `emg-band`): both commands answered
  "Unknown feature".
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"

_FORBIDDEN = re.compile(r"uv sync --extra|pip install\s+[\"']?yazses\[")

#: (path relative to src/yazses, a fragment of the literal) -> why it is allowed.
ALLOWED: dict[tuple[str, str], str] = {
    ("system/dormant.py", "naming a developer command such as"):
        "module docstring narrating the defect this module fixed; not an instruction",
    ("core/daemon.py", "some naming `uv sync --extra"):
        "method docstring narrating the old factory messages; not an instruction",
    ("system/install_txn.py", "for `uv sync --extra`"):
        "developer docstring: the source-checkout channel, where syncing IS right",
    ("meeting/silero_vad.py", "resolves to **25 distributions"):
        "module docstring recording a dependency-closure measurement for developers",
    ("platform/linux/tray.py", "there is no Pillow"):
        "method docstring listing install formats that lack Pillow; not an instruction",
}


def _strings(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _sources() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    # A guard that iterates is green on an empty collection: prove it saw the tree.
    assert len(files) > 300, f"only {len(files)} source files found under {SRC}"
    return files


def _parsed():
    for path in _sources():
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_user_facing_string_names_a_source_checkout_install():
    offenders: list[str] = []
    used: set[tuple[str, str]] = set()
    for path, tree in _parsed():
        rel = path.relative_to(SRC).as_posix()
        for raw in _strings(tree):
            # Whitespace collapsed: a docstring wraps the command across lines.
            text = " ".join(raw.split())
            hit = _FORBIDDEN.search(text)
            if hit is None:
                continue
            key = next((k for k in ALLOWED if k[0] == rel and k[1] in text), None)
            if key is not None:
                used.add(key)
                continue
            offenders.append(f"{rel}: {text[max(0, hit.start() - 60):hit.end() + 30]!r}")
    assert not offenders, (
        "A user-facing string tells the user to run a source-checkout install. Derive "
        "the remedy with `yazses.system.remedy.install_hint(<extra>, feature=...)` "
        "instead, or — for a developer-only docstring — add it to ALLOWED with the "
        "reason:\n  " + "\n  ".join(offenders)
    )
    stale = sorted(set(ALLOWED) - used)
    assert not stale, f"ALLOWED entries that no longer match anything: {stale}"


def test_the_scan_sees_a_planted_offender():
    """Red-green for the scanner itself, on an f-string and on a docstring."""
    planted = ast.parse(
        'def f():\n    """Install with `uv sync --extra tts`."""\n'
        '    return f"run: pip install \'yazses[{x}]\'"\n'
    )
    hits = [t for t in _strings(planted) if _FORBIDDEN.search(t)]
    assert len(hits) == 2


def _extras() -> dict[str, set[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for name, reqs in data["project"]["optional-dependencies"].items():
        out[name] = {
            re.sub(r"[-_.]+", "-", re.split(r"[\[<>=!~; ]", r, maxsplit=1)[0]).lower()
            for r in reqs
        }
    return out


def _canonical(spec: str) -> str:
    return re.sub(r"[-_.]+", "-", re.split(r"[\[<>=!~; ]", spec, maxsplit=1)[0]).lower()


def _hint_calls():
    for path, tree in _parsed():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name != "install_hint" or not node.args:
                continue
            extra = node.args[0]
            feature = next((k.value for k in node.keywords if k.arg == "feature"), None)
            yield path.relative_to(SRC).as_posix(), extra, feature


def test_every_install_hint_call_names_a_real_extra_and_a_matching_capability():
    from yazses.system.features import _registry

    extras = _extras()
    rows = {d.slug: d for d in _registry()}
    calls = list(_hint_calls())
    # The tray, settings, overlay, notes, BLE x2, EMG band and the voiceprint message.
    assert len(calls) >= 8, f"expected the converted call sites, found {calls}"
    problems: list[str] = []
    for rel, extra_node, feature_node in calls:
        if not isinstance(extra_node, ast.Constant) or not isinstance(extra_node.value, str):
            continue  # a computed extra (voiceprint backend) is checked by its own test
        extra = extra_node.value
        if extra not in extras:
            problems.append(f"{rel}: {extra!r} is not a pyproject extra")
            continue
        if feature_node is None:
            continue
        if not isinstance(feature_node, ast.Constant):
            problems.append(f"{rel}: feature= must be a literal slug")
            continue
        row = rows.get(feature_node.value)
        if row is None:
            problems.append(f"{rel}: {feature_node.value!r} is not a capability")
            continue
        mine = {_canonical(p) for p in row.pip_packages}
        if not mine or not mine <= extras[extra]:
            problems.append(
                f"{rel}: {row.slug!r} installs {sorted(mine)}, not part of the "
                f"{extra!r} extra {sorted(extras[extra])}"
            )
    assert not problems, "\n".join(problems)


def test_the_voiceprint_backends_map_to_real_extras_the_cocktail_slug_can_cover():
    from yazses.system.features import _registry
    from yazses.voiceprint.factory import BACKEND_EXTRAS

    extras = _extras()
    cocktail = next(d for d in _registry() if d.slug == "cocktail")
    for backend, extra in BACKEND_EXTRAS.items():
        assert extra in extras, f"{backend}: {extra!r} is not a pyproject extra"
    # The default backend is the one the Cocktail Filter's registry entry installs.
    assert {_canonical(p) for p in cocktail.pip_packages} <= extras[BACKEND_EXTRAS["ecapa"]]


_NAMED_SLUG = re.compile(r"yazses features (?:enable|install) ([a-z][a-z0-9_-]*)")


def test_every_slug_a_message_tells_the_user_to_enable_exists():
    from yazses.system.features import _registry

    slugs = {d.slug for d in _registry()}
    bad: list[str] = []
    seen = 0
    for path, tree in _parsed():
        for text in _strings(tree):
            for m in _NAMED_SLUG.finditer(text):
                seen += 1
                if m.group(1) not in slugs:
                    bad.append(f"{path.relative_to(SRC).as_posix()}: {m.group(0)!r}")
    assert seen > 10, "the scan found almost no `features enable` text — is it reading src?"
    assert not bad, "These commands answer 'Unknown feature':\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("module", ["settingsui/app.py", "overlay/app.py",
                                    "platform/linux/tray.py"])
def test_the_qt_refusals_derive_their_command(module):
    text = (SRC / module).read_text(encoding="utf-8")
    assert "install_hint(" in text, f"{module} no longer derives its install command"
