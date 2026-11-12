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
import urllib.parse
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

# Everything this tag push publishes on its own, CORE plus the container image.
# Distinct from CORE on purpose: this set answers "has CI finished?", which is a
# question about *waiting*, while CORE answers "is the release broken for a user
# on that OS?", which is what may demote a release. Docker belongs in the first
# and not the second -- a missing image is a gap in reach, not a broken download.
#
# It exists so the wait and the verdict share one implementation. They did not
# before: release-complete.yml counted assets in bash and hardened that count to
# two-per-platform, while the script it then asked for the verdict still accepted
# one of a pair. Two implementations of "is this published" is what let those
# drift, so there is now one.
CI_PUBLISHED = CORE | {"docker"}


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
        # TWO of each -- one per architecture. Taking the first match called a
        # platform published on one of a pair, which is exactly what let v2.20.0
        # and v2.21.0 certify "All platforms published" while carrying no Intel
        # bundle. release-complete.yml's wait loop was hardened to `> 1` at the
        # time; this, the check it delegates the *verdict* to, was not -- so the
        # summary table and `--core-only` both still accepted a half-built
        # release, and --core-only is what decides whether it keeps "Latest".
        #
        # Windows is the exception: it is x64 only since v2.43.1 (the "arm64"
        # installer was an x64 build; see build-windows.yml), so the one .exe
        # that must be there is the x64 one. Requiring a pair demoted v2.43.1 to
        # a pre-release the moment it was tagged.
        hits = sorted(n for n in names if n.endswith(suffix))
        if key == "exe":
            if any(n.endswith("-windows-x64.exe") for n in hits):
                out[key] = (True, ", ".join(hits))
            else:
                out[key] = (False, "no windows-x64.exe attached")
            continue
        if not hits:
            out[key] = (False, f"no {suffix} attached")
        elif len(hits) == 1:
            out[key] = (False, f"only {hits[0]} — one architecture of a pair")
        else:
            out[key] = (True, ", ".join(hits))
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


def _evidence(label: str, found: list[str], version: str, limit: int = 4) -> str:
    """Report evidence that supports the verdict rather than the head of a list.

    Both of these truncated with ``[:n]``, and a registry returns tags roughly in
    insertion order — so GHCR carrying 2.22.0 was reported as ``tags=2.18.2,2.19.0``
    and read exactly like an image three releases behind. The verdict was right the
    whole time; the evidence beside it said the opposite, which is worse than no
    evidence because it invites the reader to distrust the correct answer.

    So: name the queried version first when it is present, then the tail, which is
    where a recent release actually lands.
    """
    if not found:
        return f"{label}=none"
    if version in found:
        rest = [v for v in found if v != version][-(limit - 1):]
        shown = [version, *rest]
    else:
        shown = found[-limit:]
    more = "" if len(shown) >= len(found) else f" (+{len(found) - len(shown)} more)"
    return f"{label}={','.join(shown)}{more}"


def check_apt(version: str) -> tuple[bool | None, str]:
    status, body = _get(
        f"https://raw.githubusercontent.com/{REPO}/gh-pages/apt/Packages"
    )
    if status != 200:
        return _verdict(status, False), f"Packages HTTP {status}"
    found = re.findall(r"^Version:\s*(\S+)", body.decode("utf-8", "replace"), re.M)
    return version in found, _evidence("apt", found, version, limit=3)


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
    # Ask for this exact version rather than listing the package. The OData feed
    # pages at 15 entries in no particular version order and links the rest from
    # `rel="next"`, so a list-and-search verdict is only right while the package
    # has fewer versions than one page -- the same single-page truncation that made
    # `check_docker` report a published image as missing (#844).
    quoted = version.replace("'", "''")
    flt = urllib.parse.quote(f"Id eq 'yazses' and Version eq '{quoted}'", safe="")
    url = f"https://community.chocolatey.org/api/v2/Packages()?$filter={flt}"
    status, body = _get(url)
    if status != 200:
        return _verdict(status, False), f"HTTP {status}"
    text = body.decode("utf-8", "replace")
    if f"<d:Version>{version}</d:Version>" not in text:
        return False, "not listed"
    # The feed also serves versions that are merely *submitted*: moderation has not
    # approved them, `choco install` cannot fetch them, and the entry still carries
    # the exact version. v2.51.0 sat like that from 2026-11-07 while this check said
    # "published". Only an explicit IsApproved=true counts.
    approved = re.search(r"<d:IsApproved[^>]*>\s*(true|false)\s*</d:IsApproved>", text)
    if approved is None:
        return UNKNOWN, "feed does not say whether this version is approved"
    if approved.group(1) == "true":
        return True, "listed"
    status = re.search(r"<d:PackageStatus>([^<]*)</d:PackageStatus>", text)
    return False, f"not approved (status {status.group(1) if status else 'unknown'})"


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


# Every manifest media type GHCR may hold for a tag; a multi-arch tag is an index.
_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

# GHCR returns at most 100 tags a page. 10 pages is 1000 tags, an order of
# magnitude past today's ~105. Only the human-readable evidence depends on this,
# never the verdict, so reaching the cap costs a shorter "tags=" line, not a lie.
_TAG_PAGE_SIZE = 100
_TAG_MAX_PAGES = 10


def _ghcr_tags(base: str, headers: dict[str, str]) -> list[str]:
    """Every tag the registry will list, following OCI ``last=`` pagination.

    Best effort and evidence only: a failed or truncated listing returns what was
    read so far. ``check_docker`` never derives its verdict from this.
    """
    tags: list[str] = []
    last = ""
    for _ in range(_TAG_MAX_PAGES):
        url = f"{base}/tags/list?n={_TAG_PAGE_SIZE}"
        if last:
            url += "&last=" + urllib.parse.quote(last, safe="")
        status, data = _json(url, headers)
        page = (data or {}).get("tags") if status == 200 else None
        if not page or page[-1] == last:
            break
        tags.extend(page)
        last = page[-1]
    return tags


def _version_key(tag: str) -> tuple[int, tuple[int, ...], str]:
    """Order tags so the tail is the newest release rather than the lexical last.

    The registry sorts lexically, so ``2.9.0`` lands after ``2.48.1``. Plain
    version numbers sort numerically after everything else (``latest``, branches).
    """
    if re.fullmatch(r"\d+(?:\.\d+)*", tag):
        return 1, tuple(int(p) for p in tag.split(".")), tag
    return 0, (), tag


def check_docker(version: str) -> tuple[bool | None, str]:
    """GHCR needs a pull token even for public images; 401 is 'no such package'.

    The verdict comes from asking for the manifest of exactly this tag: 200 means
    published, 404 means it is not. It must NOT come from searching ``tags/list``.
    That endpoint pages at 100 tags, sorted lexically, and attestation artifacts
    (``sha256-…``) are tags too -- so once the package passed 100 tags (2026-11-04:
    105, 40 of them ``sha256-…``) every release after ``2.47.x`` fell on page two
    and was reported missing while ``docker pull`` worked (#844). It would have
    recurred on every later release as tags accumulate.
    """
    owner, image = REPO.split("/")
    base = f"https://ghcr.io/v2/{owner.lower()}/{image}"
    status, tok = _json(
        f"https://ghcr.io/token?scope=repository:{owner.lower()}/{image}:pull&service=ghcr.io"
    )
    if status != 200 or not tok or "token" not in tok:
        # A token endpoint that is down says nothing about the image.
        if status == 429 or status >= 500:
            return UNKNOWN, f"token HTTP {status}"
        return _verdict(status, False), f"token HTTP {status}"
    headers = {"Authorization": f"Bearer {tok['token']}"}
    status, _ = _get(
        f"{base}/manifests/{urllib.parse.quote(version, safe='')}",
        {**headers, "Accept": _MANIFEST_ACCEPT},
    )
    # Only a definite answer is a verdict: 200 published; 404 (or the 401/403 GHCR
    # gives a package it will not show) not published. Never-answered, 429 and 5xx
    # mean the registry failed to answer, and reporting that as "missing" is how a
    # blip becomes a false alarm or a demotion.
    if status != 200 and status not in (401, 403, 404):
        return UNKNOWN, f"manifest HTTP {status}"
    # `sha256-…` entries are the attestation/referrer artifacts the attest step
    # pushes alongside the image. They are tags as far as the registry is concerned
    # and noise as far as a human reading "is 2.22.0 published?" is concerned, so
    # they are excluded from the evidence -- never from the verdict.
    readable = sorted(
        (t for t in _ghcr_tags(base, headers) if not t.startswith("sha256-")),
        key=_version_key,
    )
    if status == 200:
        if version not in readable:  # listing failed or capped; the manifest is the proof
            readable.append(version)
        return True, _evidence("tags", readable, version)
    if not readable:
        return False, f"manifest HTTP {status}"
    return False, _evidence("tags", readable, version)


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


def run(version: str, core_only: bool, ci_only: bool = False) -> list[Result]:
    results: list[Result] = []
    for key, (ok, detail) in check_release_assets(version).items():
        results.append(Result(key, ASSET_LABELS[key], ok, detail, core=True))

    if core_only or ci_only:
        subset = [r for r in results if r.key in CORE]
        ok, detail = check_pypi(version)
        subset.append(Result("pypi", "PyPI", ok, detail, core=True))
        if ci_only:
            ok, detail = check_docker(version)
            subset.append(Result("docker", "Docker (GHCR)", ok, detail))
        return subset

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


# A detail of the form "<label>=<version>" is a channel telling us what it is
# actually serving right now; anything else ("HTTP 404", "not listed", "not in
# AUR", "cask HTTP 404") is a channel that has nothing to serve. That format is
# produced by the checks in this same module -- `_evidence` and its siblings --
# so reading it back is an internal contract rather than prose-parsing, and
# `test_every_versioned_channel_reports_what_it_serves` fails the build if a
# check stops honouring it.
#
# One uniform rule, not a per-channel table: a hand-written list of "channels
# that report a version" would be wrong the day a channel is added, and nothing
# would say so.
_SERVING_RE = re.compile(r"^[a-z-]+=(\S+)")

# `_evidence` prints "<label>=none" for an index it read successfully that
# contained no versions, and check_homebrew prints "cask=?" when the cask parses
# but carries no version line. Neither is a version being served.
_NOT_A_VERSION = {"none", "?"}


def serving(result: Result) -> str | None:
    """The version this channel says it is serving, or None if it has none.

    This is what separates "never wired up" from "published once and then
    frozen" WITHOUT consulting history -- the channel itself is asked, which is
    the only place that knows.
    """
    m = _SERVING_RE.match(result.detail)
    if not m:
        return None
    value = m.group(1).split(",")[0]
    return None if value in _NOT_A_VERSION else value


def regressions(new: list[Result], old: list[Result]) -> list[Result]:
    """Channels that have gone backwards: they should carry this release and do not.

    "Missing" and "regressed" are different findings and only the second one is
    actionable on a schedule. Several of this project's channels (Flathub,
    nixpkgs, winget, Chocolatey) have no credential wired up, so they are absent
    for EVERY version -- a daily watcher reporting them would file the same
    standing issue forever and teach its reader to close it unread.

    A channel qualifies as regressed two ways, and the second one exists because
    the first has a blind spot that hid a real fault for seventeen releases:

    1. The previous release reached it and this one did not. This catches a
       channel the moment it breaks.

    2. It is serving a concrete version that is not this one. This catches a
       channel that broke and STAYED broken -- which (1) cannot, because the
       previous release did not reach it either, so it becomes its own baseline
       and drops out of the comparison permanently.

    (2) is not hypothetical. The Homebrew tap froze at 2.18.2 on 2026-08-13
    because `TAP_TOKEN` was never set, so the publish job took its skip branch
    and reported success. This watcher was written on 2026-08-26 -- by which
    time the tap was already stale, hence already baseline -- and so it reported
    "every channel that carried v2.34.0 also has v2.35.0" every single day while
    `brew install --cask yazses` served a build seventeen releases old. A user
    installed it and reported the macOS bugs that had been fixed in between as
    still broken, which is how this was finally noticed.

    Note the two rules use different evidence on purpose: (1) is historical and
    (2) is present-tense. A channel that reports no version at all ("HTTP 404",
    "not in AUR") is never called stale by (2) -- absence is not staleness.

    A channel that is UNREACHABLE now is never called a regression by either
    rule: not being able to ask is not an answer (see ``_get``). It is reported
    separately.
    """
    was_published = {r.key for r in old if r.ok is True}
    return [
        r
        for r in new
        if r.ok is False and (r.key in was_published or serving(r) is not None)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", required=True, help="version without the leading v")
    ap.add_argument(
        "--core-only",
        action="store_true",
        help="only the channels CI produces (deb/dmg/exe/PyPI) -- used to decide "
        "whether a release is broken for users, as opposed to merely unpublished",
    )
    ap.add_argument(
        "--ci-only",
        action="store_true",
        help="only the channels this tag push publishes itself (CORE plus the "
        "container image) -- used to wait for CI to finish before reporting, so "
        "an in-flight channel is never named as missing",
    )
    ap.add_argument(
        "--compare-with",
        metavar="VERSION",
        help="report only channels that carried VERSION and not --version, i.e. "
        "channels that went BACKWARDS. Used by the scheduled drift watch, where "
        "a channel this project has never published to is not news.",
    )
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = ap.parse_args()

    results = run(args.version, args.core_only, args.ci_only)
    # `is False` and `is None` are different answers and are reported separately.
    # Rolling them together is what made one dropped connection to the AUR read as
    # an unpublished package -- and "publish it again" is the wrong repair for a
    # network blip.
    if args.compare_with:
        previous = run(args.compare_with, args.core_only, args.ci_only)
        results = regressions(results, previous) + [
            r for r in results if r.ok is UNKNOWN
        ]

    missing = [r for r in results if r.ok is False]
    unknown = [r for r in results if r.ok is UNKNOWN]

    if args.format == "json":
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        headline = f"## Release completeness — v{args.version}"
        if args.compare_with:
            headline += f" (channels that carried v{args.compare_with})"
        print(headline + "\n")
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
            if args.compare_with:
                print(
                    f"**Every channel that carried v{args.compare_with} also has "
                    f"v{args.version}.**"
                )
            else:
                print("**Every checked channel has this version.**")

    # Both are failures: one says a channel is behind, the other says we cannot
    # prove it is not. Neither should be reported as a complete release.
    return 1 if (missing or unknown) else 0


if __name__ == "__main__":
    sys.exit(main())
