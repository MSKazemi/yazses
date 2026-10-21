"""ADR-028 §4: what a pack install actually puts on the wire.

Every ``urllib.request.Request`` the **real default opener** builds during a pack fetch is
captured (the opener's ``open`` is replaced; nothing leaves the machine). Its URL must be
one of the two URLs computed from the running version's tag, its headers must equal the
release-asset headers exactly, and ``api.github.com`` is never contacted — the test
ADR-027 wished it had before its 415.
"""
from __future__ import annotations

import io
import urllib.request

import pytest

from tests.packs_fixtures import build_pack
from yazses.packs.fetch import PackFetchError, fetch_pack, pack_urls
from yazses.system import installer_update


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def captured(monkeypatch):
    requests: list[urllib.request.Request] = []
    served: dict[str, bytes] = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            requests.append(req)
            return _Resp(served[req.full_url])

    monkeypatch.setattr(installer_update.urllib.request, "build_opener",
                        lambda *handlers: FakeOpener())
    return requests, served


def test_a_pack_fetch_makes_exactly_two_requests_with_the_asset_headers(tmp_path, captured):
    requests, served = captured
    pack = build_pack(tmp_path / "p.yazpack")
    index = pack.index()
    entry = index.packs[0]
    sums_url, pack_url = pack_urls(index, entry)
    served[sums_url] = f"{entry.sha256}  {entry.asset}\n".encode()
    served[pack_url] = pack.path.read_bytes()

    fetch_pack(index, entry, tmp_path / "dl")

    assert [r.full_url for r in requests] == [sums_url, pack_url]
    for req in requests:
        assert req.get_method() == "GET"
        assert req.data is None, "nothing is sent in a body"
        headers = {k.lower(): v for k, v in req.header_items()}
        assert headers == {"accept": "application/octet-stream", "user-agent": "yazses-updater"}
        assert "cookie" not in headers and "authorization" not in headers
        assert "api.github.com" not in req.full_url
        assert req.full_url.startswith(
            "https://github.com/MSKazemi/yazses/releases/download/v2.44.0/"
        )


def test_the_urls_come_from_the_running_versions_tag(tmp_path) -> None:
    pack = build_pack(tmp_path / "p.yazpack")
    index = pack.index()
    sums_url, pack_url = pack_urls(index, index.packs[0])
    assert sums_url == (
        "https://github.com/MSKazemi/yazses/releases/download/v2.44.0/SHA256SUMS.txt"
    )
    assert pack_url.endswith("/v2.44.0/YazSes-2.44.0-windows-x64-pack-parakeet.yazpack")
    assert installer_update.is_trusted_download_url(sums_url)
    assert installer_update.is_trusted_download_url(pack_url)


def test_a_checksums_mismatch_stops_after_one_request(tmp_path, captured) -> None:
    requests, served = captured
    pack = build_pack(tmp_path / "p.yazpack")
    index = pack.index()
    entry = index.packs[0]
    sums_url, _ = pack_urls(index, entry)
    served[sums_url] = f"{'f' * 64}  {entry.asset}\n".encode()
    with pytest.raises(PackFetchError):
        fetch_pack(index, entry, tmp_path / "dl")
    assert [r.full_url for r in requests] == [sums_url]


def test_an_offline_install_from_a_file_makes_no_request(tmp_path, captured) -> None:
    """ADR-028 question 5: `packs install --from <file>` trusts the embedded index alone.
    Through the same captured opener that sees both requests of a real fetch, a whole
    --from install (copy, hash, extract, match, place) builds **no** request at all: no
    SHA256SUMS.txt, no pack URL."""
    from tests.packs_fixtures import FakeRuntime, asset_name, base
    from yazses.packs.context import PackContext
    from yazses.packs.layout import PackLayout
    from yazses.packs.manage import install_from_file
    from yazses.packs.policy import Capability

    requests, _served = captured
    pack = build_pack(tmp_path / "usb" / asset_name("parakeet"))
    ctx = PackContext(
        runtime=FakeRuntime(), layout=PackLayout.under(tmp_path / "data"), frozen=True,
        capability=Capability(True), index=pack.index(), base=base(),
    )
    result = install_from_file(ctx, pack.path, probe=lambda name, staged: (True, ""))
    assert result.ok, result.message
    assert requests == [], [r.full_url for r in requests]
