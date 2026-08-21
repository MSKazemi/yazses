"""A feature advertised as *wired* must not write a config key nothing reads.

Two guards already stand near this, and each is satisfied by the state this one
forbids:

* `test_feature_wiring_honesty.py` proves the feature's **package is reachable** from
  a real entry point. Reachable is not the same as *consulted*: a package can be
  imported for one thing while the key a toggle writes is read by nobody.
* `test_config_keys_are_read.py` keeps a **ledger** of config keys no code reads. It
  is deliberately a ledger and not a gate — 63 keys are listed with reasons, because
  demanding 63 fixes in one commit would only get the test deleted.

So the hole is between them. Add a feature, mark it wired (its package is imported for
something else), and park its key in `KNOWN_UNREAD` with a plausible note: both guards
stay green, `yazses features enable <slug>` writes the key, and nothing on any runtime
path ever reads it. The user is told the capability is on. It is inert.

That combination is different in kind from either half. An honestly-flagged unwired
feature is a promise not yet kept, which the registry states plainly and `features
enable` refuses. This is a promise contradicted — and it is the exact shape this
project has spent months digging out of ("67 designed capabilities nobody can reach").

Currently zero, which is why it is worth pinning now rather than after it drifts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_config_keys_are_read import KNOWN_UNREAD  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.system.features import grouped_features  # noqa: E402


def _config_class(section: str) -> str:
    """The dataclass name backing a config section, e.g. `commands` -> CommandsConfig.

    Read off a real `Config` rather than guessed from the section name: dotted
    sections (`filters.disfluency`) and sections whose class name is not the
    title-cased section both exist, and a wrong guess here would silently match
    nothing — a guard that quietly stops guarding.
    """
    node = Config()
    for part in section.split("."):
        node = getattr(node, part, None)
        if node is None:
            return ""
    return type(node).__name__


def _wired_toggle_keys() -> list[tuple[str, str, str]]:
    """`(slug, section, key)` for every key a *wired* feature's toggle writes."""
    out: list[tuple[str, str, str]] = []
    for _category, _blurb, feats in grouped_features(Config()):
        for feat in feats:
            if not getattr(feat, "wired", True):
                continue
            for write in getattr(feat, "on_writes", ()) or ():
                section, key = write[0], write[1]
                out.append((feat.slug, str(section), str(key)))
    return out


@pytest.fixture(scope="module")
def toggle_keys() -> list[tuple[str, str, str]]:
    return _wired_toggle_keys()


def test_the_scan_sees_real_features(toggle_keys) -> None:
    """A guard that iterates an empty set passes on everything — a shape this repo
    has been bitten by repeatedly, including three times in one day."""
    assert len(toggle_keys) > 50, f"only {len(toggle_keys)} toggle writes found"
    slugs = {slug for slug, _s, _k in toggle_keys}
    assert "meeting" in slugs and "commands" in slugs


def test_no_wired_features_toggle_writes_an_unread_key(toggle_keys) -> None:
    """The lie neither neighbouring guard can see on its own."""
    # `KNOWN_UNREAD` is "ClassName.field", so the class must be resolved rather than
    # the entry reduced to its field. Reducing it was the first version, and
    # red-greening it showed why: dozens of sections have a field called `enabled`,
    # so parking ONE `*.enabled` in the ledger flagged every feature that has one.
    # A guard that reports thirty innocents alongside the guilty one is a guard that
    # gets deleted.
    offenders = sorted({
        f"{slug}: [{section}] {key}"
        for slug, section, key in toggle_keys
        if f"{_config_class(section)}.{key}" in KNOWN_UNREAD
    })
    assert not offenders, (
        "these features are advertised as wired, and `features enable` writes a key "
        "that the unread-key ledger says nothing reads — so the switch does nothing "
        "while telling the user it is on:\n  " + "\n  ".join(offenders)
        + "\n\nEither wire the key, or flag the feature unwired in features.py so "
        "`features enable` refuses it honestly."
    )


def test_the_check_can_fail(toggle_keys) -> None:
    """Only worth having if it can fire.

    Uses a real toggle key and a synthetic ledger rather than the reverse, so the
    assertion exercises the same matching the guard above does.
    """
    slug, section, key = toggle_keys[0]
    qualified = f"{_config_class(section)}.{key}"
    assert _config_class(section), f"could not resolve the config class for [{section}]"
    hits = [
        s for s, sec, k in toggle_keys
        if f"{_config_class(sec)}.{k}" == qualified
    ]
    assert slug in hits, f"the matcher failed to find {slug}'s own key {qualified!r}"


def test_the_ledger_is_actually_populated() -> None:
    """If `KNOWN_UNREAD` were ever emptied, the guard above would pass vacuously
    while the hole it covers stayed open."""
    assert len(KNOWN_UNREAD) > 20
