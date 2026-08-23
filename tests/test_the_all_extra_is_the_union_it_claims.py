"""`yazses[all]` promised everything and quietly shipped eight extras less.

`[project.optional-dependencies].all` is a hand-written list of requirement strings.
Two separate places in this repo already treated it as a computed aggregate:

    scripts/check_dependency_budget.py   "all": "aggregate of every other extra; its
                                                 members are checked individually"
    tests/test_feature_pins_match_the_extras.py   if name == "all":  # an aggregate

Both exemptions are sound *given* the relationship they name — members checked through
their owning extra really are checked, and a pin restated in `all` really would be a
duplicate statement rather than an independent one. Neither computed it. When the
relationship stopped holding, both stayed green: on 2026-08-23 `all` was missing nine
requirements from eight extras, so an install that asked for everything got no denoise,
no Chinese script normalisation, no Silero VAD, no Moonshine, no EMG band, no MCP agent
and no pyannote diarization.

The direction matters and both are checked here:

* **union minus `all`** is the silent-omission direction — a new extra is added and
  `all` is not updated, which is exactly how this happened.
* **`all` minus union** is the drift direction — `all` restates `PySide6>=6.11.1` by
  hand, so bumping `overlay` to a newer pin leaves `all` resolving the old one with
  nothing to say so.

The omissions were not a resolver constraint: `pyproject.toml` declares no `conflicts`,
and `uv.lock` is a single resolution containing every one of the nine, so the extras
provably co-resolve.
"""
from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Extras deliberately left out of `all`, each with the reason stated in pyproject.toml
#: beside the list itself. Keep the two in step — the reason is the point, not the name.
EXCLUDED = frozenset({"voiceprint-resemblyzer"})


def _extras() -> dict[str, list[str]]:
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(raw)["project"]["optional-dependencies"]


def _union() -> dict[str, list[str]]:
    """Requirement string -> the extras that state it, excluding `all` itself."""
    out: dict[str, list[str]] = {}
    for name, reqs in _extras().items():
        if name == "all" or name in EXCLUDED:
            continue
        for req in reqs:
            out.setdefault(req, []).append(name)
    return out


def test_there_is_something_to_check():
    """A set-difference guard is green over two empty sets. Prove neither is empty."""
    extras = _extras()
    assert "all" in extras, "the `all` extra is gone; this guard now proves nothing"
    assert len(extras) >= 20, extras.keys()
    assert len(extras["all"]) >= 20, "`all` is suspiciously short"
    assert len(_union()) >= 20, "the union is empty — the reader is broken"


def test_every_excluded_extra_still_exists():
    """An exclusion naming a deleted extra silently widens what `all` may omit."""
    unknown = sorted(EXCLUDED - set(_extras()))
    assert not unknown, f"{unknown} is excluded from `all` but is not an extra any more"


def test_the_exclusions_are_explained_where_the_list_lives():
    """The reason has to sit beside `all`, not only in this test.

    A reader deciding whether to add a dependency to `all` is looking at pyproject.toml.
    """
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    head = raw[: raw.index("\nall = [")]
    block = head[head.rindex("\n# \"Just give me the lot") :]
    # Anchored to the bullet, not to the name: the block mentions
    # `yazses[all,voiceprint-resemblyzer]` as the way to opt back in, so a bare
    # substring search stays green when the reason itself is deleted.
    bullets = {
        line.strip().lstrip("# ").split(" -- ")[0].strip()
        for line in block.splitlines()
        if line.startswith("#   ") and " -- " in line
    }
    for name in EXCLUDED:
        assert name in bullets, (
            f"`{name}` is excluded from `all`, but the comment above `all` states no "
            f"`#   {name} -- <reason>` bullet for it. The reason is the point: it is "
            "what the next person reads when deciding whether to add a dependency."
        )


def test_all_contains_every_other_extras_requirements():
    """The silent-omission direction: an extra was added and `all` was not updated."""
    union = _union()
    missing = sorted(set(union) - set(_extras()["all"]))
    assert not missing, (
        "`yazses[all]` does not install "
        + ", ".join(f"{req} (from {'/'.join(union[req])})" for req in missing)
        + " — add it to `all`, or add its extra to EXCLUDED here *and* to the comment "
        "above `all` in pyproject.toml with a reason."
    )


def test_all_states_no_pin_of_its_own():
    """The drift direction: `all` copies pins by hand, so it can fall behind one."""
    union = _union()
    orphans = sorted(set(_extras()["all"]) - set(union))
    assert not orphans, (
        f"{orphans} appears in `all` and in no other extra. Either a pin was bumped in "
        "one place only — `all` now resolves a different version than the extra that "
        "owns it — or `all` grew a dependency that belongs in a named extra."
    )


def test_the_excluded_extra_loses_no_capability():
    """`voiceprint-resemblyzer` is an alternative backend, not a missing feature.

    Excluding an extra from `all` is only acceptable while the seam it serves still has
    a backend inside `all`. `[voiceprint] backend` defaults to ECAPA via `speechbrain`;
    if that ever left `all`, asking for everything would leave speaker embedding with no
    backend at all and this exclusion would stop being harmless.
    """
    everything = " ".join(_extras()["all"])
    assert "speechbrain" in everything, (
        "`voiceprint-resemblyzer` is excluded from `all` on the grounds that the default "
        "voiceprint backend is already there — and now it is not"
    )
