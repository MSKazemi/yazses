#!/usr/bin/env python3
"""Ask every distribution channel whether it actually has a given version.

Why this exists
---------------
v2.18.1 shipped Windows and macOS, no Linux package, and nothing on PyPI, and
was published as "Latest" anyway. Its Release workflow had failed in the test
job, so release-linux and publish-pypi were skipped -- but build-macos and
build-windows are separate workflows, so they succeeded and created the Release
themselves. Every workflow did its own job correctly. None was in a position to
ask whether *all* of it shipped.

Policy (owner, 2026-08-13): the newest version must carry a package on every
channel. Older versions need not -- a superseded release being incomplete is
history, not a live problem.

Verification gotcha this encodes
--------------------------------
`curl -o /dev/null -w '%{http_code}'` LIES about Flathub and search.nixos.org:
they are single-page apps that return HTTP 200 for pages that do not exist. Every
check below therefore queries a real API or a raw file path whose absence is a
genuine 404 -- never a rendered page.

Deliberately stdlib-only, like refresh-package-manifests.py, so it runs under a
bare /usr/bin/python3 in a CI job with nothing installed.

Usage
-----
    python scripts/check-release-channels.py --version 2.18.2
    python scripts/check-release-channels.py --version 2.18.2 --core-only
    python scripts/check-release-channels.py --version 2.18.2 --format json

Exit status is 1 if any channel lacks the version OR could not be reached.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

REPO = "MSKazemi/yazses"
# Must match the manifest, the metainfo and .github/workflows/flatpak.yml, all of
# which use com.mskazemi.YazSes (a domain the maintainer controls, as Flathub
# requires). This read io.github.mskazemi.YazSes until 2026-08-14. Both IDs 404
# today because the app is not on Flathub yet, so the gate looked healthy — it
# would have started reporting a published app as missing, forever, on the day
# the submission landed. A check against the wrong identifier does not fail; it
# lies quietly.
FLATPAK_ID = "com.mskazemi.YazSes"
TIMEOUT = 20
RETRIES = 3
RETRY_BACKOFF_S = 2

# A check answers one of three things, and conflating the last two is how a
# dropped connection gets reported as an unpublished package:
#   True  -- this channel has this version
#   False -- this channel answered, and does not have it
#   None  -- the channel could not be reached, so we do not know
UNKNOWN = None


def _verdict(status: int, published: bool) -> bool | None:
    """Map an HTTP status onto the tri-state. Status 0 means 'never answered'."""
    return UNKNOWN if status == 0 else published

# The channels CI itself produces. These are the ones whose absence means the
# release is actively broken for a user on that OS, so they alone justify
# demoting a release. Everything else is a publishing gap: real, worth failing
# the build over, but not a reason to relabel what did ship.
CORE = {"deb", "dmg", "exe", "pypi"}


@dataclass
class Result:
    key: str
    label: str
    ok: bool | None  # True published / False absent / None unreachable
    detail: str = ""
    core: bool = field(default=False)


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    """Return (status, body). Never raises for HTTP errors -- 404 is an answer.

    Status 0 means the request never completed (DNS, TLS, timeout, reset). That is
    NOT the same as a 404 and must never be read as "not published": on 2026-08-13
    a single dropped connection to aur.archlinux.org made this report the AUR as
    absent, and three retries a moment later all returned 200.

    Transient failures are retried before giving up, because most of them are.
    """
    req = urllib.request.Request(url, headers=headers or {})
    last = b""
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() if e.fp else b""
        except Exception as e:  # network/DNS/TLS
            last = str(e).encode()
            if attempt + 1 < RETRIES:
                time.sleep(RETRY_BACKOFF_S * (attempt + 1))
    return 0, last


def _json(url: str, headers: dict[str, str] | None = None):
    status, body = _get(url, headers)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


# --------------------------------------------------------------------------
# One function per channel. Each returns (published, detail), where `published`
# is True / False / UNKNOWN -- see the note on UNKNOWN above.
# --------------------------------------------------------------------------


def check_release_assets(version: str) -> dict[str, tuple[bool | None, str]]:
    """The three binaries attached to the GitHub Release, in one API call."""
    status, data = _json(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}")
    if status != 200 or not data:
        miss = f"release v{version} not found (HTTP {status})"
        if status == 0:
            miss = "github.com unreachable"
        return {k: (_verdict(status, False), miss) for k in ("deb", "dmg", "exe")}
    names = [a["name"] for a in data.get("assets", [])]
    out = {}
    for key, suffix in (("deb", ".deb"), ("dmg", ".dmg"), ("exe", ".exe")):
        hit = next((n for n in names if n.endswith(suffix)), None)
        out[key] = (hit is not None, hit or f"no {suffix} attached")
    return out


def check_pypi(version: str) -> tuple[bool | None, str]:
    status, _ = _get(f"https://pypi.org/pypi/yazses/{version}/json")
    return _verdict(status, status == 200), f"HTTP {status}"


def check_snap(version: str) -> tuple[bool | None, str]:
    status, data = _json(
        "https://api.snapcraft.io/v2/snaps/info/yazses?fields=version",
        {"Snap-Device-Series": "16"},
    )
    if status != 200 or not data:
        return _verdict(status, False), f"snapcraft API HTTP {status}"
    stable = [
        c.get("version")
        for c in data.get("channel-map", [])
        if c.get("channel", {}).get("name") == "stable"
    ]
    if not stable:
        return False, "no stable channel"
    return version in stable, f"stable={','.join(sorted(set(stable)))}"


def check_apt(version: str) -> tuple[bool | None, str]:
    status, body = _get(
        f"https://raw.githubusercontent.com/{REPO}/gh-pages/apt/Packages"
    )
    if status != 200:
        return _verdict(status, False), f"Packages HTTP {status}"
    found = re.findall(r"^Version:\s*(\S+)", body.decode("utf-8", "replace"), re.M)
    return version in found, f"apt={','.join(found[:3]) or 'none'}"


def check_homebrew(version: str) -> tuple[bool | None, str]:
    status, body = _get(
        "https://raw.githubusercontent.com/MSKazemi/homebrew-yazses/main/Casks/yazses.rb"
    )
    if status != 200:
        return _verdict(status, False), f"cask HTTP {status}"
    m = re.search(r'^\s*version\s+"([^"]+)"', body.decode("utf-8", "replace"), re.M)
    return (m is not None and m.group(1) == version), f"cask={m.group(1) if m else '?'}"


def check_scoop(version: str) -> tuple[bool | None, str]:
    status, data = _json(
        f"https://raw.githubusercontent.com/{REPO}/main/bucket/yazses.json"
    )
    if status != 200 or not data:
        return _verdict(status, False), f"bucket HTTP {status}"
    return data.get("version") == version, f"bucket={data.get('version')}"


def check_winget(version: str) -> tuple[bool | None, str]:
    # The upstream community repo, not our own copy of the manifests. Having them
    # in packaging/ installs nobody.
    url = (
        "https://api.github.com/repos/microsoft/winget-pkgs/contents/"
        f"manifests/m/MSKazemi/YazSes/{version}"
    )
    status, _ = _get(url)
    return _verdict(status, status == 200), f"winget-pkgs HTTP {status}"


def check_chocolatey(version: str) -> tuple[bool | None, str]:
    url = "https://community.chocolatey.org/api/v2/Packages()?$filter=Id%20eq%20'yazses'"
    status, body = _get(url)
    if status != 200:
        return _verdict(status, False), f"HTTP {status}"
    text = body.decode("utf-8", "replace")
    return f"<d:Version>{version}</d:Version>" in text, (
        "listed" if "<entry>" in text else "not listed"
    )


def check_aur(version: str) -> tuple[bool | None, str]:
    status, data = _json("https://aur.archlinux.org/rpc/v5/info?arg[]=yazses")
    if status != 200 or not data:
        return _verdict(status, False), f"AUR RPC HTTP {status}"
    results = data.get("results", [])
    if not results:
        return False, "not in AUR"
    got = results[0].get("Version", "")
    return got.split("-")[0] == version, f"aur={got}"


def check_flathub(version: str) -> tuple[bool | None, str]:
    # The API answers honestly; flathub.org itself returns 200 for missing apps.
    status, _ = _get(f"https://flathub.org/api/v2/appstream/{FLATPAK_ID}")
    return _verdict(status, status == 200), f"appstream HTTP {status}"


def check_nix(version: str) -> tuple[bool | None, str]:
    # search.nixos.org is an SPA and lies. A raw path in nixpkgs does not.
    status, _ = _get(
        "https://raw.githubusercontent.com/NixOS/nixpkgs/master/"
        "pkgs/by-name/ya/yazses/package.nix"
    )
    return _verdict(status, status == 200), f"nixpkgs HTTP {status}"


def check_docker(version: str) -> tuple[bool | None, str]:
    """GHCR needs a pull token even for public images; 401 is 'no such package'."""
    owner, image = REPO.split("/")
    status, tok = _json(
        f"https://ghcr.io/token?scope=repository:{owner.lower()}/{image}:pull&service=ghcr.io"
    )
    if status != 200 or not tok or "token" not in tok:
        return _verdict(status, False), f"token HTTP {status}"
    status, data = _json(
        f"https://ghcr.io/v2/{owner.lower()}/{image}/tags/list",
        {"Authorization": f"Bearer {tok['token']}"},
    )
    if status != 200 or not data:
        return _verdict(status, False), f"tags HTTP {status}"
    tags = data.get("tags") or []
    return version in tags, f"tags={','.join(tags[:4]) or 'none'}"


CHECKS = [
    ("pypi", "PyPI", check_pypi),
    ("snap", "Snap Store (stable)", check_snap),
    ("apt", "APT repo", check_apt),
    ("homebrew", "Homebrew tap", check_homebrew),
    ("scoop", "Scoop bucket", check_scoop),
    ("winget", "winget-pkgs", check_winget),
    ("chocolatey", "Chocolatey", check_chocolatey),
    ("aur", "AUR", check_aur),
    ("flathub", "Flathub", check_flathub),
    ("nix", "nixpkgs", check_nix),
    ("docker", "Docker (GHCR)", check_docker),
]

ASSET_LABELS = {"deb": "Linux .deb", "dmg": "macOS .dmg", "exe": "Windows .exe"}


def run(version: str, core_only: bool) -> list[Result]:
    results: list[Result] = []
    for key, (ok, detail) in check_release_assets(version).items():
        results.append(Result(key, ASSET_LABELS[key], ok, detail, core=True))

    if core_only:
        core = [r for r in results if r.key in CORE]
        ok, detail = check_pypi(version)
        core.append(Result("pypi", "PyPI", ok, detail, core=True))
        return core

    # Every check is an independent network round-trip against a different host,
    # so run them concurrently -- serially this took ~200s, which is too slow to
    # be worth running by hand, and a tool nobody runs locally is a tool that
    # only ever fails in CI.
    def one(item):
        key, label, fn = item
        try:
            ok, detail = fn(version)
        except Exception as e:  # a broken check must not hide the other thirteen
            # UNKNOWN, not False: a check that crashed has told us nothing about
            # whether the package is published.
            ok, detail = UNKNOWN, f"check errored: {type(e).__name__}"
        return Result(key, label, ok, detail, core=key in CORE)

    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        results.extend(pool.map(one, CHECKS))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", required=True, help="version without the leading v")
    ap.add_argument(
        "--core-only",
        action="store_true",
        help="only the channels CI produces (deb/dmg/exe/PyPI) -- used to decide "
        "whether a release is broken for users, as opposed to merely unpublished",
    )
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = ap.parse_args()

    results = run(args.version, args.core_only)
    # `is False` and `is None` are different answers and are reported separately.
    # Rolling them together is what made one dropped connection to the AUR read as
    # an unpublished package -- and "publish it again" is the wrong repair for a
    # network blip.
    missing = [r for r in results if r.ok is False]
    unknown = [r for r in results if r.ok is UNKNOWN]

    if args.format == "json":
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        print(f"## Release completeness — v{args.version}\n")
        print("| Channel | Published | Detail |")
        print("|---|---|---|")
        for r in results:
            mark = "✅" if r.ok else ("⚠️" if r.ok is UNKNOWN else "❌")
            print(f"| {r.label} | {mark} | {r.detail} |")
        print()
        if missing:
            print(f"**Missing ({len(missing)}):** " + ", ".join(r.label for r in missing))
        if unknown:
            print(
                f"**Could not check ({len(unknown)}):** "
                + ", ".join(r.label for r in unknown)
                + " — unreachable, not known to be absent."
            )
        if not missing and not unknown:
            print("**Every checked channel has this version.**")

    # Both are failures: one says a channel is behind, the other says we cannot
    # prove it is not. Neither should be reported as a complete release.
    return 1 if (missing or unknown) else 0


if __name__ == "__main__":
    sys.exit(main())
