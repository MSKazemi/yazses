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


def _split(req: str) -> tuple[str, str]:
    """`"mediapipe>=0.10.35; sys_platform != 'darwin'"` -> the requirement and its marker.

    `all` is allowed to carry a marker its owning extra does not, and only in one
    direction -- see `test_all_may_narrow_a_requirement_to_fewer_platforms`. Comparing
    the raw strings would forbid that; comparing only the requirement half would stop
    noticing a pin bumped in one place and not the other. So the two halves are checked
    separately.
    """
    req, _, marker = req.partition(";")
    return req.strip(), marker.strip()


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
    in_all = {_split(r)[0] for r in _extras()["all"]}
    missing = sorted(req for req in union if _split(req)[0] not in in_all)
    assert not missing, (
        "`yazses[all]` does not install "
        + ", ".join(f"{req} (from {'/'.join(union[req])})" for req in missing)
        + " — add it to `all`, or add its extra to EXCLUDED here *and* to the comment "
        "above `all` in pyproject.toml with a reason."
    )


def test_all_states_no_pin_of_its_own():
    """The drift direction: `all` copies pins by hand, so it can fall behind one."""
    union = _union()
    owned = {_split(r)[0] for r in union}
    orphans = sorted(r for r in _extras()["all"] if _split(r)[0] not in owned)
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


# --- `all` may narrow, never widen ---------------------------------------------------
#
# Three dependencies have stopped publishing macOS x86_64 wheels and cannot be resolved
# there at any version: `mediapipe` after 0.10.21, and `torch` -- which `pyannote.audio`
# pulls in -- after 2.2.2. Before this, `uv pip compile --python-platform
# x86_64-apple-darwin --extra all` failed outright, so "install the lot" was the one
# install instruction the docs give that no Intel Mac could follow.
#
# `all` therefore carries a platform marker that `gaze` and `diarization-pyannote` do
# not. That divergence is deliberate and directional: **`yazses[all]` means "everything
# that can work on this machine", while `yazses[gaze]` is an explicit request for one
# feature and must fail loudly rather than install a hollow subset of it.** What must
# never happen is the reverse -- `all` offering a requirement on *more* platforms than
# its owning extra does, which would resolve something the owner already knows is broken.

#: Requirement name -> the reason `all` states a marker its owning extra does not.
NARROWED = {
    "mediapipe": "no macOS x86_64 wheel after 0.10.21; gaze routing is X11-only anyway",
    "pyannote.audio": "pulls in torch, which has no macOS x86_64 wheel after 2.2.2",
}


def _name(req: str) -> str:
    import re
    return re.split(r"[\[<>=!~;\s]", req, maxsplit=1)[0].strip()


def test_all_may_narrow_a_requirement_to_fewer_platforms():
    """Every marker divergence must be listed in NARROWED with its reason."""
    union = _union()
    by_req = {_split(r)[0]: _split(r)[1] for r in union}
    undocumented = []
    for req in _extras()["all"]:
        base, marker = _split(req)
        owner_marker = by_req.get(base)
        if owner_marker is not None and marker != owner_marker and _name(req) not in NARROWED:
            undocumented.append(req)
    assert not undocumented, (
        f"{undocumented} carries a marker in `all` that its owning extra does not, and "
        "no reason is recorded in NARROWED. A divergence nobody wrote down is drift."
    )


def test_all_never_widens_a_requirement_to_more_platforms():
    """The dangerous direction, and the one no reason could justify.

    An unmarked requirement in `all` where the owning extra states a marker would install,
    on a platform the owner has already ruled out, precisely the thing that does not work
    there. Checked structurally: an empty marker in `all` against a non-empty one in the
    owning extra.
    """
    by_req = {_split(r)[0]: _split(r)[1] for r in _union()}
    widened = []
    for req in _extras()["all"]:
        base, marker = _split(req)
        owner = by_req.get(base)
        if owner and not marker:
            widened.append(f"{req} (owner states `{owner}`)")
    assert not widened, f"`all` offers on more platforms than its owner allows: {widened}"


def test_every_narrowed_requirement_is_actually_narrowed():
    """A stale exemption is a hole. If a marker is dropped from `all`, the entry here
    stops describing anything and must go rather than sit ready to excuse the next one."""
    markers = {_name(r): _split(r)[1] for r in _extras()["all"]}
    stale = sorted(n for n in NARROWED if not markers.get(n))
    assert not stale, (
        f"{stale} is listed in NARROWED but states no marker in `all` any more — "
        "delete the entry, or restore the marker it was written for"
    )


def test_the_narrowing_marker_actually_excludes_intel_macos():
    """The reason is platform-specific, so assert the marker *is* the platform.

    A marker that had drifted to, say, `python_version` would still count as a
    divergence and still be exempted by NARROWED, while silently no longer keeping the
    unresolvable wheel off the platform that cannot take it.
    """
    from packaging.markers import Marker

    intel_mac = {"sys_platform": "darwin", "platform_machine": "x86_64",
                 "os_name": "posix", "platform_system": "Darwin"}
    apple_silicon = dict(intel_mac, platform_machine="arm64")
    linux = {"sys_platform": "linux", "platform_machine": "x86_64",
             "os_name": "posix", "platform_system": "Linux"}
    for req in _extras()["all"]:
        if _name(req) not in NARROWED:
            continue
        marker = Marker(_split(req)[1])
        assert not marker.evaluate(intel_mac), f"{req} still resolves on Intel macOS"
        assert marker.evaluate(apple_silicon), f"{req} no longer resolves on Apple silicon"
        assert marker.evaluate(linux), f"{req} no longer resolves on Linux"
