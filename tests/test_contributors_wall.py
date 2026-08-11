"""The contributors wall must agree with itself.

Credit is spread across three hand-maintained surfaces — `.all-contributorsrc` (the
source of truth), the generated wall + badge in `README.md`, and the prose in
`CONTRIBUTORS.md`. Nothing kept them in step, and all three had drifted: the rc badge
template said 8, the README badge said 9, and there were 10 people. @YossiMH was
credited in CONTRIBUTORS.md for the design review that produced `contract/semantic/`
and was missing from the wall entirely — the surface people actually look at.

Being forgotten is the one failure mode a contributor never reports. These checks are
offline and deterministic; "is someone with merged work missing from all three?" needs
to know who actually has merged work, so it lives in `scripts/check_contributor_wall.py`
(GitHub API, with a git-history fallback) rather than here. Run that after a merge wave —
these tests pass happily while all three surfaces agree and omit the same person.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RC = ROOT / ".all-contributorsrc"
README = ROOT / "README.md"
CONTRIBUTORS = ROOT / "CONTRIBUTORS.md"


def _rc_logins() -> list[str]:
    return [c["login"] for c in json.loads(RC.read_text(encoding="utf-8"))["contributors"]]


def _rc_profiles() -> dict[str, str]:
    """login -> the profile URL the wall is supposed to render for them."""
    return {
        c["login"]: c["profile"]
        for c in json.loads(RC.read_text(encoding="utf-8"))["contributors"]
    }


def _contributors_md_logins() -> set[str]:
    """Every `[@login](...)` mentioned in CONTRIBUTORS.md, any section."""
    return set(re.findall(r"\[@([A-Za-z0-9-]+)\]", CONTRIBUTORS.read_text(encoding="utf-8")))


def test_everyone_on_the_wall_is_named_in_contributors_md():
    missing = sorted(set(_rc_logins()) - _contributors_md_logins())
    assert not missing, (
        f"on the README wall but absent from CONTRIBUTORS.md: {missing} — "
        "add them, or remove them from .all-contributorsrc"
    )


def test_everyone_named_in_contributors_md_is_on_the_wall():
    """The direction that actually broke: credited in prose, invisible on the wall."""
    missing = sorted(_contributors_md_logins() - set(_rc_logins()))
    assert not missing, (
        f"credited in CONTRIBUTORS.md but missing from the README wall: {missing} — "
        "run `npx all-contributors-cli add <login> <types>`. A contribution with no "
        "commit behind it (ideas, bug, research) is exactly the kind that gets dropped."
    )


def test_the_badge_counts_the_people_actually_on_the_wall():
    badge = re.search(r"all_contributors-(\d+)-", README.read_text(encoding="utf-8"))
    assert badge, "the all-contributors badge is gone from README.md"
    assert int(badge.group(1)) == len(_rc_logins()), (
        f"badge says {badge.group(1)}, .all-contributorsrc has {len(_rc_logins())} "
        "contributors. The generator does not own this line — update it by hand."
    )


def test_the_wall_renders_every_contributor():
    wall = README.read_text(encoding="utf-8")
    start, end = wall.find("ALL-CONTRIBUTORS-LIST:START"), wall.find("ALL-CONTRIBUTORS-LIST:END")
    assert start != -1 and end != -1, "the ALL-CONTRIBUTORS-LIST markers are gone from README.md"
    section = wall[start:end]
    # Check each entry's *declared* profile URL, not a hardcoded github.com/<login> shape.
    # The wall is generated from .all-contributorsrc, so the rc is the invariant; assuming
    # the URL shape instead made the two disagree the moment a link legitimately differed —
    # which happened when a contributor deleted their account and their profile link had to
    # be repointed at their commits so the README stopped serving a 404.
    profiles = _rc_profiles()
    missing = [login for login, url in profiles.items() if f'href="{url}"' not in section]
    assert not missing, (
        f"in .all-contributorsrc but not rendered in the README wall with its declared "
        f"profile URL: {missing} — run `npx all-contributors-cli generate`"
    )


def test_no_duplicate_entries():
    logins = _rc_logins()
    dupes = sorted({x for x in logins if logins.count(x) > 1})
    assert not dupes, f"listed twice in .all-contributorsrc: {dupes}"


def test_ci_output_masks_contributor_email_addresses():
    """`.github/workflows/attribution.yml` runs the wall check on every merge to main.

    Workflow logs on a public repository are public, and the script prints the address of
    any author it could not map to a login. Unmasked, automating the check would publish
    contributors' email addresses — turning a helpful check into a privacy leak, and
    contradicting the rule the campaign scripts already follow.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_wall", ROOT / "scripts" / "check_contributor_wall.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    masked = mod.redact_email("Ada Lovelace <ada.lovelace@example.com>")
    assert "ada.lovelace@" not in masked, "the local part leaked"
    assert "example.com" in masked, "the domain is what makes the person recognisable"
    assert "Ada Lovelace" in masked, "the name must survive or nobody can act on it"

    workflow = (ROOT / ".github" / "workflows" / "attribution.yml").read_text(encoding="utf-8")
    assert "--redact-emails" in workflow, (
        "the attribution workflow must pass --redact-emails; without it every unmapped "
        "contributor's address is printed into a public workflow log"
    )


def _wall_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_wall", ROOT / "scripts" / "check_contributor_wall.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_api_call_uses_a_token_when_one_is_available(monkeypatch):
    """`attribution.yml` set GITHUB_TOKEN from day one and the script never read it.

    Unauthenticated GitHub allows 60 requests/hour per IP and Actions runners share address
    space, so the call was rate-limited every run and fell back to git history — which
    recovers only logins with a noreply address (5 here, against 9 from the API). The
    workflow therefore ran in its weakest mode permanently, and said "✓ every contributor
    is credited" while doing so. The env var was provided; the wiring was missing.
    """
    mod = _wall_script()

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert "Authorization" not in mod.api_headers(), "must not invent an Authorization header"

    monkeypatch.setenv("GITHUB_TOKEN", "ghs_exampletoken")
    assert mod.api_headers()["Authorization"] == "Bearer ghs_exampletoken"

    workflow = (ROOT / ".github" / "workflows" / "attribution.yml").read_text(encoding="utf-8")
    assert "GITHUB_TOKEN" in workflow, (
        "the attribution workflow must pass GITHUB_TOKEN, or the API call is rate-limited "
        "and the check silently degrades to the weaker git-history mode"
    )


def test_a_deleted_account_on_the_wall_is_reported():
    """The wall check ran one direction only, and was blind to the opposite failure.

    On 2026-08-11 the largest external contributor deleted their GitHub account. GitHub
    then stopped listing them in `/contributors`, so the "everyone with commits is on the
    wall" count simply dropped from 10 to 9 and the run still exited 0 — the guard got
    weaker at the exact moment the problem appeared, and the README was left linking to a
    404. Nothing detected it; it was found by hand while verifying @-mentions.
    """
    mod = _wall_script()
    dead = mod.dead_wall_profiles({"alive", "gone"}, probe=lambda login: 404 if login == "gone" else 200)
    assert dead == {"gone"}


def test_the_warning_clears_once_the_link_is_repointed():
    """What needs fixing is the dead link, not the departure.

    The account stays gone forever, so a warning keyed on the account alone would never go
    away — and a warning that survives its own fix is one people learn to scroll past. Once
    the entry points at something that resolves (their commits URL), there is nothing left
    to act on and the check goes quiet.
    """
    mod = _wall_script()
    gone = {"gone"}
    probe = lambda _login: 404  # noqa: E731 - the account is deleted either way

    still_dead = mod.dead_wall_profiles(gone, probe=probe, profiles={"gone": "https://github.com/gone"})
    assert still_dead == {"gone"}, "a bare profile link to a deleted account must be reported"

    repointed = mod.dead_wall_profiles(
        gone, probe=probe, profiles={"gone": "https://github.com/MSKazemi/yazses/commits?author=gone"}
    )
    assert repointed == set(), "once repointed at a URL that resolves, stop nagging"


def test_the_real_wall_has_no_dead_profile_links():
    """No entry on the wall may point at `github.com/<login>` for an account that has gone.

    Offline and network-free: it compares the rc against a known-departed login rather than
    hitting the API, so it cannot flake in CI. The live account check lives in the script.
    """
    departed = {"waterlemonnn"}  # deleted 2026-08-11; the work stays credited
    bad = [
        login
        for login, url in _rc_profiles().items()
        if login in departed and url.rstrip("/") == f"https://github.com/{login}"
    ]
    assert not bad, (
        f"the wall links to a deleted account and will serve a 404: {bad} — repoint the "
        "profile at their commits URL. Do NOT remove them; the work is in every release."
    )


def test_a_rate_limit_is_never_reported_as_a_deleted_account():
    """Unauthenticated GitHub allows 60 requests/hour, so 403 is an ordinary outcome here.

    Accusing a real contributor of not existing is far worse than saying nothing, so any
    status that is not a definite 404 abandons the whole sub-check rather than guessing.
    """
    mod = _wall_script()
    assert mod.dead_wall_profiles({"a", "b"}, probe=lambda _login: 403) == set()
    assert mod.dead_wall_profiles({"a", "b"}, probe=lambda _login: None) == set()


def test_a_departed_contributor_is_not_reported_as_missing_from_the_wall():
    """The two checks must not fight each other.

    A deleted account disappears from the API, so it can never show up in `missing` — but
    if it ever did, the advice printed ("add them to the wall") would contradict the advice
    the reverse check prints ("do not remove them"). Pin the intent: the script must tell
    the reader to keep the credit and repair the link, never to delete the person.
    """
    source = (ROOT / "scripts" / "check_contributor_wall.py").read_text(encoding="utf-8")
    assert "Do NOT remove them" in source, (
        "the reverse check must say explicitly that a departed contributor stays on the "
        "wall — otherwise the obvious way to make the warning go away is to delete them"
    )


def _translated_readmes() -> list[Path]:
    """`README.<code>.md` — the translations, which carry their own copy of the wall."""
    return sorted(p for p in ROOT.glob("README.*.md") if p.name != "README.md")


def test_translations_carry_the_same_wall():
    """A translated README copies the wall verbatim, and copies go stale silently.

    Prose in a translation is allowed to lag the English (issue #18 says so
    explicitly, and nobody is signing up to maintain it forever). The wall is not
    prose: it is generated markup, identical in every language, and letting it
    drift drops a real person from the surface people actually look at — in the
    one file where the omission is hardest to notice. The generator only knows
    about `.all-contributorsrc`'s `files` list, so this is the check that fails
    when someone is added and a translation is left behind.
    """
    start, end = "<!-- ALL-CONTRIBUTORS-LIST:START", "<!-- ALL-CONTRIBUTORS-LIST:END"
    english = README.read_text(encoding="utf-8")
    canonical = english[english.find(start) : english.find(end)]

    for path in _translated_readmes():
        text = path.read_text(encoding="utf-8")
        s, e = text.find(start), text.find(end)
        assert s != -1 and e != -1, f"{path.name} has no ALL-CONTRIBUTORS-LIST markers"
        assert text[s:e] == canonical, (
            f"{path.name}'s contributor wall differs from README.md — copy the block "
            "between the ALL-CONTRIBUTORS-LIST markers across after regenerating. "
            "The wall is generated markup, not prose: it does not get to go stale."
        )


def test_translations_show_the_same_badge_count():
    expected = len(_rc_logins())
    for path in _translated_readmes():
        badge = re.search(r"all_contributors-(\d+)-", path.read_text(encoding="utf-8"))
        assert badge, f"the all-contributors badge is gone from {path.name}"
        assert int(badge.group(1)) == expected, (
            f"{path.name} badge says {badge.group(1)}, .all-contributorsrc has {expected}"
        )


def test_every_translation_is_reachable_from_the_english_readme():
    """A translation nobody can find delivers nothing.

    `README.hi.md` shipped before README.md had a switcher line at all, so the
    file existed and no reader could reach it. Every translation must be linked
    from the front door.
    """
    english = README.read_text(encoding="utf-8")
    unlinked = [p.name for p in _translated_readmes() if f"({p.name})" not in english]
    assert not unlinked, (
        f"translated READMEs not linked from README.md: {unlinked} — add them to the "
        '"Read this in other languages" line at the top, alphabetically by code'
    )
