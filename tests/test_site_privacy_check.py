"""The published-artifact privacy check (`scripts/check-site-privacy.py`).

`test_private_tiers_stay_private.py` and `test_design_tier_hook.py` prove the
exclusion *rule* is right and reads its list from one source. Neither looks at
what was actually built, and those are different claims: a correct rule that does
not run publishes everything, and a file can reach the site by a route the hook
never sees — a hand-added nav entry, a copied asset, an include.

The script runs in CI against `site/` after the build. Its logic is tested here,
because the interesting parts are decisions rather than I/O: what counts as
"inside a private tree", and refusing to call an empty site clean.

**The trees below are invented.** Naming the real ones in a public test file would
trip the pre-commit hook that guards them — which it did, on the first draft of
this file. That is the right outcome twice over: the hook works, and the logic
under test does not care what the trees are called. The real names arrive at
runtime from the hook itself.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Stand-ins with the same shapes as the real set: one flat, one nested, one
#: dotted.
FAKE = ["secrets", "internal/plans", ".notes"]


def _script():
    spec = importlib.util.spec_from_file_location(
        "check_site_privacy", ROOT / "scripts" / "check-site-privacy.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_a_page_inside_a_private_tree_is_caught() -> None:
    mod = _script()
    assert mod.offending_paths(["secrets/bet.html", "index.html"], FAKE) == ["secrets/bet.html"]


def test_a_nested_private_path_is_caught_wherever_it_sits() -> None:
    """A tier grafted under a prefix puts the private segment mid-path, not at the
    root of the published URL."""
    mod = _script()
    assert mod.offending_paths(["docs/internal/plans/x.html"], FAKE)


def test_a_similarly_named_public_page_is_not_flagged() -> None:
    """`secrets-and-scope.html` is not inside `secrets/`. A check that cries wolf
    here teaches people to ignore it, which is worse than not having it."""
    mod = _script()
    assert mod.offending_paths(["secrets-and-scope.html", "resecrets/x.html"], FAKE) == []


def test_every_private_tree_is_checked_not_just_the_first() -> None:
    mod = _script()
    paths = ["secrets/a.html", "internal/plans/b.html", ".notes/c.html", "ok.html"]
    assert len(mod.offending_paths(paths, FAKE)) == 3


def test_the_prefix_list_comes_from_the_hook() -> None:
    """Restating the trees would recreate the drift the hook exists to prevent."""
    mod = _script()
    hook = 'grep -E "(^|[^a-zA-Z0-9_/-])(secrets|internal/plans)/"'
    assert mod.private_prefixes(hook) == ["secrets", "internal/plans"]


def test_an_unreadable_hook_falls_back_to_a_populated_set() -> None:
    """A fresh clone has no hooks installed. Falling back to an empty list would
    make this check pass by examining no rules at all."""
    mod = _script()
    assert mod.private_prefixes(None) == mod.DOCUMENTED
    assert mod.private_prefixes("a hook with no such regex") == mod.DOCUMENTED
    assert len(mod.DOCUMENTED) >= 3, "the fallback must not quietly empty out"


def test_an_empty_site_is_refused_rather_than_called_clean(tmp_path) -> None:
    """The exact shape this repo has been bitten by: iterate an empty collection,
    report success. An empty site/ means the build failed, which is not a privacy
    result."""
    empty = tmp_path / "site"
    empty.mkdir()
    assert _script().main(["prog", str(empty)]) == 2


def test_a_missing_site_is_an_error_not_a_pass(tmp_path) -> None:
    assert _script().main(["prog", str(tmp_path / "nope")]) == 2


def test_a_clean_site_passes(tmp_path) -> None:
    site = tmp_path / "site"
    (site / "guides").mkdir(parents=True)
    (site / "index.html").write_text("hi")
    (site / "guides" / "a.html").write_text("hi")
    assert _script().main(["prog", str(site)]) == 0


def test_a_dirty_site_fails(tmp_path, monkeypatch) -> None:
    """End to end through main(), with the tree list forced to the stand-ins."""
    mod = _script()
    monkeypatch.setattr(mod, "_hook_text", lambda: 'x"(^|[^a-zA-Z0-9_/-])(secrets)/"')
    site = tmp_path / "site"
    (site / "secrets").mkdir(parents=True)
    (site / "index.html").write_text("hi")
    (site / "secrets" / "plan.html").write_text("confidential")
    assert mod.main(["prog", str(site)]) == 1
