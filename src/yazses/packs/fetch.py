"""Download one add-on pack from the running version's release (ADR-028 §3-§4).

**Egress — ADR-019 Class A, declared in ``FETCH_VIA``.** This is the only module that
starts a pack download. It imports no network primitive itself: it calls ADR-027's
allow-listed helpers in ``system/installer_update.py`` (``fetch_checksums``,
``expected_sha256``, ``download_verified``), which is why the egress test needs its
fourth scan to see it. What crosses the wire: an HTTP GET for ``SHA256SUMS.txt`` and one
for the ``.yazpack``, both under
``https://github.com/MSKazemi/yazses/releases/download/v<running version>/`` with
redirects only to GitHub's https asset hosts, the fixed asset headers, no cookie, no
token. No ``api.github.com`` call: the URLs are deterministic from the tag. It runs only
after a user confirmed enabling a feature or ``yazses packs install`` — never from the
daemon, the update watcher or the runtime hook (a closure test enforces that).

**Trust.** The pack must hash to the SHA-256 in the index **built into this installed
app**; ``download_verified`` checks that and deletes the file otherwise. The release's
``SHA256SUMS.txt`` is a second, independent check: its line must equal the embedded hash,
or the user is told the release has changed since this copy was built (the v2.32.0 case)
and nothing is downloaded.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yazses.packs.manifest import IndexEntry, PackIndex
from yazses.packs.policy import deadline_s, max_download_bytes
from yazses.system.installer_update import (
    CHECKSUMS_ASSET,
    RELEASE_DOWNLOAD_PREFIX,
    OpenUrl,
    ReleaseAsset,
    UpdateRefused,
    download_verified,
    expected_sha256,
    fetch_checksums,
)

__all__ = [
    "PackCancelled",
    "PackFetchError",
    "fetch_pack",
    "manual_steps",
    "pack_urls",
]

Progress = Callable[[str, "float | None"], None]


class PackCancelled(Exception):
    """The user cancelled. Raised from the progress callback, so ``download_verified``
    deletes its ``.part`` file on the way out."""


class PackFetchError(Exception):
    """The pack was not downloaded. ``str()`` is a user sentence; ``kind`` is one of
    ``offline``, ``checksum``, ``release-changed``, ``refused``."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _pretty(name: str) -> str:
    return name.replace("-", " ").title()


def pack_urls(index: PackIndex, entry: IndexEntry) -> tuple[str, str]:
    """``(SHA256SUMS.txt URL, pack URL)`` for the running version's tag — the only two
    URLs this module ever requests."""
    base = f"{RELEASE_DOWNLOAD_PREFIX}v{index.app_version}/"
    return base + CHECKSUMS_ASSET, base + entry.asset


def manual_steps(index: PackIndex, entry: IndexEntry) -> list[str]:
    """What a user can do by hand when the download cannot happen here."""
    _, url = pack_urls(index, entry)
    return [
        f"Check that this computer can reach github.com, then run: yazses packs install "
        f"{entry.name}",
        f"The add-on file is {entry.asset} on the v{index.app_version} release: {url}",
        f"Or download that file on another computer, copy it here, and run: yazses packs "
        f"install --from <path to {entry.asset}>",
    ]


def _is_network_error(exc: BaseException | None) -> bool:
    # `urllib.error.URLError` and socket timeouts are `OSError`s; tested without
    # importing urllib here, which would make this module a second downloader.
    return isinstance(exc, OSError)


def fetch_pack(
    index: PackIndex,
    entry: IndexEntry,
    dest_dir: Path,
    *,
    open_url: OpenUrl | None = None,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Path:
    """Download and verify ``entry`` into ``dest_dir``; return the archive's path.

    Raises :class:`PackCancelled` or :class:`PackFetchError` — never anything else for an
    expected failure. On every failure ``download_verified`` has deleted its ``.part``.
    Cancellation is checked before each request and on each progress report, which
    ``download_verified`` makes every 10 % (ADR-028 §4a records the finer ``cancel``
    hook as a follow-up refactor).
    """
    pretty = _pretty(entry.name)
    sums_url, pack_url = pack_urls(index, entry)

    def check_cancel() -> None:
        if cancel is not None and cancel():
            raise PackCancelled()

    def report(message: str, fraction: float | None) -> None:
        # Only mid-download: `download_verified`'s final "Checking the SHA-256…" report
        # sits outside its cleanup block, so cancelling there would strand the `.part`.
        if fraction is not None:
            check_cancel()
        if progress is not None:
            progress(message, fraction)

    def translate(exc: UpdateRefused) -> BaseException:
        cause: Any = exc.__cause__
        if isinstance(cause, PackCancelled):
            return cause
        if _is_network_error(cause):
            return PackFetchError("offline", (
                f"Couldn't reach github.com to download the {pretty} add-on. Check your "
                "connection or proxy and try again. Nothing was changed."
            ))
        if "does not match the SHA-256" in str(exc):
            return PackFetchError("checksum", (
                f"The {pretty} add-on did not match the checksum built into this copy of "
                "YazSes; it was deleted and nothing was installed."
            ))
        return PackFetchError("refused", (
            f"The {pretty} add-on was not downloaded: {exc}. Nothing was changed."
        ))

    check_cancel()
    try:
        if progress is not None:
            progress(f"Checking the v{index.app_version} release on github.com…", None)
        sums = fetch_checksums(sums_url, open_url=open_url)
        published = expected_sha256(sums, entry.asset)
    except UpdateRefused as exc:
        raise translate(exc) from exc
    if published != entry.sha256:
        raise PackFetchError("release-changed", (
            f"The release's {CHECKSUMS_ASSET} gives the {pretty} add-on a different "
            "SHA-256 than the one built into this copy of YazSes: the release assets "
            "have changed since this copy was built. Nothing was installed. Reinstall "
            "YazSes from the releases page to get a matching set."
        ))
    check_cancel()
    asset = ReleaseAsset(
        name=entry.asset, url=pack_url, size=entry.size,
        version=index.app_version, arch=index.arch,
    )
    try:
        return download_verified(
            asset,
            entry.sha256,
            dest_dir,
            open_url=open_url,
            progress=report,
            clock=clock,
            max_bytes=max_download_bytes(entry),
            deadline_s=deadline_s(entry.size),
        )
    except UpdateRefused as exc:
        raise translate(exc) from exc
