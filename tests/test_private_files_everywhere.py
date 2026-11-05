"""The learning corpus, voiceprints, participants and few-shots are owner-only on POSIX.

``learning/crypto.py`` sets the data directory ``0700`` and the key ``0600``, but only when
the key is first loaded. The corpus database, the clip files, ``voiceprint.enc``, the
participant voiceprints and ``few_shots.toml`` were created with the process umask (0644
inside 0755 on a normal login), so the only thing between them and another local account
was a directory chmod that a user who never reached the key code path did not have.
Dirs are now ``0700``, files ``0600``, from creation, and a looser pre-existing one is
tightened on the next write. Windows uses ACLs, which none of this touches.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import numpy as np
import pytest

from yazses.learning.analysis import Proposal, apply_proposal, load_few_shots
from yazses.learning.crypto import Cipher
from yazses.learning.store import CorpusStore
from yazses.meeting.participants import load_participants
from yazses.voiceprint.embedding import Embedding
from yazses.voiceprint.store import load_voiceprint, save_voiceprint

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or os.name != "posix",
    reason="POSIX permission bits; Windows uses ACLs, which these writers do not set",
)


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.fixture(params=[0o022, 0o000], ids=["umask022", "umask000"])
def umask(request):
    old = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(old)


@pytest.fixture
def cipher() -> Cipher:
    return Cipher(bytes(range(32)))


def _emb() -> Embedding:
    return Embedding(vector=np.arange(8, dtype="float32"))


def _event(text: str = "synthetic words") -> dict:
    return {"ts": 1.0, "raw_text": text, "final_text": text, "injected": True}


def _audio() -> np.ndarray:
    return (np.sin(np.linspace(0, 50, 1600)) * 0.5).astype("float32")


def _proposal(*examples: str) -> Proposal:
    return Proposal(kind="few_shots", title="t", detail="d", evidence=1,
                    target="few_shots", examples=list(examples))


def test_voiceprint_is_owner_only_and_round_trips(tmp_path, cipher, umask):
    p = tmp_path / "data" / "voiceprint.enc"
    save_voiceprint(_emb(), p, cipher)
    assert _mode(p) == 0o600
    assert _mode(p.parent) == 0o700
    loaded = load_voiceprint(p, cipher)
    assert loaded is not None
    assert np.array_equal(loaded.vector, _emb().vector)


def test_participant_voiceprints_are_owner_only(tmp_path, cipher, umask):
    d = tmp_path / "data" / "participants"
    save_voiceprint(_emb(), d / "Alice.vp", cipher)
    save_voiceprint(_emb(), d / "Bob.vp", cipher)
    assert _mode(d) == 0o700
    assert all(_mode(f) == 0o600 for f in d.iterdir())

    class Cfg:
        participants_dir = str(d)

    found = load_participants(Cfg(), cipher)
    assert sorted(found) == ["Alice", "Bob"]


def test_few_shots_is_owner_only_and_content_unchanged(tmp_path, umask):
    p = tmp_path / "data" / "few_shots.toml"
    prop = _proposal("open the door -> open", "héllo -> x")
    apply_proposal(prop, tmp_path / "config.toml", p)
    apply_proposal(prop, tmp_path / "config.toml", p)
    assert _mode(p) == 0o600
    assert _mode(p.parent) == 0o700
    assert p.read_text(encoding="utf-8").startswith("# YazSes SLM few-shot examples")
    assert load_few_shots(p) == ["open the door -> open", "héllo -> x"] * 2


def test_corpus_db_clips_and_dirs_are_owner_only(tmp_path, cipher, umask):
    data = tmp_path / "data"
    store = CorpusStore(data, cipher)
    try:
        assert _mode(data / "corpus.db") == 0o600  # before any write
        eid = store.add_event(_event(), audio=_audio())
        store.add_event(_event("second"))
        store.mark_wrong(eid, "corrected")
    finally:
        store.close()
    assert _mode(data) == 0o700
    assert _mode(data / "clips") == 0o700
    assert _mode(data / "corpus.db") == 0o600
    clips = list((data / "clips").glob("*.wav.enc"))
    assert clips and all(_mode(c) == 0o600 for c in clips)
    for side in data.glob("corpus.db-*"):  # SQLite journal/WAL, if present
        assert _mode(side) & 0o077 == 0, side.name


def test_corpus_round_trips_through_the_real_reader(tmp_path, cipher, umask):
    data = tmp_path / "data"
    store = CorpusStore(data, cipher)
    audio = _audio()
    eid = store.add_event(_event("round trip"), audio=audio)
    store.close()
    again = CorpusStore(data, cipher)
    try:
        rec = [r for r in again.events() if r.id == eid][0]
        assert rec.raw_text == "round trip"
        loaded = again.load_audio(eid)
        assert loaded is not None and loaded[0].size == audio.size
    finally:
        again.close()


def test_preexisting_loose_files_are_tightened_on_next_write(tmp_path, cipher, umask):
    data = tmp_path / "data"
    store = CorpusStore(data, cipher)
    eid = store.add_event(_event(), audio=_audio())
    store.close()
    clip = data / "clips" / f"{eid}.wav.enc"
    vp = data / "voiceprint.enc"
    fs = data / "few_shots.toml"
    save_voiceprint(_emb(), vp, cipher)
    fs.write_text("# old\nexample\n", encoding="utf-8")
    for d in (data, data / "clips"):
        os.chmod(d, 0o755)
    for f in (data / "corpus.db", clip, vp, fs):
        os.chmod(f, 0o644)

    store = CorpusStore(data, cipher)  # reopening tightens the db and both dirs
    new_id = store.add_event(_event("two"), audio=_audio())
    store.close()
    assert _mode(data) == 0o700 and _mode(data / "clips") == 0o700
    assert _mode(data / "corpus.db") == 0o600
    assert _mode(data / "clips" / f"{new_id}.wav.enc") == 0o600

    save_voiceprint(_emb(), vp, cipher)
    assert _mode(vp) == 0o600
    apply_proposal(_proposal("new"), tmp_path / "c.toml", fs)
    assert _mode(fs) == 0o600
    assert load_few_shots(fs) == ["example", "new"]


def test_never_widens_a_stricter_file(tmp_path, cipher, umask):
    vp = tmp_path / "voiceprint.enc"
    vp.write_bytes(b"x")
    os.chmod(vp, 0o200)  # write-only for the owner, stricter than 0600
    save_voiceprint(_emb(), vp, cipher)
    assert _mode(vp) == 0o200


def test_chmod_failure_does_not_lose_the_data(tmp_path, cipher, monkeypatch):
    def refuse(*_a, **_k):
        raise OSError("operation not supported")

    monkeypatch.setattr(os, "chmod", refuse)
    vp = tmp_path / "voiceprint.enc"
    save_voiceprint(_emb(), vp, cipher)
    loaded = load_voiceprint(vp, cipher)
    assert loaded is not None and np.array_equal(loaded.vector, _emb().vector)
    store = CorpusStore(tmp_path / "data", cipher)
    eid = store.add_event(_event("kept"), audio=_audio())
    assert store.load_audio(eid) is not None
    store.close()
    fs = tmp_path / "data" / "few_shots.toml"
    apply_proposal(_proposal("kept"), tmp_path / "c.toml", fs)
    assert load_few_shots(fs) == ["kept"]


def test_new_files_are_never_world_readable_even_if_chmod_fails(tmp_path, cipher, monkeypatch):
    def refuse(*_a, **_k):
        raise OSError("no")

    old = os.umask(0o000)
    try:
        monkeypatch.setattr(os, "chmod", refuse)
        vp = tmp_path / "d" / "voiceprint.enc"
        save_voiceprint(_emb(), vp, cipher)
        assert _mode(vp) == 0o600
        store = CorpusStore(tmp_path / "data", cipher)
        eid = store.add_event(_event(), audio=_audio())
        store.close()
        assert _mode(tmp_path / "data" / "corpus.db") == 0o600
        assert _mode(tmp_path / "data" / "clips" / f"{eid}.wav.enc") == 0o600
    finally:
        os.umask(old)
