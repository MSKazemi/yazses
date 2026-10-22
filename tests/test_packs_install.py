"""ADR-028 §6: the install transaction, with fakes and no network.

A failure injected at each step must leave no staging tree, no download (complete or
``.part``) and no config write; the single-flight lock must hold; cancel must leave no
trace. The extractor is the real one, run on real ZIPs built in ``tmp_path``.
"""
from __future__ import annotations

import io
import shutil
import urllib.error
import zipfile
from pathlib import Path

import pytest

from tests.packs_fixtures import OTHER_BUILD_ID, base, build_pack
from yazses.packs.fetch import PackCancelled, PackFetchError, fetch_pack
from yazses.packs.install import ExtractError, extract_archive, install_pack, quarantine_tree
from yazses.packs.layout import COMPLETE, PackLayout
from yazses.packs.state import empty_state


class World:
    def __init__(self, tmp_path: Path, **pack_kwargs) -> None:
        self.tmp = tmp_path
        self.pack = build_pack(tmp_path / "src" / "p.yazpack", **pack_kwargs)
        self.index = self.pack.index()
        self.entry = self.index.packs[0]
        self.layout = PackLayout.under(tmp_path / "data")
        self.docs: list[dict] = []
        self.probed: list[tuple[str, Path]] = []

    def fetch(self, index, entry, dest, *, progress=None, cancel=None):
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / entry.asset
        shutil.copyfile(self.pack.path, out)
        return out

    def probe_ok(self, name, staged):
        self.probed.append((name, staged))
        assert (staged / "pack.json").is_file(), "the probe must see the staged tree"
        return True, ""

    def run(self, **kw):
        args = dict(doc=empty_state(), probe=self.probe_ok, fetch=self.fetch,
                    write_doc=self.docs.append, free_bytes=lambda p: 10**12)
        args.update(kw)
        return install_pack(self.index, self.entry, base(), self.layout, **args)

    def leftovers(self) -> list[str]:
        out = []
        for d in (self.layout.staging, self.layout.downloads):
            if d.is_dir():
                out += [p.name for p in d.iterdir()]
        return out


def test_a_successful_install_places_the_tree_and_writes_complete_last(tmp_path) -> None:
    w = World(tmp_path)
    result = w.run()
    assert result.ok, result.message
    tree = w.layout.pack_dir("b-" + "a" * 12, "parakeet")
    assert (tree / "site" / "fakepkg_parakeet" / "core.py").is_file()
    assert (tree / COMPLETE).read_text(encoding="utf-8") == f"sha256 {w.entry.sha256}\n"
    assert w.leftovers() == [], "the archive and staging tree are deleted"
    assert not w.layout.lock("parakeet").exists()
    assert w.probed and w.probed[0][0] == "parakeet"
    assert w.docs[-1]["builds"]["b-" + "a" * 12]["packs"]["parakeet"]["sha256"] == w.entry.sha256


def _assert_nothing_installed(w: World, result, step: str) -> None:
    assert not result.ok
    assert result.step == step, (result.step, result.message)
    assert w.leftovers() == [], f"left behind: {w.leftovers()}"
    assert not w.layout.pack_dir("b-" + "a" * 12, "parakeet").exists()
    assert not w.layout.lock("parakeet").exists()
    assert result.message


def test_a_held_lock_refuses_a_second_install(tmp_path) -> None:
    w = World(tmp_path)
    w.layout.root.mkdir(parents=True)
    w.layout.lock("parakeet").write_text("1 0\n", encoding="utf-8")
    result = w.run(clock=lambda: w.layout.lock("parakeet").stat().st_mtime + 5)
    assert not result.ok and result.step == "lock"
    assert "already running" in result.message
    assert w.layout.lock("parakeet").exists(), "someone else's lock is not ours to delete"


def test_a_stale_lock_is_taken_over(tmp_path) -> None:
    w = World(tmp_path)
    w.layout.root.mkdir(parents=True)
    w.layout.lock("parakeet").write_text("1 0\n", encoding="utf-8")
    old = w.layout.lock("parakeet").stat().st_mtime
    assert w.run(clock=lambda: old + 3 * 3600).ok


def test_a_full_disk_refuses_before_downloading(tmp_path) -> None:
    w = World(tmp_path)
    fetched = []
    result = w.run(free_bytes=lambda p: 10, fetch=lambda *a, **k: fetched.append(1))
    _assert_nothing_installed(w, result, "disk")
    assert not fetched and "free" in result.message


def test_a_failed_download_installs_nothing(tmp_path) -> None:
    w = World(tmp_path)

    def offline(*a, **k):
        raise PackFetchError("offline", "Couldn't reach github.com … Nothing was changed.")

    result = w.run(fetch=offline)
    _assert_nothing_installed(w, result, "download")
    assert "github.com" in result.message
    assert w.docs[-1]["last_results"]["parakeet"]["ok"] is False


def test_a_cancelled_download_leaves_no_trace(tmp_path) -> None:
    w = World(tmp_path)

    def cancelled(index, entry, dest, **k):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / (entry.asset + ".part")).write_bytes(b"half")
        raise PackCancelled()

    result = w.run(fetch=cancelled)
    _assert_nothing_installed(w, result, "cancelled")
    assert "Cancelled" in result.message


def test_ctrl_c_during_the_download_leaves_no_trace(tmp_path) -> None:
    w = World(tmp_path)

    def interrupted(index, entry, dest, **k):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / (entry.asset + ".part")).write_bytes(b"half")
        raise KeyboardInterrupt

    _assert_nothing_installed(w, w.run(fetch=interrupted), "cancelled")


def test_a_cancel_between_steps_stops_before_the_probe(tmp_path) -> None:
    w = World(tmp_path)
    calls = iter([False, True])
    result = w.run(cancel=lambda: next(calls, True))
    _assert_nothing_installed(w, result, "cancelled")
    assert not w.probed


def test_a_corrupt_archive_is_refused_at_extract(tmp_path) -> None:
    w = World(tmp_path)

    def corrupt(index, entry, dest, **k):
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / entry.asset
        out.write_bytes(b"PK\x03\x04 not really a zip")
        return out

    result = w.run(fetch=corrupt)
    _assert_nothing_installed(w, result, "extract")
    assert "refused" in result.message


def test_a_pack_for_another_build_is_refused_at_match(tmp_path) -> None:
    w = World(tmp_path, manifest_over={"base_build_id": OTHER_BUILD_ID})
    result = w.run()
    _assert_nothing_installed(w, result, "match")
    assert "does not belong" in result.message
    assert not w.probed, "a pack for another build is never even test-imported"


def test_a_failed_probe_installs_nothing_and_names_the_reason(tmp_path) -> None:
    w = World(tmp_path)
    result = w.run(probe=lambda n, s: (False, "needs the standard-library module 'x' [stdlib-gap]"))
    _assert_nothing_installed(w, result, "probe")
    assert "stdlib-gap" in result.message


def test_a_failed_move_into_place_installs_nothing(tmp_path) -> None:
    w = World(tmp_path)

    def broken_replace(src, dst):
        raise OSError("disk went away")

    result = w.run(replace=broken_replace)
    _assert_nothing_installed(w, result, "place")
    assert "unexpected error" in result.message


def test_a_reinstall_replaces_the_tree_and_restores_it_on_failure(tmp_path) -> None:
    w = World(tmp_path)
    assert w.run().ok
    tree = w.layout.pack_dir("b-" + "a" * 12, "parakeet")
    marker = tree / "site" / "fakepkg_parakeet" / "core.py"
    marker.write_text("old", encoding="utf-8")
    calls = []

    def fail_second(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError("no")
        import os
        os.replace(src, dst)

    assert not w.run(replace=fail_second).ok
    assert marker.read_text(encoding="utf-8") == "old", "the previous tree is put back"
    assert w.run().ok
    assert marker.read_text(encoding="utf-8") != "old"


def test_a_too_large_pack_is_refused_before_anything(tmp_path) -> None:
    from dataclasses import replace as dc_replace

    from yazses.packs.policy import PACK_MAX_BYTES

    w = World(tmp_path)
    w.entry = dc_replace(w.entry, size=PACK_MAX_BYTES + 1)
    result = w.run()
    assert not result.ok and result.step == "check"
    assert not w.layout.root.exists()


# ---- the real extractor ----------------------------------------------------------------

def test_extract_rejects_a_member_the_record_does_not_list(tmp_path) -> None:
    pack = build_pack(tmp_path / "p.yazpack", extra_members={"site/sneaky.py": b"x"})
    with pytest.raises(ExtractError):
        extract_archive(pack.path, tmp_path / "out")


def test_extract_rejects_a_record_hash_that_does_not_match(tmp_path) -> None:
    pack = build_pack(tmp_path / "p.yazpack")
    import json
    rec = json.loads(zipfile.ZipFile(pack.path).read("RECORD.json"))["files"]
    rec[0]["sha256"] = "0" * 64
    bad = build_pack(tmp_path / "q.yazpack", record_over=rec)
    with pytest.raises(ExtractError, match="RECORD"):
        extract_archive(bad.path, tmp_path / "out")


def test_extract_rejects_traversal_in_a_real_zip(tmp_path) -> None:
    pack = build_pack(tmp_path / "p.yazpack", extra_members={"../evil.py": b"x"})
    with pytest.raises(ExtractError, match="unsafe"):
        extract_archive(pack.path, tmp_path / "out")
    assert not (tmp_path / "evil.py").exists()
    assert not (tmp_path / "out").exists(), "nothing is written before the checks pass"


def test_quarantine_moves_the_tree_beside_a_reason(tmp_path) -> None:
    lay = PackLayout.under(tmp_path)
    tree = lay.pack_dir("b-" + "a" * 12, "parakeet")
    tree.mkdir(parents=True)
    dest = quarantine_tree(lay, tree, "site/x.dll is missing", clock=lambda: 0.0)
    assert dest is not None and dest.name == "parakeet-19700101T000000Z"
    assert (dest / "reason.txt").read_text(encoding="utf-8").startswith("site/x.dll")
    assert not tree.exists()


# ---- the real fetch, through ADR-027's download_verified ------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(served: dict[str, bytes], seen: list[str]):
    def open_url(url, timeout):
        seen.append(url)
        if url not in served:
            raise urllib.error.URLError("no route to host")
        return _Resp(served[url])
    return open_url


def _sums(name: str, sha: str) -> bytes:
    return f"{sha}  {name}\n{'e' * 64}  YazSes-2.44.0-windows-x64.exe\n".encode()


def _served(w: World, *, pack_bytes: bytes | None = None, sha: str | None = None):
    from yazses.packs.fetch import pack_urls

    sums_url, pack_url = pack_urls(w.index, w.entry)
    return {
        sums_url: _sums(w.entry.asset, sha or w.entry.sha256),
        pack_url: pack_bytes if pack_bytes is not None else w.pack.path.read_bytes(),
    }


def test_fetch_downloads_and_verifies_against_the_embedded_hash(tmp_path) -> None:
    w = World(tmp_path)
    seen: list[str] = []
    path = fetch_pack(w.index, w.entry, tmp_path / "dl", open_url=_opener(_served(w), seen))
    assert path.read_bytes() == w.pack.path.read_bytes()
    assert seen == [
        "https://github.com/MSKazemi/yazses/releases/download/v2.44.0/SHA256SUMS.txt",
        f"https://github.com/MSKazemi/yazses/releases/download/v2.44.0/{w.entry.asset}",
    ]


def test_one_flipped_byte_is_a_checksum_failure_and_is_deleted(tmp_path) -> None:
    w = World(tmp_path)
    data = bytearray(w.pack.path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    with pytest.raises(PackFetchError) as err:
        fetch_pack(w.index, w.entry, tmp_path / "dl",
                   open_url=_opener(_served(w, pack_bytes=bytes(data)), []))
    assert err.value.kind == "checksum"
    assert "built into this copy" in str(err.value)
    assert list((tmp_path / "dl").iterdir()) == []


def test_a_wrong_sha256sums_line_refuses_before_downloading(tmp_path) -> None:
    w = World(tmp_path)
    seen: list[str] = []
    with pytest.raises(PackFetchError) as err:
        fetch_pack(w.index, w.entry, tmp_path / "dl",
                   open_url=_opener(_served(w, sha="f" * 64), seen))
    assert err.value.kind == "release-changed"
    assert len(seen) == 1, "the pack itself is never requested"


def test_a_truncated_download_is_refused(tmp_path) -> None:
    w = World(tmp_path)
    short = w.pack.path.read_bytes()[:-10]
    with pytest.raises(PackFetchError) as err:
        fetch_pack(w.index, w.entry, tmp_path / "dl",
                   open_url=_opener(_served(w, pack_bytes=short), []))
    assert err.value.kind == "refused" and "stopped early" in str(err.value)
    assert list((tmp_path / "dl").iterdir()) == []


def test_offline_says_so_and_changes_nothing(tmp_path) -> None:
    w = World(tmp_path)
    with pytest.raises(PackFetchError) as err:
        fetch_pack(w.index, w.entry, tmp_path / "dl", open_url=_opener({}, []))
    assert err.value.kind == "offline"
    assert "Couldn't reach github.com" in str(err.value)
    assert "Nothing was changed" in str(err.value)


def test_cancel_during_the_download_deletes_the_part_file(tmp_path) -> None:
    w = World(tmp_path)
    big = build_pack(tmp_path / "big.yazpack",
                     payload={"site/blob.bin": bytes(range(256)) * 4000})
    index = big.index()
    entry = index.packs[0]
    from yazses.packs.fetch import pack_urls

    sums_url, pack_url = pack_urls(index, entry)
    served = {sums_url: _sums(entry.asset, entry.sha256), pack_url: big.path.read_bytes()}
    with pytest.raises(PackCancelled):
        fetch_pack(index, entry, tmp_path / "dl", open_url=_opener(served, []),
                   cancel=lambda: True if (tmp_path / "dl").exists() else False)
    assert list((tmp_path / "dl").iterdir()) == []
    del w
