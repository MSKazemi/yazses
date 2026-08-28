"""`scripts/check-release-channels.py` must answer honestly about every channel.

The script is the thing that decides whether a release shipped everywhere, so a
bug in it is worse than no check at all: it would report a complete release while
one platform was missing, which is exactly the failure it exists to catch.

These tests are **fully offline**, like the rest of the suite. Every HTTP call goes
through one `_get` seam, so stubbing that is enough to drive each channel through
its success and failure paths without touching the network.

Two traps get their own tests because both have already been made for real:

- **Flathub and search.nixos.org return HTTP 200 for pages that do not exist**, so a
  naive check reports them published forever. The checks must query an API, and
  `test_flathub_uses_the_api_not_the_website` asserts the URL, not just the verdict.
- **GHCR rejects unauthenticated reads whether or not the image exists.** A bare
  request returns 401/404 for a published image, which is how `packaging/README.md`
  came to record Docker as unpublished while it was live.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-release-channels.py"


def _load():
    """Import the script by path -- its filename is not a valid module name."""
    spec = importlib.util.spec_from_file_location("check_release_channels", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Must be registered before exec: @dataclass resolves annotations via
    # sys.modules[cls.__module__] and raises AttributeError on a module that is
    # not there yet.
    sys.modules["check_release_channels"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def crc():
    return _load()


@pytest.fixture
def responses(crc, monkeypatch):
    """Stub the single network seam. Returns the recorded list of requested URLs."""
    requested: list[str] = []

    def make(mapping: dict[str, tuple[int, bytes]], default=(404, b"")):
        def fake_get(url: str, headers=None):
            requested.append(url)
            for fragment, response in mapping.items():
                if fragment in url:
                    return response
            return default

        monkeypatch.setattr(crc, "_get", fake_get)
        return requested

    return make


def _body(obj) -> bytes:
    return json.dumps(obj).encode()


# --------------------------------------------------------------------------
# Release assets
# --------------------------------------------------------------------------


def test_all_three_assets_present(crc, responses):
    responses(
        {
            "api.github.com": (
                200,
                _body(
                    {
                        "assets": [
                            {"name": "yazses_2.18.2_amd64.deb"},
                            {"name": "yazses_2.18.2_arm64.deb"},
                            {"name": "YazSes-2.18.2-macos-arm64.dmg"},
                            {"name": "YazSes-2.18.2-macos-x86_64.dmg"},
                            {"name": "YazSes-2.18.2-windows-arm64.exe"},
                            {"name": "YazSes-2.18.2-windows-x64.exe"},
                        ]
                    }
                ),
            )
        }
    )
    got = crc.check_release_assets("2.18.2")
    assert all(ok for ok, _ in got.values())


def test_missing_deb_is_reported_alone(crc, responses):
    """The real v2.18.1: macOS and Windows shipped, Linux did not."""
    responses(
        {
            "api.github.com": (
                200,
                _body(
                    {
                        "assets": [
                            {"name": "YazSes-2.18.1-macos-arm64.dmg"},
                            {"name": "YazSes-2.18.1-macos-x86_64.dmg"},
                            {"name": "YazSes-2.18.1-windows-arm64.exe"},
                            {"name": "YazSes-2.18.1-windows-x64.exe"},
                        ]
                    }
                ),
            )
        }
    )
    got = crc.check_release_assets("2.18.1")
    assert got["deb"][0] is False
    assert got["dmg"][0] is True
    assert got["exe"][0] is True


def test_absent_release_fails_every_asset(crc, responses):
    responses({})  # everything 404s
    got = crc.check_release_assets("9.9.9")
    assert not any(ok for ok, _ in got.values())


# --------------------------------------------------------------------------
# Channels whose answer is a version, not merely presence
# --------------------------------------------------------------------------


def test_snap_stale_version_is_not_published(crc, responses):
    """A channel serving an older build must not count as carrying this release."""
    payload = {"channel-map": [{"channel": {"name": "stable"}, "version": "2.17.0"}]}
    responses({"api.snapcraft.io": (200, _body(payload))})
    ok, detail = crc.check_snap("2.18.2")
    assert ok is False
    assert "2.17.0" in detail


def test_snap_matching_version_passes(crc, responses):
    payload = {"channel-map": [{"channel": {"name": "stable"}, "version": "2.18.2"}]}
    responses({"api.snapcraft.io": (200, _body(payload))})
    assert crc.check_snap("2.18.2")[0] is True


def test_apt_reads_the_packages_index(crc, responses):
    responses({"gh-pages/apt/Packages": (200, b"Package: yazses\nVersion: 2.18.2\n")})
    assert crc.check_apt("2.18.2")[0] is True
    assert crc.check_apt("2.18.3")[0] is False


def test_homebrew_cask_version(crc, responses):
    responses({"homebrew-yazses": (200, b'cask "yazses" do\n  version "2.18.2"\nend\n')})
    assert crc.check_homebrew("2.18.2")[0] is True
    assert crc.check_homebrew("2.17.0")[0] is False


def test_scoop_bucket_version(crc, responses):
    responses({"bucket/yazses.json": (200, _body({"version": "2.18.2"}))})
    assert crc.check_scoop("2.18.2")[0] is True
    assert crc.check_scoop("2.18.1")[0] is False


def test_aur_strips_the_pkgrel(crc, responses):
    """AUR reports `2.18.2-1`; the trailing pkgrel is not part of our version."""
    responses({"aur.archlinux.org": (200, _body({"results": [{"Version": "2.18.2-1"}]}))})
    assert crc.check_aur("2.18.2")[0] is True


def test_aur_absent(crc, responses):
    responses({"aur.archlinux.org": (200, _body({"resultcount": 0, "results": []}))})
    ok, detail = crc.check_aur("2.18.2")
    assert ok is False and "not in AUR" in detail


def test_chocolatey_needs_this_exact_version(crc, responses):
    feed = b"<feed><entry><d:Version>2.17.0</d:Version></entry></feed>"
    responses({"chocolatey.org": (200, feed)})
    assert crc.check_chocolatey("2.18.2")[0] is False
    assert crc.check_chocolatey("2.17.0")[0] is True


def test_winget_checks_upstream_not_our_own_copy(crc, responses):
    """Manifests sitting in packaging/ install nobody -- only winget-pkgs counts."""
    requested = responses({"microsoft/winget-pkgs": (200, b"[]")})
    assert crc.check_winget("2.18.2")[0] is True
    assert any("microsoft/winget-pkgs" in u for u in requested)


# --------------------------------------------------------------------------
# The two verification traps
# --------------------------------------------------------------------------


def test_flathub_uses_the_api_not_the_website(crc, responses):
    """flathub.org is a SPA that answers 200 for apps that do not exist."""
    requested = responses({"flathub.org/api/v2/appstream": (200, b"{}")})
    assert crc.check_flathub("2.18.2")[0] is True
    assert requested, "no request was made"
    assert all("/api/v2/appstream/" in u for u in requested), requested


def test_flathub_absent_is_a_real_404(crc, responses):
    responses({})
    assert crc.check_flathub("2.18.2")[0] is False


def test_nix_uses_a_raw_nixpkgs_path_not_the_search_site(crc, responses):
    """search.nixos.org is also a SPA; a raw file path 404s honestly."""
    requested = responses({"raw.githubusercontent.com/NixOS/nixpkgs": (200, b"{}")})
    assert crc.check_nix("2.18.2")[0] is True
    assert all("search.nixos.org" not in u for u in requested), requested


def test_ghcr_gets_a_pull_token_before_listing_tags(crc, responses):
    """An unauthenticated GHCR read 401s even for a published public image."""
    requested = responses(
        {
            "ghcr.io/token": (200, _body({"token": "abc"})),
            "ghcr.io/v2/": (200, _body({"tags": ["2.18.2"]})),
        }
    )
    assert crc.check_docker("2.18.2")[0] is True
    assert any("ghcr.io/token" in u for u in requested), "no token was requested"


def test_ghcr_without_a_token_is_not_read_as_absent(crc, responses):
    """If the token call fails we must say so, not silently report 'not published'."""
    responses({})
    ok, detail = crc.check_docker("2.18.2")
    assert ok is False
    assert "token" in detail


def test_ghcr_tag_missing(crc, responses):
    responses(
        {
            "ghcr.io/token": (200, _body({"token": "abc"})),
            "ghcr.io/v2/": (200, _body({"tags": ["2.17.0"]})),
        }
    )
    assert crc.check_docker("2.18.2")[0] is False


# --------------------------------------------------------------------------
# Aggregation and the core/full distinction
# --------------------------------------------------------------------------


def test_core_only_returns_exactly_the_channels_ci_builds(crc, responses):
    responses(
        {
            "api.github.com": (
                200,
                _body(
                    {
                        "assets": [
                            {"name": "a1.deb"},
                            {"name": "a2.deb"},
                            {"name": "b1.dmg"},
                            {"name": "b2.dmg"},
                            {"name": "c1.exe"},
                            {"name": "c2.exe"},
                        ]
                    }
                ),
            ),
            "pypi.org": (200, b"{}"),
        }
    )
    results = crc.run("2.18.2", core_only=True)
    assert {r.key for r in results} == crc.CORE
    assert all(r.ok for r in results)


def test_core_only_does_not_touch_the_other_channels(crc, responses):
    requested = responses({"api.github.com": (200, _body({"assets": []})), "pypi.org": (200, b"{}")})
    crc.run("2.18.2", core_only=True)
    for host in ("snapcraft", "flathub", "ghcr.io", "aur.archlinux"):
        assert not any(host in u for u in requested), f"core-only queried {host}"


def test_full_run_covers_every_declared_channel(crc, responses):
    responses({}, default=(404, b""))  # everything genuinely absent
    results = crc.run("9.9.9", core_only=False)
    keys = {r.key for r in results}
    assert keys == {"deb", "dmg", "exe"} | {k for k, _, _ in crc.CHECKS}
    assert not any(r.ok for r in results)


# --------------------------------------------------------------------------
# Unreachable is not the same as absent
# --------------------------------------------------------------------------


def test_unreachable_host_is_unknown_not_absent(crc, responses):
    """Status 0 means the request never completed.

    Observed for real on 2026-08-13: one dropped connection to aur.archlinux.org
    made the report say the AUR did not have the release, and three retries a
    moment later all returned 200. Reporting that as absent invites the wrong
    repair -- publishing a package that is already there.
    """
    responses({}, default=(0, b"Connection reset"))
    for fn in (crc.check_aur, crc.check_pypi, crc.check_flathub, crc.check_snap):
        ok, _ = fn("2.18.2")
        assert ok is crc.UNKNOWN, f"{fn.__name__} reported {ok!r} for an unreachable host"


def test_a_real_404_is_still_absent(crc, responses):
    """The tri-state must not turn genuine absence into 'cannot tell'."""
    responses({}, default=(404, b""))
    assert crc.check_flathub("2.18.2")[0] is False
    assert crc.check_pypi("2.18.2")[0] is False


def test_release_assets_unreachable_is_unknown(crc, responses):
    responses({}, default=(0, b"timeout"))
    got = crc.check_release_assets("2.18.2")
    assert all(ok is crc.UNKNOWN for ok, _ in got.values())
    assert all("unreachable" in detail for _, detail in got.values())


def test_transient_failure_is_retried_then_succeeds(crc, monkeypatch):
    """Most status-0 failures are transient, so one blip must not decide the answer."""
    calls = {"n": 0}

    class Boom(Exception):
        pass

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise Boom("reset")

        class R:
            status = 200

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R()

    monkeypatch.setattr(crc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(crc.urllib.request, "urlopen", flaky)
    status, _ = crc._get("https://example.invalid/x")
    assert status == 200
    assert calls["n"] == 2, "the first failure was not retried"


def test_retries_give_up_and_report_zero(crc, monkeypatch):
    def always_fail(req, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr(crc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(crc.urllib.request, "urlopen", always_fail)
    status, body = crc._get("https://example.invalid/x")
    assert status == 0
    assert b"no route" in body


def test_unknown_is_reported_separately_from_missing(crc, responses, capsys, monkeypatch):
    """The summary must not lump 'unreachable' in with 'not published'."""
    responses(
        {
            "api.github.com": (
                200,
                _body({"assets": [{"name": "a1.deb"}, {"name": "a2.deb"}, {"name": "b1.dmg"},
                                  {"name": "b2.dmg"}, {"name": "c1.exe"}, {"name": "c2.exe"}]}),
            )
        },
        default=(0, b"unreachable"),
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--version", "2.18.2"])
    code = crc.main()
    out = capsys.readouterr().out
    assert code == 1, "an unverifiable release must not be reported as complete"
    assert "Could not check" in out
    assert "not known to be absent" in out
    assert "⚠️" in out


def test_a_check_that_raises_does_not_hide_the_others(crc, responses, monkeypatch):
    """One broken channel must not take the whole report down with it."""
    responses(
        {"api.github.com": (200, _body({"assets": [{"name": "a1.deb"}, {"name": "a2.deb"}]}))}
    )

    def boom(_version):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(crc, "CHECKS", [("pypi", "PyPI", boom)])
    results = crc.run("2.18.2", core_only=False)
    pypi = next(r for r in results if r.key == "pypi")
    # UNKNOWN, not False: a crashed check has told us nothing about the package.
    assert pypi.ok is crc.UNKNOWN
    assert "RuntimeError" in pypi.detail
    # The asset checks still reported.
    assert next(r for r in results if r.key == "deb").ok is True


def test_one_architecture_of_a_pair_is_not_a_published_platform(crc, responses):
    """The exact gap release-complete.yml's wait loop was hardened against.

    That workflow used to count `deb > 1 && dmg > 1 && exe > 1` in bash, with a
    comment explaining why: "at least one .dmg" is what let v2.20.0 and v2.21.0
    print "All platforms published" while the cross-architecture legs failed
    silently. But the wait was only a wait — the *verdict* came from this script,
    which took the first matching asset and called the platform done, so the gate
    waited for a stricter condition than the one it went on to certify. The
    workflow now polls this script instead of counting separately, so there is one
    implementation; this test is what keeps it strict.

    That mattered twice over, because `--core-only` is what decides whether an
    incomplete release keeps the "Latest" label: a release carrying only an arm64
    .dmg passed it, so it was never demoted and Intel users were sent to a
    download that did not exist.
    """
    responses(
        {
            "api.github.com": (
                200,
                _body(
                    {
                        "assets": [
                            {"name": "yazses_2.25.0_amd64.deb"},
                            {"name": "yazses_2.25.0_arm64.deb"},
                            {"name": "YazSes-2.25.0-macos-arm64.dmg"},
                            {"name": "YazSes-2.25.0-windows-arm64.exe"},
                            {"name": "YazSes-2.25.0-windows-x64.exe"},
                        ]
                    }
                ),
            )
        }
    )
    got = crc.check_release_assets("2.25.0")
    assert got["deb"][0] is True, "both .deb architectures are attached"
    assert got["exe"][0] is True, "both .exe architectures are attached"
    assert got["dmg"][0] is False, (
        "only the arm64 .dmg is attached — Intel users have no download, and this "
        f"reported the macOS platform as published: {got['dmg']}"
    )
    assert "arm64" in got["dmg"][1], "the detail must name what was actually found"


def test_ci_only_covers_the_container_image_and_core_only_does_not(crc, responses):
    """The two subsets answer different questions and must not be conflated.

    `--ci-only` answers "has CI finished?", so it includes the container image
    this same tag push publishes — omitting it is how the v2.25.0 report named
    Docker missing while it was still in flight. `--core-only` answers "is the
    release broken for a user on that OS?", which is what may demote a release to
    pre-release, and a missing image is a gap in reach rather than a broken
    download.
    """
    assert "docker" in crc.CI_PUBLISHED
    assert "docker" not in crc.CORE
    assert crc.CORE < crc.CI_PUBLISHED, "ci-only must be a superset of core"

    responses(
        {
            "api.github.com": (
                200,
                _body(
                    {
                        "assets": [
                            {"name": "a1.deb"}, {"name": "a2.deb"},
                            {"name": "b1.dmg"}, {"name": "b2.dmg"},
                            {"name": "c1.exe"}, {"name": "c2.exe"},
                        ]
                    }
                ),
            ),
            "pypi.org": (200, b"{}"),
            "ghcr.io": (200, b'{"tags": ["2.18.2"]}'),
        }
    )
    core_keys = {r.key for r in crc.run("2.18.2", core_only=True)}
    ci_keys = {r.key for r in crc.run("2.18.2", core_only=False, ci_only=True)}
    assert "docker" not in core_keys, f"--core-only must not gate on the image: {core_keys}"
    assert "docker" in ci_keys, f"--ci-only must wait for the image: {ci_keys}"


# --- regression comparison ---------------------------------------------------
#
# The scheduled drift watch (.github/workflows/channel-drift.yml) asks a
# different question from the tag-time completeness gate: not "is every channel
# published?" but "did a channel that used to work stop working?". Six of this
# project's channels have no credential wired up and are absent for every
# version, so a daily report of plain absence is a standing complaint nobody
# reads. `regressions()` is what makes the difference, and it derives the answer
# from the previous release rather than from a hand-written list of channels
# that count -- a list that would be wrong the day a credential is added and
# wrong again the day one lapses, with nothing to say so.


def _r(crc, key, ok):
    return crc.Result(key, key.upper(), ok, "")


def test_a_channel_that_carried_the_previous_release_and_not_this_one_is_a_regression(crc):
    new = [_r(crc, "snap", False), _r(crc, "pypi", True)]
    old = [_r(crc, "snap", True), _r(crc, "pypi", True)]
    assert [r.key for r in crc.regressions(new, old)] == ["snap"]


def test_a_channel_that_never_carried_anything_is_not_reported(crc):
    """Flathub, nixpkgs and the AUR are absent for every version by design."""
    new = [_r(crc, "flathub", False), _r(crc, "nix", False)]
    old = [_r(crc, "flathub", False), _r(crc, "nix", False)]
    assert crc.regressions(new, old) == []


def test_an_unreachable_channel_is_never_called_a_regression(crc):
    """Not being able to ask is not an answer -- the `_get` lesson, again.

    A dropped connection to the AUR once made this script report an unpublished
    package; the repair for that is not "publish it again".
    """
    new = [_r(crc, "aur", crc.UNKNOWN)]
    old = [_r(crc, "aur", True)]
    assert crc.regressions(new, old) == []


def test_a_channel_that_only_appeared_in_the_new_release_is_not_a_regression(crc):
    """A newly wired-up credential must not read as a fault the day before."""
    new = [_r(crc, "choco", True)]
    old = [_r(crc, "choco", False)]
    assert crc.regressions(new, old) == []


def test_an_empty_previous_release_reports_nothing_rather_than_everything(crc):
    """The empty-collection trap: a comparison with nothing must not be a pass.

    It reports no regressions, which is correct -- but the *workflow* must then
    fall back to the plain completeness report rather than treating "no previous
    release" as "all clear". That fallback is asserted in
    tests/test_channel_drift_watch.py; this records the half that lives here.
    """
    new = [_r(crc, "snap", False), _r(crc, "pypi", False)]
    assert crc.regressions(new, []) == []


# ---------------------------------------------------------------------------
# The blind spot in "report regressions, not absences".
#
# Comparing against the PREVIOUS release catches a channel the moment it breaks
# and never again: once it has missed two releases in a row it did not carry the
# previous one either, so it becomes its own baseline and drops out of the
# comparison for good. That is not a hypothetical -- it hid a frozen Homebrew
# tap for seventeen releases while the daily watcher reported all clear, and a
# user installed the stale build and reported already-fixed macOS bugs as live.
#
# The second rule closes it by asking the channel what it is serving right now.
# ---------------------------------------------------------------------------


def _rd(crc, key, ok, detail):
    """A Result that carries the evidence string a real check would produce."""
    return crc.Result(key, key.upper(), ok, detail)


def test_a_channel_frozen_since_before_the_comparison_window_is_still_a_regression(crc):
    """The Homebrew case: stale in BOTH releases, so the old rule sees nothing."""
    new = [_rd(crc, "homebrew", False, "cask=2.18.2")]
    old = [_rd(crc, "homebrew", False, "cask=2.18.2")]
    # Rule 1 alone reports nothing here -- the previous release did not reach it.
    assert {r.key for r in old if r.ok is True} == set()
    assert [r.key for r in crc.regressions(new, old)] == ["homebrew"]


def test_a_channel_that_serves_nothing_is_still_not_reported(crc):
    """Absence is not staleness -- the six unwired channels stay suppressed."""
    new = [
        _rd(crc, "flathub", False, "appstream HTTP 404"),
        _rd(crc, "nix", False, "nixpkgs HTTP 404"),
        _rd(crc, "winget", False, "winget-pkgs HTTP 404"),
        _rd(crc, "choco", False, "not listed"),
        _rd(crc, "aur", False, "not in AUR"),
    ]
    assert crc.regressions(new, new) == []


def test_a_channel_that_could_not_be_read_is_not_called_stale(crc):
    """`cask HTTP 404` names a label but is not a version being served."""
    new = [_rd(crc, "homebrew", False, "cask HTTP 404")]
    assert crc.regressions(new, new) == []


def test_sentinel_details_are_not_mistaken_for_a_served_version(crc):
    """`_evidence` prints `<label>=none`; check_homebrew prints `cask=?`."""
    assert crc.serving(_rd(crc, "apt", False, "apt=none")) is None
    assert crc.serving(_rd(crc, "homebrew", False, "cask=?")) is None


def test_serving_reads_the_first_of_several_reported_versions(crc):
    """`_evidence` emits a comma-separated list with a trailing "(+n more)"."""
    r = _rd(crc, "docker", False, "tags=2.34.0,2.33.0 (+31 more)")
    assert crc.serving(r) == "2.34.0"


def test_an_unreachable_channel_is_not_a_regression_even_when_it_names_a_version(crc):
    """Rule 2 must not resurrect the UNKNOWN mistake rule 1 was careful about."""
    new = [_rd(crc, "homebrew", crc.UNKNOWN, "cask=2.18.2")]
    old = [_rd(crc, "homebrew", True, "cask=2.34.0")]
    assert crc.regressions(new, old) == []


def test_every_versioned_channel_reports_what_it_serves(crc, responses):
    """Locks the detail format rule 2 reads back.

    A check that stops emitting `<label>=<version>` would silently disable
    staleness detection for its channel while every test above still passed.
    """
    responses(
        {
            "homebrew-yazses": (200, b'cask "yazses" do\n  version "2.18.2"\nend\n'),
            "bucket/yazses.json": (200, _body({"version": "2.18.2"})),
            "gh-pages/apt/Packages": (200, b"Package: yazses\nVersion: 2.18.2\n"),
            "aur.archlinux.org": (200, _body({"results": [{"Version": "2.18.2-1"}]})),
            "api.snapcraft.io": (
                200,
                _body(
                    {"channel-map": [{"channel": {"name": "stable"}, "version": "2.18.2"}]}
                ),
            ),
        }
    )
    for key, fn in (
        ("homebrew", crc.check_homebrew),
        ("scoop", crc.check_scoop),
        ("apt", crc.check_apt),
        ("aur", crc.check_aur),
        ("snap", crc.check_snap),
    ):
        ok, detail = fn("2.35.0")
        assert ok is False, key
        served = crc.serving(crc.Result(key, key, ok, detail))
        assert served is not None, f"{key} reports no served version: {detail!r}"
        assert served.startswith("2.18.2"), (key, detail)
