"""One-click update for the Windows channels: plan, download, verify, hand off (ADR-027).

`yazses update` and the tray's *Check for updates…* used to stop at "download the newest
.exe and run it" for the Inno installer, so on Windows the update button found the update
and then handed the user a chore. This module turns that into one confirmed action:

1. **Plan** (pure): from the GitHub "latest release" JSON, pick the installer asset for
   this machine's architecture. Refuse a download URL that is not exactly under
   ``https://github.com/MSKazemi/yazses/releases/download/``. Refuse a version that is
   not *strictly* newer (``updater.is_newer``). Find the asset's SHA-256 in the release's
   own ``SHA256SUMS.txt``.
2. **Download** (I/O): to a per-user staging directory, with a size cap, a per-read
   timeout and an overall deadline, following redirects only to GitHub's https hosts.
3. **Verify**: the SHA-256 of the bytes written must equal the published one *before*
   anything runs. On a mismatch the file is deleted and the update refused.
4. **Hand off**: an installer cannot replace files that the process which launched it
   still holds open, so the job is given to the platform's :class:`UpdateLauncher`, which
   starts it detached; YazSes then shuts down. The detached job waits for YazSes to exit,
   checks the hash once more, runs the installer silently as an in-place upgrade, records
   the exit code and starts YazSes again — success or not.

Chocolatey, winget and Scoop already have an upgrade command (``updater.upgrade_command``)
and go through the same hand-off, because each of them also ends by running the Inno
installer over the files of the running app, and Scoop refuses outright while it runs.

**Trust model, stated plainly.** The installer is not code-signed yet. A SHA-256 taken
from the *same* release proves the file is the one that release published and that it
arrived intact; it does not prove who built it — someone able to replace the .exe on the
release could replace ``SHA256SUMS.txt`` too. Authenticode signing is the remaining step
and is recorded as such in ADR-027.

**Egress.** This module is a FETCH in ADR-019: it reads the release JSON and downloads
two files from ``github.com`` release assets — only after the user confirmed an update,
never in the background. Nothing about the user is sent.

Every network helper takes an injectable opener, so the decision logic and the download
loop are testable offline. Every public entry point answers with a result instead of
raising: a failed update must end in "here is how to update by hand", never a traceback.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yazses.system.updater import (
    RELEASES_URL,
    _github_version_from_json,
    is_newer,
    manual_update_steps,
    upgrade_command,
)

if TYPE_CHECKING:
    from yazses.platform.base import UpdateHandoff, UpdateLauncher

__all__ = [
    "CHECKSUMS_ASSET",
    "ONE_CLICK_METHODS",
    "HandoffResult",
    "InstallerAsset",
    "UpdateRefused",
    "build_handoff",
    "confirmation_prompt",
    "describe_handoff_result",
    "download_verified",
    "expected_sha256",
    "installer_arguments",
    "is_allowed_redirect",
    "is_trusted_download_url",
    "normalize_arch",
    "one_click_supported",
    "package_manager_argv",
    "parse_sha256sums",
    "plan_installer",
    "read_handoff_result",
    "start_one_click_update",
]

_RELEASES_API = "https://api.github.com/repos/MSKazemi/yazses/releases/latest"

#: The only place an installer may come from. Compared as a prefix of the *parsed* URL's
#: path on the exact host ``github.com`` — never as a substring of the raw string, which
#: ``https://github.com.evil.example/MSKazemi/yazses/releases/download/`` would pass.
RELEASE_DOWNLOAD_PREFIX = "https://github.com/MSKazemi/yazses/releases/download/"
_DOWNLOAD_HOST = "github.com"
_DOWNLOAD_PATH = "/MSKazemi/yazses/releases/download/"

#: Where github.com hands a release-asset download on to. Redirects anywhere else, or to
#: plain http, are refused.
_REDIRECT_HOSTS = frozenset({"github.com"})
_REDIRECT_SUFFIX = ".githubusercontent.com"

#: Published by `.github/workflows/checksums.yml` with `sha256sum`.
CHECKSUMS_ASSET = "SHA256SUMS.txt"

#: Methods the one-click hand-off covers. All four run the same Inno installer in the end.
ONE_CLICK_METHODS = ("windows-installer", "choco", "winget", "scoop")

#: Hard ceiling on what is downloaded, whatever the release JSON claims. The installer is
#: a few hundred MB; a response far beyond that is not our installer.
MAX_INSTALLER_BYTES = 1 << 30
MAX_CHECKSUMS_BYTES = 1 << 20
MAX_RELEASE_JSON_BYTES = 4 << 20
#: Per-read socket timeout, and the wall-clock budget for the whole download.
READ_TIMEOUT_S = 30.0
DOWNLOAD_DEADLINE_S = 30 * 60.0
_CHUNK = 1 << 16

#: Inno Setup switches for an unattended in-place upgrade. The AppId in
#: ``packaging/windows/installer.iss`` is stable, so Inno upgrades over the existing
#: install instead of beside it, reusing its directory and install mode
#: (``UsePreviousAppDir`` / ``UsePreviousPrivileges`` default to yes).
#: ``/CLOSEAPPLICATIONS`` + ``/FORCECLOSEAPPLICATIONS``: anything of ours still holding a
#: file (a tray the CLI could not stop) is closed through the Restart Manager rather than
#: failing the copy. ``/NORESTARTAPPLICATIONS``: the hand-off owns the relaunch, so the
#: Restart Manager must not start a second copy.
INSTALLER_SWITCHES = (
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/SP-",
    "/CLOSEAPPLICATIONS",
    "/FORCECLOSEAPPLICATIONS",
    "/NORESTARTAPPLICATIONS",
)

#: File names inside the launcher's staging directory.
PENDING_NAME = "pending.json"
RESULT_NAME = "exit-code.txt"
LOG_NAME = "update.log"
INSTALLER_LOG_NAME = "installer.log"

#: How long a hand-off may go without reporting before it is called lost.
_PENDING_GRACE_S = 30 * 60.0

#: ``YazSes-<version>-windows-<arch>.exe`` — the name `scripts/build-windows.ps1` produces.
_ASSET_RE = re.compile(
    r"^YazSes-(?P<version>[0-9][0-9A-Za-z.+!-]*)-windows-(?P<arch>x64|arm64)\.exe$"
)
_SHA_LINE = re.compile(r"^(?P<sha>[0-9a-fA-F]{64}) [ *](?P<name>\S.*)$")
_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")

Progress = Callable[[str, "float | None"], None]
"""``progress(message, fraction)``. ``fraction`` is ``None`` for a stage change and a
number in [0, 1] while downloading, so a tray can show stages and skip the percentages."""


class UpdateRefused(Exception):
    """The one-click update will not proceed; ``str(exc)`` is written for the user."""


@dataclass(frozen=True)
class InstallerAsset:
    name: str
    url: str
    size: int | None
    version: str
    arch: str
    #: ``sha256:<hex>`` from the release JSON, when GitHub supplies it. A second opinion
    #: only — the published SHA256SUMS.txt is still required.
    digest: str | None = None


@dataclass
class HandoffResult:
    """What a one-click attempt came to. ``ok`` means the detached job was started and
    YazSes should now shut down; anything else means stay running and show ``steps``."""

    ok: bool
    title: str
    message: str
    steps: list[str] = field(default_factory=list)
    log_file: Path | None = None


# ---- pure: architecture, URLs, assets --------------------------------------

def normalize_arch(raw: str | None) -> str:
    """Map an OS architecture string to the asset vocabulary ("x64", "arm64")."""
    value = (raw or "").strip().lower()
    if value in {"amd64", "x86_64", "x64", "em64t"}:
        return "x64"
    if value in {"arm64", "aarch64", "arm64ec"}:
        return "arm64"
    return value


def is_trusted_download_url(url: object) -> bool:
    """True only for ``https://github.com/MSKazemi/yazses/releases/download/<tag>/<file>``.

    Parsed, not substring-matched: no userinfo, no port, no query, no fragment, no
    ``..`` segment, exactly two path segments after the prefix.
    """
    if not isinstance(url, str):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.netloc != _DOWNLOAD_HOST or port is not None:
        return False
    if parts.query or parts.fragment or not parts.path.startswith(_DOWNLOAD_PATH):
        return False
    rest = parts.path[len(_DOWNLOAD_PATH):].split("/")
    if len(rest) != 2 or any(seg in {"", ".", ".."} for seg in rest):
        return False
    return "%2f" not in parts.path.lower() and "\\" not in parts.path


def is_allowed_redirect(url: object) -> bool:
    """Where a release download may be redirected: https, on github.com or a
    ``*.githubusercontent.com`` asset host, with no userinfo or odd port."""
    if not isinstance(url, str):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or "@" in parts.netloc or port not in (None, 443):
        return False
    return host in _REDIRECT_HOSTS or (
        host.endswith(_REDIRECT_SUFFIX) and len(host) > len(_REDIRECT_SUFFIX)
    )


def _assets(payload: Any) -> list[dict]:
    raw = payload.get("assets") if isinstance(payload, dict) else None
    return [a for a in raw if isinstance(a, dict)] if isinstance(raw, list) else []


def select_installer_asset(payload: Any, arch: str) -> InstallerAsset:
    """The installer for ``arch`` in a release payload. Raises :class:`UpdateRefused`.

    A native build is preferred. An ARM64 machine falls back to the x64 installer, which
    the .iss deliberately allows there (``ArchitecturesAllowed=x64compatible``) and which
    Windows runs under emulation — and which is the only Windows asset published while
    there is no native arm64 build. An x64 machine never takes an arm64 installer.
    """
    version = _github_version_from_json(payload) if isinstance(payload, dict) else None
    if not version:
        raise UpdateRefused("the latest GitHub release is missing, a draft or a prerelease")
    wanted = normalize_arch(arch)
    order = ["arm64", "x64"] if wanted == "arm64" else ["x64"] if wanted == "x64" else []
    if not order:
        raise UpdateRefused(f"there is no Windows installer for a {arch or 'unknown'} machine")
    found: dict[str, InstallerAsset] = {}
    for asset in _assets(payload):
        name = asset.get("name")
        if not isinstance(name, str):
            continue
        match = _ASSET_RE.match(name)
        if match is None or match.group("version") != version:
            continue
        url = asset.get("browser_download_url")
        if not is_trusted_download_url(url):
            raise UpdateRefused(f"{name} is not served from {RELEASE_DOWNLOAD_PREFIX}")
        assert isinstance(url, str)
        expected_tail = f"/{name}"
        if not url.endswith(expected_tail):
            raise UpdateRefused(f"{name}'s download URL names a different file")
        size = asset.get("size")
        digest = asset.get("digest")
        found[match.group("arch")] = InstallerAsset(
            name=name,
            url=url,
            size=size if isinstance(size, int) and not isinstance(size, bool) else None,
            version=version,
            arch=match.group("arch"),
            digest=digest if isinstance(digest, str) else None,
        )
    for candidate in order:
        if candidate in found:
            return found[candidate]
    raise UpdateRefused(f"release {version} has no Windows installer for {wanted}")


def checksums_url(payload: Any) -> str:
    """The trusted URL of the release's SHA256SUMS.txt. Raises :class:`UpdateRefused`."""
    for asset in _assets(payload):
        if asset.get("name") == CHECKSUMS_ASSET:
            url = asset.get("browser_download_url")
            if is_trusted_download_url(url) and isinstance(url, str):
                return url
            raise UpdateRefused(f"{CHECKSUMS_ASSET} is not served from {RELEASE_DOWNLOAD_PREFIX}")
    raise UpdateRefused(
        f"the release publishes no {CHECKSUMS_ASSET}, so the download could not be checked"
    )


def parse_sha256sums(text: str) -> dict[str, list[str]]:
    """``sha256sum`` output → ``{file name: [lower-case hex, ...]}``.

    A list per name, so a file listed twice with two different hashes can be refused
    rather than silently resolved to whichever line came last.
    """
    out: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        match = _SHA_LINE.match(line.strip())
        if match is None:
            continue
        name = match.group("name").strip()
        sha = match.group("sha").lower()
        if sha not in out.setdefault(name, []):
            out[name].append(sha)
    return out


def expected_sha256(sums_text: str, asset_name: str, *, api_digest: str | None = None) -> str:
    """The one SHA-256 the published checksum file gives ``asset_name``.

    Raises :class:`UpdateRefused` when the file does not list it, lists it with two
    different hashes, or disagrees with the ``sha256:`` digest GitHub reports for the
    asset (when it reports one).
    """
    hashes = parse_sha256sums(sums_text).get(asset_name, [])
    if not hashes:
        raise UpdateRefused(f"{CHECKSUMS_ASSET} does not list {asset_name}")
    if len(hashes) > 1:
        raise UpdateRefused(f"{CHECKSUMS_ASSET} lists {asset_name} with conflicting hashes")
    sha = hashes[0]
    if api_digest and api_digest.lower().startswith("sha256:"):
        if api_digest.split(":", 1)[1].strip().lower() != sha:
            raise UpdateRefused(
                f"{CHECKSUMS_ASSET} and GitHub disagree about {asset_name}'s SHA-256"
            )
    return sha


def plan_installer(payload: Any, current: str, arch: str) -> InstallerAsset:
    """Pick the installer to download, or refuse. Strictly-newer releases only."""
    asset = select_installer_asset(payload, arch)
    if not is_newer(asset.version, current):
        raise UpdateRefused(f"{asset.version} is not newer than the running {current}")
    if asset.size is not None and asset.size > MAX_INSTALLER_BYTES:
        raise UpdateRefused(f"{asset.name} is larger than the {MAX_INSTALLER_BYTES >> 20} MB cap")
    return asset


def installer_arguments(log_file: Path) -> list[str]:
    """The Inno Setup command line for the silent in-place upgrade."""
    return [*INSTALLER_SWITCHES, f"/LOG={log_file}"]


def package_manager_argv(method: str) -> tuple[list[str], bool, bool]:
    """``(argv, elevate, capture_output)`` for a package-manager hand-off.

    Built on ``updater.upgrade_command`` so there is one source for each command, plus
    what an unattended, windowless run needs: winget must not stop to ask about source
    agreements in a window nobody can see, and Chocolatey writes to ``ProgramData`` and
    so needs administrator rights (a UAC prompt) — across which Windows will not redirect
    output, so its own log (``%ProgramData%\\chocolatey\\logs``) is where its output goes.
    """
    command = upgrade_command(method)
    if not command or method not in ONE_CLICK_METHODS or method == "windows-installer":
        raise UpdateRefused(f"no package-manager upgrade for a {method} install")
    if method == "winget":
        return (
            [*command, "--silent", "--accept-source-agreements",
             "--accept-package-agreements", "--disable-interactivity"],
            False,
            True,
        )
    if method == "choco":
        return [*command, "--no-progress"], True, False
    return list(command), False, True


def one_click_supported(status: Any, launcher: UpdateLauncher | None) -> bool:
    """True when ``status`` is an available update this machine can hand off."""
    return bool(
        launcher is not None
        and getattr(status, "available", False)
        and getattr(status, "latest", None)
        and getattr(status, "method", "") in ONE_CLICK_METHODS
    )


def confirmation_prompt(status: Any) -> tuple[str, str]:
    """``(title, text)`` for the yes/no question asked before anything is downloaded."""
    method = getattr(status, "method", "")
    head = f"YazSes {status.current} → {status.latest} is available."
    closing = (
        "YazSes will close, update, and start again by itself. Your settings and "
        "models are kept."
    )
    if method == "windows-installer":
        body = (
            f"{head}\n\nDownload the installer from github.com, check its SHA-256 against "
            f"the release's {CHECKSUMS_ASSET}, and install it in place?\n\n{closing}\n\n"
            "If YazSes was installed for all users, Windows will ask for administrator "
            "permission.\n\nThe installer is not code-signed yet: the checksum proves the "
            "file is the one this release published, not who built it."
        )
    else:
        argv, elevate, _ = package_manager_argv(method)
        body = f"{head}\n\nRun  {' '.join(argv)}  now?\n\n{closing}"
        if elevate:
            body += "\n\nChocolatey needs administrator rights, so Windows will ask."
    return "Install the YazSes update?", body


# ---- I/O: fetching and downloading ------------------------------------------

class _GithubOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a host :func:`is_allowed_redirect` accepts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not is_allowed_redirect(newurl):
            raise urllib.error.HTTPError(
                newurl, code, f"refused redirect to {newurl!r}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OpenUrl = Callable[[str, float], Any]
"""``open_url(url, timeout)`` → a context manager with ``.read(n)``. Injected in tests."""


def _default_open(url: str, timeout: float) -> Any:
    opener = urllib.request.build_opener(_GithubOnlyRedirects())
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "yazses-updater", "Accept": "application/octet-stream"},
    )
    return opener.open(req, timeout=timeout)  # noqa: S310 (https, allowlisted)


def _read_bounded(url: str, limit: int, *, open_url: OpenUrl, timeout: float) -> bytes:
    with open_url(url, timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise UpdateRefused(f"{url} is larger than expected")
    return data


def fetch_release_payload(*, open_url: OpenUrl | None = None, timeout: float = 10.0) -> dict:
    """The GitHub "latest release" JSON. Raises :class:`UpdateRefused` on any failure."""
    opener = open_url or _default_open
    try:
        raw = _read_bounded(_RELEASES_API, MAX_RELEASE_JSON_BYTES, open_url=opener, timeout=timeout)
        payload = json.loads(raw.decode("utf-8"))
    except UpdateRefused:
        raise
    except Exception as exc:
        raise UpdateRefused(f"could not read the release from github.com ({exc})") from exc
    if not isinstance(payload, dict):
        raise UpdateRefused("github.com returned something that is not a release")
    return payload


def fetch_checksums(url: str, *, open_url: OpenUrl | None = None, timeout: float = 10.0) -> str:
    if not is_trusted_download_url(url):
        raise UpdateRefused(f"refusing to fetch checksums from {url}")
    try:
        raw = _read_bounded(url, MAX_CHECKSUMS_BYTES, open_url=open_url or _default_open,
                            timeout=timeout)
        return raw.decode("utf-8", errors="replace")
    except UpdateRefused:
        raise
    except Exception as exc:
        raise UpdateRefused(f"could not download {CHECKSUMS_ASSET} ({exc})") from exc


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def download_verified(
    asset: InstallerAsset,
    sha256: str,
    dest_dir: Path,
    *,
    open_url: OpenUrl | None = None,
    progress: Progress | None = None,
    clock: Callable[[], float] = time.monotonic,
    max_bytes: int = MAX_INSTALLER_BYTES,
    deadline_s: float = DOWNLOAD_DEADLINE_S,
    read_timeout_s: float = READ_TIMEOUT_S,
) -> Path:
    """Download ``asset`` into ``dest_dir`` and return its path — only if it verifies.

    Written to ``<name>.part`` and renamed once complete and checked, so a partial or
    tampered file never sits under the name that will be run. Refuses (and deletes) on:
    more bytes than the cap or than the release declared, fewer than declared, a blown
    deadline, a network error, or a SHA-256 that differs from ``sha256``.
    """
    if not is_trusted_download_url(asset.url):
        raise UpdateRefused(f"refusing to download from {asset.url}")
    if not _SHA_HEX.match(sha256 or ""):
        raise UpdateRefused("no valid SHA-256 to check the download against")
    limit = min(max_bytes, asset.size) if asset.size is not None else max_bytes
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / asset.name
    part = dest_dir / (asset.name + ".part")
    _unlink(part)
    _unlink(final)
    digest = hashlib.sha256()
    written = 0
    started = clock()
    next_report = 0.1
    try:
        opener = open_url or _default_open
        with opener(asset.url, read_timeout_s) as resp, part.open("wb") as out:
            while True:
                if clock() - started > deadline_s:
                    raise UpdateRefused("the download took too long and was stopped")
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise UpdateRefused(
                        f"{asset.name} is larger than the release says it is — stopped"
                    )
                digest.update(chunk)
                out.write(chunk)
                if progress is not None and asset.size:
                    fraction = written / asset.size
                    if fraction >= next_report:
                        progress(f"Downloading… {int(fraction * 100)}%", min(fraction, 1.0))
                        next_report = fraction + 0.1
    except UpdateRefused:
        _unlink(part)
        raise
    except Exception as exc:
        _unlink(part)
        raise UpdateRefused(f"the download failed ({exc})") from exc
    if asset.size is not None and written != asset.size:
        _unlink(part)
        raise UpdateRefused(f"the download stopped early ({written} of {asset.size} bytes)")
    if progress is not None:
        progress("Checking the SHA-256…", None)
    if digest.hexdigest() != sha256.lower():
        _unlink(part)
        raise UpdateRefused(
            f"{asset.name} does not match the SHA-256 published in {CHECKSUMS_ASSET}. "
            "It was deleted and nothing was installed."
        )
    try:
        part.replace(final)
    except OSError as exc:
        _unlink(part)
        raise UpdateRefused(f"could not save the installer ({exc})") from exc
    return final


# ---- the hand-off ---------------------------------------------------------

def build_handoff(
    *,
    kind: str,
    argv: list[str],
    elevate: bool,
    capture_output: bool,
    wait_pids: list[int] | tuple[int, ...],
    relaunch: list[str],
    staging: Path,
    sha256: str = "",
    cleanup: tuple[Path, ...] = (),
) -> UpdateHandoff:
    """Assemble the job description the launcher carries out (pure)."""
    from yazses.platform.base import UpdateHandoff

    pids = tuple(sorted({int(p) for p in wait_pids if isinstance(p, int) and p > 0}))
    return UpdateHandoff(
        kind=kind,
        argv=tuple(argv),
        elevate=elevate,
        wait_pids=pids,
        relaunch=tuple(relaunch),
        log_file=staging / LOG_NAME,
        result_file=staging / RESULT_NAME,
        cleanup=cleanup,
        capture_output=capture_output,
        sha256=sha256,
    )


def _fallback(status: Any, title: str, reason: str) -> HandoffResult:
    method = getattr(status, "method", "")
    return HandoffResult(
        ok=False,
        title=title,
        message=f"{reason}\nNothing was installed; YazSes keeps running.",
        steps=list(getattr(status, "steps", None) or manual_update_steps(method)),
    )


def _clear_stale(staging: Path) -> None:
    """Remove a previous attempt's downloads. Never raises."""
    try:
        for child in staging.iterdir():
            if child.suffix.lower() in {".exe", ".part"} and child.is_file():
                _unlink(child)
    except OSError:
        pass


def start_one_click_update(
    status: Any,
    launcher: UpdateLauncher | None,
    *,
    wait_pids: list[int] | tuple[int, ...] = (),
    progress: Progress | None = None,
    fetch_payload: Callable[[], dict] | None = None,
    fetch_sums: Callable[[str], str] | None = None,
    download: Callable[..., Path] | None = None,
    now: Callable[[], float] = time.time,
) -> HandoffResult:
    """Check → download → verify → hand off. Never raises.

    On ``ok`` the detached job has been started and the caller must now shut YazSes
    down (the job waits for ``wait_pids`` to exit). On anything else nothing has been
    started, any download has been deleted, and ``steps`` are the manual way.
    """
    title = "Update not installed"
    if not one_click_supported(status, launcher):
        return _fallback(status, title, "One-click update is not available for this install.")
    assert launcher is not None
    method = status.method
    try:
        relaunch = launcher.relaunch_command()
        if not relaunch:
            raise UpdateRefused("could not tell where YazSes is installed, to restart it")
        staging = launcher.staging_dir()
        staging.mkdir(parents=True, exist_ok=True)
        _clear_stale(staging)
        if method == "windows-installer":
            if progress is not None:
                progress("Looking up the release on github.com…", None)
            payload = (fetch_payload or fetch_release_payload)()
            asset = plan_installer(payload, status.current, launcher.native_arch())
            sums = (fetch_sums or fetch_checksums)(checksums_url(payload))
            sha = expected_sha256(sums, asset.name, api_digest=asset.digest)
            if progress is not None:
                size = f" ({asset.size / 1e6:.0f} MB)" if asset.size else ""
                progress(f"Downloading YazSes {asset.version}{size}…", None)
            path = (download or download_verified)(asset, sha, staging, progress=progress)
            handoff = build_handoff(
                kind="installer",
                argv=[str(path), *installer_arguments(staging / INSTALLER_LOG_NAME)],
                elevate=False,
                capture_output=False,
                wait_pids=wait_pids,
                relaunch=relaunch,
                staging=staging,
                sha256=sha,
                cleanup=(path,),
            )
            target = asset.version
        else:
            argv, elevate, capture = package_manager_argv(method)
            handoff = build_handoff(
                kind="package-manager",
                argv=argv,
                elevate=elevate,
                capture_output=capture,
                wait_pids=wait_pids,
                relaunch=relaunch,
                staging=staging,
            )
            target = str(status.latest)
        _write_pending(staging, {
            "from": str(status.current),
            "to": target,
            "method": method,
            "log": str(handoff.log_file),
            "started": now(),
        })
        _unlink(handoff.result_file)
        try:
            launcher.hand_off(handoff)
        except Exception as exc:
            _unlink(staging / PENDING_NAME)
            for leftover in handoff.cleanup:
                _unlink(leftover)
            raise UpdateRefused(f"could not start the installer ({exc})") from exc
    except UpdateRefused as exc:
        return _fallback(status, title, f"The update was not installed: {exc}.")
    except Exception as exc:  # pragma: no cover - belt and braces: never a traceback
        return _fallback(status, title, f"The update was not installed: unexpected error ({exc}).")
    if progress is not None:
        progress("Installing — YazSes will close and start again by itself.", None)
    return HandoffResult(
        ok=True,
        title=f"Installing YazSes {target}",
        message=(
            f"YazSes is closing to install {target}. It starts again by itself when "
            f"the installer finishes.\nLog: {handoff.log_file}"
        ),
        log_file=handoff.log_file,
    )


# ---- reporting what the hand-off did, on the next start ------------------

def _write_pending(staging: Path, record: dict) -> None:
    (staging / PENDING_NAME).write_text(json.dumps(record, indent=2), encoding="utf-8")


def _parse_exit(text: str | None) -> int | None:
    try:
        return int((text or "").strip().lstrip("﻿"))
    except ValueError:
        return None


def describe_handoff_result(
    pending: dict, exit_text: str | None, running: str
) -> tuple[str, str] | None:
    """``(title, body)`` for what the last hand-off did, judged by the version *now
    running* — an exit code of 0 is not evidence the version moved (pure)."""
    if not isinstance(pending, dict):
        return None
    target = str(pending.get("to") or "")
    before = str(pending.get("from") or "")
    if not target:
        return None
    if running == target or (before and is_newer(running, before)):
        return ("YazSes updated", f"Updated {before} → {running}.")
    code = _parse_exit(exit_text)
    if code is None:
        reason = "The updater did not report back."
    elif code == -1:
        reason = (
            "The installer could not be started (if Windows asked for administrator "
            "permission, it was declined)."
        )
    elif code == -2:
        reason = (
            "The installer failed its last SHA-256 check just before it would have "
            "run, so it was deleted unrun."
        )
    elif code in (2, 5, 1223):
        reason = "The installation was cancelled."
    elif code == 0:
        reason = "The installer finished without an error but did not change the version."
    else:
        reason = f"The installer exited with code {code}."
    lines = [
        f"The update to {target} did not install — YazSes is still {running}.",
        reason,
        f"Update by hand: {RELEASES_URL}",
    ]
    log = pending.get("log")
    if log:
        lines.append(f"Log: {log}")
    return ("Update did not install", "\n".join(lines))


def read_handoff_result(
    staging: Path, running: str, *, now: Callable[[], float] = time.time
) -> tuple[str, str] | None:
    """Report the last hand-off once, then forget it. Never raises.

    Left alone while a job may still be running (no exit code yet, and younger than the
    grace period) — a tray started by hand mid-install must not call it failed.
    """
    pending_path = staging / PENDING_NAME
    result_path = staging / RESULT_NAME
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        exit_text: str | None = result_path.read_text(encoding="utf-8-sig")
    except OSError:
        exit_text = None
    if exit_text is None:
        started = pending.get("started") if isinstance(pending, dict) else None
        if isinstance(started, (int, float)) and now() - started < _PENDING_GRACE_S:
            return None
    _unlink(pending_path)
    _unlink(result_path)
    return describe_handoff_result(pending, exit_text, running)
