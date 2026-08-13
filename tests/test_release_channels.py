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
                            {"name": "YazSes-2.18.2.dmg"},
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
                            {"name": "YazSes-2.18.1.dmg"},
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
                            {"name": "a.deb"},
                            {"name": "b.dmg"},
                            {"name": "c.exe"},
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
    responses({})  # everything absent
    results = crc.run("9.9.9", core_only=False)
    keys = {r.key for r in results}
    assert keys == {"deb", "dmg", "exe"} | {k for k, _, _ in crc.CHECKS}
    assert not any(r.ok for r in results)


def test_a_check_that_raises_does_not_hide_the_others(crc, responses, monkeypatch):
    """One broken channel must not take the whole report down with it."""
    responses({"api.github.com": (200, _body({"assets": [{"name": "a.deb"}]}))})

    def boom(_version):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(crc, "CHECKS", [("pypi", "PyPI", boom)])
    results = crc.run("2.18.2", core_only=False)
    pypi = next(r for r in results if r.key == "pypi")
    assert pypi.ok is False
    assert "RuntimeError" in pypi.detail
    # The asset checks still reported.
    assert next(r for r in results if r.key == "deb").ok is True
