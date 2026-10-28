"""scripts/hf_preflight.py: the offline gate in front of every Hugging Face upload.

The validator must reject every class of thing that must never reach the Hub (private
trees, secrets, audio, PDFs, broken links, bad cards, an unapproved destination), must
accept a clean tree, and must be *unable* to publish. Everything runs offline against
fixtures in tmp_path, plus one test against the real tree and manifest.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
def _load(name: str):
    """Load scripts/<name>.py by path, as tests/test_ci_telemetry.py does: the FreeBSD
    leg and the test-dependency guard treat a `sys.path` name import as a missing package."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


pf = _load("hf_preflight")

SPACE_CARD = "---\ntitle: Demo\nsdk: static\n---\n\n# Demo\n"
DATASET_CARD = (
    "---\nlicense: cc-by-4.0\nconfigs:\n  - config_name: default\n    data_files: data/*.csv\n---\n\n# D\n"
)
INDEX = '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head>' \
        '<body><a href="#top">t</a><h1 id="top">x</h1><img src="assets/a.svg"></body></html>'


def _dest(**over) -> dict:
    base = {
        "repo_id": "acme/showcase",
        "repo_type": "space",
        "url": None,
        "source_dir": "huggingface/showcase",
        "files": ["README.md", "index.html", "styles.css", "assets/"],
        "status": "planned",
        "owner_approved": False,
        "publisher": "acme-showcase",
        "delete_remote_files": False,
        "max_file_bytes": 100_000,
        "required_card_keys": ["title", "sdk"],
    }
    base.update(over)
    return base


def _manifest(**dests: dict) -> dict:
    dests = dests or {"showcase": _dest()}
    return {
        "schema_version": 1,
        "oidc_publisher": {
            "provider": "github-actions", "repository": "acme/repo", "branch": "main",
            "workflow": "huggingface-publish.yml", "environment": "huggingface-publish",
        },
        "destinations": dests,
        "collection": {
            "owner": "acme", "owner_approved": False, "title": "T", "description": "D",
            "items": [{
                "type": "paper", "id": "1234.56789", "status": "planned", "url": None,
                "destination": None, "note": "n", "evidence": "e",
            }],
        },
    }


def _write_tree(root: Path, files: dict[str, str | bytes], base: str = "huggingface/showcase") -> None:
    for rel, content in files.items():
        path = root / base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")


def _good_files() -> dict[str, str | bytes]:
    return {
        "README.md": SPACE_CARD,
        "index.html": INDEX,
        "styles.css": "body { background: url(assets/a.svg); }",
        "assets/a.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
    }


def _run(tmp_path: Path, manifest: dict, files: dict[str, str | bytes] | None = None,
         *argv: str, base: str = "huggingface/showcase", capsys=None):
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    _write_tree(root, _good_files() if files is None else files, base)
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    code = pf.main(["--manifest", str(mpath), "--root", str(root), "--skip-export-check", *argv])
    err = capsys.readouterr().err if capsys else ""
    return code, err


def _failures(err: str) -> str:
    return "\n".join(line for line in err.splitlines() if line.startswith("FAIL"))


# --- the real manifest and tree -----------------------------------------------------


def test_the_real_manifest_is_valid() -> None:
    manifest = pf.load_manifest(pf.DEFAULT_MANIFEST)
    report = pf.Report()
    pf.validate_schema(manifest, report)
    assert not report.errors, report.errors


def test_every_real_source_path_exists_and_passes_preflight(capsys) -> None:
    """The whole real tree, offline. The benchmark export check is covered separately."""
    code = pf.main(["--skip-export-check"])
    assert code == 0, capsys.readouterr().err


def test_an_approved_destination_is_live_and_has_a_url() -> None:
    """Approval is a deliberate, reviewed edit, and it only makes sense for a page that
    exists: an approved destination must be live with a recorded URL, and the collection
    cannot be approved while any destination it lists is still planned."""
    manifest = pf.load_manifest(pf.DEFAULT_MANIFEST)
    for name, dest in manifest["destinations"].items():
        if dest["owner_approved"] is True:
            assert dest["status"] == "live", name
            assert dest["url"], name
    if manifest["collection"]["owner_approved"] is True:
        for item in manifest["collection"]["items"]:
            if item.get("destination"):
                assert manifest["destinations"][item["destination"]]["status"] == "live", item["id"]


def test_planned_items_and_destinations_carry_no_url() -> None:
    manifest = pf.load_manifest(pf.DEFAULT_MANIFEST)
    for name, dest in manifest["destinations"].items():
        assert (dest["status"] == "planned") == (dest["url"] is None), name
    for item in manifest["collection"]["items"]:
        assert (item["status"] == "planned") == (item["url"] is None), item["id"]


def test_a_clean_fixture_passes(tmp_path, capsys) -> None:
    code, err = _run(tmp_path, _manifest(), capsys=capsys)
    assert code == 0, err


# --- schema ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        (lambda m: m["destinations"]["showcase"].update(delete_remote_files=True), "delete_remote_files"),
        (lambda m: m["destinations"]["showcase"].update(status="maybe"), "status must be"),
        (lambda m: m["destinations"]["showcase"].update(owner_approved="yes"), "owner_approved"),
        (lambda m: m["destinations"]["showcase"].update(repo_id="nonsense"), "repo_id"),
        (lambda m: m["destinations"]["showcase"].update(bogus=1), "unknown keys"),
        (lambda m: m["destinations"]["showcase"].update(url="https://huggingface.co/spaces/acme/showcase"), "planned destination must have url null"),
        (lambda m: m["destinations"]["showcase"].update(source_dir="paper/benchmark"), "must be a subdirectory of huggingface"),
        (lambda m: m["destinations"]["showcase"].update(source_dir="huggingface/profile"), "never uploaded"),
        (lambda m: m["destinations"]["showcase"].update(source_dir="huggingface/design"), "forbidden segment"),
        (lambda m: m["destinations"]["showcase"].update(source_dir="huggingface/../x"), "'..'"),
        (lambda m: m["destinations"]["showcase"].update(files=["../secret.txt"]), "'..'"),
        (lambda m: m["destinations"]["showcase"].update(files=["/etc/passwd"]), "relative POSIX"),
        (lambda m: m["destinations"]["showcase"].update(max_file_bytes=10**9), "max_file_bytes"),
        (lambda m: m["destinations"]["showcase"].update(export_check=["scripts/x.py", "--upload"]), "export_check"),
        (lambda m: m["destinations"]["showcase"].update(audio_fixtures=[{"path": "a.wav", "synthetic": False}]), "synthetic"),
        (lambda m: m["destinations"]["showcase"].update(card_only=True), "card_only"),
        (lambda m: m.update(surprise=1), "unknown top-level key"),
        (lambda m: m["collection"]["items"][0].update(note="x" * 501), "501 characters"),
        (lambda m: m["collection"].update(description="d" * 151), "151 characters"),
        (lambda m: m["collection"]["items"][0].update(url="https://huggingface.co/papers/1234.56789"), "planned item must have url null"),
        (lambda m: m["collection"]["items"].append(copy.deepcopy(m["collection"]["items"][0])), "duplicate item"),
        (lambda m: m["collection"]["items"][0].update(destination="nope"), "not in the manifest"),
    ],
)
def test_schema_rejects(mutation, needle, tmp_path, capsys) -> None:
    manifest = _manifest()
    mutation(manifest)
    code, err = _run(tmp_path, manifest, capsys=capsys)
    assert code == 1
    assert needle in _failures(err), err


def test_a_live_item_needs_the_exact_url_and_evidence() -> None:
    manifest = _manifest()
    manifest["collection"]["items"][0].update(status="live", url="https://example.com/x", evidence="")
    report = pf.Report()
    pf.validate_schema(manifest, report)
    text = "\n".join(report.errors)
    assert "live item's url must be" in text
    assert "needs evidence" in text


def test_a_live_item_cannot_point_at_a_planned_destination() -> None:
    dest = _dest()
    manifest = _manifest(showcase=dest)
    manifest["collection"]["items"][0].update(
        type="space", id="acme/showcase", status="live",
        url="https://huggingface.co/spaces/acme/showcase", destination="showcase", evidence="e",
    )
    report = pf.Report()
    pf.validate_schema(manifest, report)
    assert any("destination showcase is planned" in e for e in report.errors), report.errors


def test_duplicate_publishers_and_overlapping_dirs_are_rejected() -> None:
    manifest = _manifest(
        a=_dest(repo_id="acme/a", source_dir="huggingface/x"),
        b=_dest(repo_id="acme/b", source_dir="huggingface/x/y", publisher="acme-showcase"),
    )
    report = pf.Report()
    pf.validate_schema(manifest, report)
    text = "\n".join(report.errors)
    assert "is shared with" in text
    assert "overlap" in text


def test_a_duplicate_json_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "m.json"
    path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
    with pytest.raises(pf.ManifestError, match="duplicate JSON key"):
        pf.load_manifest(path)


def test_an_unreadable_manifest_exits_2(tmp_path, capsys) -> None:
    assert pf.main(["--manifest", str(tmp_path / "missing.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


# --- forbidden classes -------------------------------------------------------------


def _with(extra: dict[str, str | bytes], allow: list[str]) -> tuple[dict, dict]:
    files = {**_good_files(), **extra}
    return _manifest(showcase=_dest(files=["README.md", "index.html", "styles.css", "assets/", *allow])), files


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("paper/notes.md", "forbidden path segment"),
        ("design/adr.md", "forbidden path segment"),
        ("strategy" + "/plan.md", "forbidden path segment"),
        (".claude" + "/memory.md", "forbidden path segment"),
        (".git/config", "forbidden path segment"),
        ("sub/.env", "dotfiles"),
        (".env.local", "dotfiles"),
        ("manuscript.pdf", "never uploaded"),
        ("voice.wav", "audio/video is never uploaded"),
        ("voice.FLAC", "audio/video is never uploaded"),
        ("clip.mp3", "audio/video is never uploaded"),
        ("clip.m4a", "audio/video is never uploaded"),
        ("clip.ogg", "audio/video is never uploaded"),
        ("demo.mp4", "audio/video is never uploaded"),
        ("server.pem", "never uploaded"),
        ("id.key", "never uploaded"),
        ("data.sqlite", "never uploaded"),
        ("tool.exe", "not in the upload allowlist"),
        ("archive.zip", "not in the upload allowlist"),
    ],
)
def test_forbidden_paths_are_rejected(path, needle, tmp_path, capsys) -> None:
    manifest, files = _with({path: "x"}, [path])
    code, err = _run(tmp_path, manifest, files, capsys=capsys)
    assert code == 1
    assert needle in _failures(err), err


def test_the_only_suffixless_file_allowed_is_sha256sums(tmp_path, capsys) -> None:
    # The benchmark card tells users to run `sha256sum -c SHA256SUMS`, so that exact name
    # must ship. The exception is one exact basename, not "files without a suffix".
    assert pf.ALLOWED_BASENAMES == frozenset({"SHA256SUMS"})
    manifest, files = _with({"SHA256SUMS": "abc  README.md\n"}, ["SHA256SUMS"])
    code, err = _run(tmp_path / "ok", manifest, files, capsys=capsys)
    assert code == 0, err
    for name in ("Makefile", "sha256sums", "SHA256SUMS.bak", "run"):
        manifest, files = _with({name: "x"}, [name])
        code, err = _run(tmp_path / f"no-{name}", manifest, files, capsys=capsys)
        assert code == 1, name
        assert "not in the upload allowlist" in _failures(err), err


def test_a_tiny_synthetic_audio_fixture_must_be_named_explicitly(tmp_path, capsys) -> None:
    manifest, files = _with({"assets/tone.wav": b"RIFF" + b"\0" * 100}, ["assets/tone.wav"])
    code, _ = _run(tmp_path / "a", manifest, files, capsys=capsys)
    assert code == 1  # allowlisted but not declared a fixture
    manifest["destinations"]["showcase"]["audio_fixtures"] = [
        {"path": "assets/tone.wav", "synthetic": True}
    ]
    code, err = _run(tmp_path / "b", manifest, files, capsys=capsys)
    assert code == 0, err


def test_an_audio_fixture_must_be_tiny(tmp_path, capsys) -> None:
    manifest, files = _with({"assets/tone.wav": b"\0" * (pf.MAX_AUDIO_FIXTURE_BYTES + 1)}, ["assets/tone.wav"])
    manifest["destinations"]["showcase"]["audio_fixtures"] = [{"path": "assets/tone.wav", "synthetic": True}]
    code, err = _run(tmp_path, manifest, files, capsys=capsys)
    assert code == 1
    assert "audio fixture is" in _failures(err)


def test_a_file_over_the_limit_is_rejected(tmp_path, capsys) -> None:
    manifest, files = _with({"big.txt": "x" * 100_001}, ["big.txt"])
    code, err = _run(tmp_path, manifest, files, capsys=capsys)
    assert code == 1
    assert "exceeds the 100000 byte limit" in _failures(err)


def test_a_symlink_is_rejected(tmp_path, capsys) -> None:
    root = tmp_path / "repo"
    manifest, files = _with({}, ["link.txt"])
    _write_tree(root, files)
    (root / "outside.txt").write_text("secret", encoding="utf-8")
    try:
        (root / "huggingface/showcase/link.txt").symlink_to(root / "outside.txt")
    except OSError:
        pytest.skip("symlinks unavailable")
    code, err = _run(tmp_path, manifest, files, capsys=capsys)
    assert code == 1
    assert "symlink" in _failures(err)


def test_an_allowlist_entry_matching_nothing_is_rejected(tmp_path, capsys) -> None:
    manifest, files = _with({}, ["data/*.csv", "missing.html"])
    code, err = _run(tmp_path, manifest, files, capsys=capsys)
    assert code == 1
    text = _failures(err)
    assert "matched no files" in text
    assert "missing.html does not exist" in text


def test_unlisted_files_are_only_a_warning_and_are_not_staged(tmp_path, capsys) -> None:
    files = {**_good_files(), "NOTES.md": "internal"}
    stage_dir = tmp_path / "stage"
    code, err = _run(tmp_path, _manifest(), files, "--stage-dir", str(stage_dir), capsys=capsys)
    assert code == 0, err
    assert "NOTES.md is not allowlisted and will NOT be uploaded" in err
    staged = sorted(p.relative_to(stage_dir / "showcase").as_posix() for p in (stage_dir / "showcase").rglob("*") if p.is_file())
    assert staged == ["README.md", "assets/a.svg", "index.html", "styles.css"]


def test_staging_inside_the_upload_tree_is_refused(tmp_path) -> None:
    root = tmp_path / "repo"
    _write_tree(root, _good_files())
    with pytest.raises(pf.SelectionError, match="outside"):
        pf.stage(root, root / "huggingface" / "stage", "showcase", _dest(), ["README.md"])


# --- secrets -----------------------------------------------------------------------

# Built from parts so this test file itself contains no token-shaped string.
_FAKE_SECRETS = {
    "hf token": "token = '" + "hf_" + "a" * 34 + "'",
    "github token": "x " + "ghp_" + "b" * 36,
    "github pat": "x " + "github_pat_" + "c" * 30,
    "sk key": "key " + "sk-" + "d" * 30,
    "aws": "id " + "AKIA" + "E" * 16,
    "private key": "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
    "bearer": "Authorization: Bearer " + "e" * 30,
    "assignment": "HF_TOKEN=" + "f" * 30,
    "home path": "cp /home/" + "jdoe" + "/models/x .",
    "mac path": "/Users/" + "jdoe" + "/Library/x",
    "windows path": "C:\\Users\\" + "jdoe" + "\\Desktop\\x",
    "work mailbox": "write to someone@" + "e4company.com",
}


@pytest.mark.parametrize("label", sorted(_FAKE_SECRETS))
def test_secret_shaped_content_is_rejected_without_echoing_it(label, tmp_path, capsys) -> None:
    secret = _FAKE_SECRETS[label]
    files = {**_good_files(), "README.md": SPACE_CARD + "\n" + secret + "\n"}
    code, err = _run(tmp_path, _manifest(), files, capsys=capsys)
    assert code == 1
    assert "README.md:" in _failures(err), err
    assert "value not shown" in err
    distinctive = {"home path": "jdoe", "mac path": "jdoe", "windows path": "jdoe",
                   "work mailbox": "e4company"}.get(label, secret.split()[-1].strip("'")[-12:])
    assert distinctive not in err, "the matched value must never be printed"


def test_placeholder_home_paths_and_the_container_user_are_not_flagged(tmp_path, capsys) -> None:
    text = "mount /home/user/models and /home/yazses/.cache and ~/.cache/huggingface\n"
    files = {**_good_files(), "README.md": SPACE_CARD + text}
    code, err = _run(tmp_path, _manifest(), files, capsys=capsys)
    assert code == 0, err


# --- cards -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("card", "needle"),
    [
        ("# no front matter\n", "no YAML front matter"),
        ("---\ntitle: [unclosed\n---\n", "not valid YAML"),
        ("---\ntitle: a\ntitle: b\nsdk: static\n---\n", "duplicate key"),
        ("---\n- a\n- b\n---\n", "must be a YAML mapping"),
        ("---\ntitle: Demo\n---\n", "missing required key 'sdk'"),
        ("---\nsdk: static\n---\n", "missing required key 'title'"),
        ("---\ntitle: Demo\nsdk: flask\n---\n", "must be one of"),
        ("---\ntitle: Demo\nsdk: gradio\n---\n", "needs 'app_file'"),
        ("---\ntitle: Demo\nsdk: gradio\napp_file: app.py\n---\n", "not in the upload set"),
    ],
)
def test_bad_space_cards_are_rejected(card, needle, tmp_path, capsys) -> None:
    files = {**_good_files(), "README.md": card}
    code, err = _run(tmp_path, _manifest(), files, capsys=capsys)
    assert code == 1
    assert needle in _failures(err), err


def test_a_static_space_needs_its_page(tmp_path, capsys) -> None:
    manifest = _manifest(showcase=_dest(files=["README.md", "styles.css", "assets/"]))
    code, err = _run(tmp_path, manifest, capsys=capsys)
    assert code == 1
    assert "static Space needs 'index.html'" in _failures(err)


def test_an_org_card_needs_only_its_readme(tmp_path, capsys) -> None:
    manifest = _manifest(card=_dest(repo_id="acme/README", files=["README.md"],
                                    card_only=True, source_dir="huggingface/organization"))
    code, err = _run(tmp_path, manifest, {"README.md": SPACE_CARD}, base="huggingface/organization", capsys=capsys)
    assert code == 0, err


def _dataset_manifest(**over) -> dict:
    return _manifest(ds=_dest(
        repo_id="acme/ds", repo_type="dataset", source_dir="huggingface/ds",
        files=["README.md", "data/*.csv"], required_card_keys=["license", "configs"], **over))


def test_a_good_dataset_card_passes(tmp_path, capsys) -> None:
    files = {"README.md": DATASET_CARD, "data/a.csv": "a,b\n1,2\n"}
    code, err = _run(tmp_path, _dataset_manifest(), files, base="huggingface/ds", capsys=capsys)
    assert code == 0, err


@pytest.mark.parametrize(
    ("card", "needle"),
    [
        ("---\nconfigs:\n  - config_name: d\n    data_files: data/*.csv\n---\n", "missing required key 'license'"),
        ("---\nlicense: mit\n---\n", "missing required key 'configs'"),
        ("---\nlicense: mit\nconfigs: []\n---\n", "missing required key 'configs'"),
        ("---\nlicense: mit\nconfigs:\n  - data_files: data/*.csv\n---\n", "config_name"),
        ("---\nlicense: mit\nconfigs:\n  - config_name: d\n---\n", "needs 'data_files'"),
        ("---\nlicense: mit\nconfigs:\n  - config_name: d\n    data_files: data/nothing-*.csv\n---\n", "matches no uploaded file"),
        ("---\nlicense: mit\nconfigs:\n  - config_name: d\n    data_files:\n      train: data/a.csv\n      test: data/gone.csv\n---\n", "data/gone.csv"),
    ],
)
def test_bad_dataset_cards_are_rejected(card, needle, tmp_path, capsys) -> None:
    files = {"README.md": card, "data/a.csv": "a,b\n1,2\n"}
    code, err = _run(tmp_path, _dataset_manifest(), files, base="huggingface/ds", capsys=capsys)
    assert code == 1
    assert needle in _failures(err), err


# --- references --------------------------------------------------------------------


def _page(body: str) -> dict[str, str | bytes]:
    return {**_good_files(), "index.html": f"<!doctype html><html><body>{body}</body></html>"}


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ('<img src="assets/missing.png">', "is not in the upload set"),
        ('<script src="app.js"></script>', "is not in the upload set"),
        ('<img src="/assets/a.svg">', "root-absolute"),
        ('<a href="http://example.org/x">x</a>', "uses http"),
        ('<a href="https://localhost:8000/x">x</a>', "local host"),
        ('<a href="https://192.168.1.4/x">x</a>', "private address"),
        ('<a href="file:///etc/passwd">x</a>', "scheme file"),
        ('<a href="javascript:alert(1)">x</a>', "scheme javascript"),
        ('<img src="//cdn.example.org/a.png">', "protocol-relative"),
        ('<a href="#nowhere">x</a>', "#nowhere does not exist"),
        ('<a href="../../../etc/passwd">x</a>', "escapes the upload directory"),
        ('<div style="background:url(gone.png)"></div>', "is not in the upload set"),
        ('<style>.a{background:url("gone.png")}</style>', "is not in the upload set"),
        ('<img srcset="assets/a.svg 1x, gone.png 2x">', "gone.png"),
    ],
)
def test_broken_or_unsafe_page_references_are_rejected(body, needle, tmp_path, capsys) -> None:
    code, err = _run(tmp_path, _manifest(), _page(body), capsys=capsys)
    assert code == 1
    assert needle in _failures(err), err


def test_good_references_pass(tmp_path, capsys) -> None:
    body = ('<a href="https://arxiv.org/abs/2607.28878?x=1#y">p</a><a href="mailto:a@b.org">m</a>'
            '<a href="#top">t</a><h2 id="top"></h2><img src="assets/a.svg?v=2"><img src="data:image/png;base64,AAAA">')
    code, err = _run(tmp_path, _manifest(), _page(body), capsys=capsys)
    assert code == 0, err


def test_a_css_reference_to_a_file_on_disk_but_not_uploaded_is_rejected(tmp_path, capsys) -> None:
    """The asset exists in the directory but is not allowlisted: it would 404 on the Hub."""
    files = {**_good_files(), "orphan.png": b"\x89PNG", "styles.css": "a{background:url(orphan.png)}"}
    code, err = _run(tmp_path, _manifest(), files, capsys=capsys)
    assert code == 1
    assert "orphan.png is not in the upload set" in _failures(err)


def test_card_markdown_links_are_checked_but_code_is_ignored(tmp_path, capsys) -> None:
    card = (SPACE_CARD + "![ok](assets/a.svg) [bad](assets/nope.png) [ext](https://arxiv.org/abs/1)\n"
            "```\n![in code](missing-in-code.png)\n```\nand `[inline](also-ignored.png)`\n"
            '<img src="assets/missing-html.png">\n[ref]: assets/missing-ref.png\n')
    files = {**_good_files(), "README.md": card}
    code, err = _run(tmp_path, _manifest(), files, capsys=capsys)
    text = _failures(err)
    assert code == 1
    assert "nope.png" in text and "missing-html.png" in text and "missing-ref.png" in text
    assert "missing-in-code" not in text and "also-ignored" not in text


# --- selection, approval, plan, export ----------------------------------------------


def _approved(manifest: dict, **over) -> dict:
    manifest["destinations"]["showcase"].update(owner_approved=True, status="live",
                                                url="https://huggingface.co/spaces/acme/showcase", **over)
    return manifest


def test_an_unapproved_destination_is_refused_for_publishing(tmp_path, capsys) -> None:
    code, err = _run(tmp_path, _manifest(), None, "--select", "showcase", "--require-approved", capsys=capsys)
    assert code == 1
    assert "owner_approved=false" in err and "refusing" in err


def test_a_planned_destination_is_refused_even_if_approved(tmp_path, capsys) -> None:
    manifest = _manifest()
    manifest["destinations"]["showcase"]["owner_approved"] = True
    code, err = _run(tmp_path, manifest, None, "--select", "showcase", "--require-approved", capsys=capsys)
    assert code == 1
    assert "status=planned" in err


def test_all_approved_with_nothing_approved_publishes_nothing(tmp_path, capsys) -> None:
    code, err = _run(tmp_path, _manifest(), None, "--select", "all-approved", "--require-approved", capsys=capsys)
    assert code == 1
    assert "nothing to publish" in err


def test_an_approved_live_destination_passes_and_is_staged(tmp_path, capsys) -> None:
    out = tmp_path / "gh_output"
    stage_dir = tmp_path / "stage"
    root = tmp_path / "repo"
    root.mkdir()
    _write_tree(root, _good_files())
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(_approved(_manifest())), encoding="utf-8")
    import os
    os.environ["GITHUB_OUTPUT"] = str(out)
    try:
        code = pf.main(["--manifest", str(mpath), "--root", str(root), "--skip-export-check",
                        "--select", "all-approved", "--require-approved", "--stage-dir", str(stage_dir),
                        "--github-output"])
    finally:
        del os.environ["GITHUB_OUTPUT"]
    assert code == 0, capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == 'selected=["showcase"]\n'
    assert (stage_dir / "showcase" / "index.html").is_file()


def test_unknown_destination_name(tmp_path, capsys) -> None:
    code, err = _run(tmp_path, _manifest(), None, "--select", "nope", capsys=capsys)
    assert code == 1 and "unknown destination" in err


def test_print_plan_lists_exactly_what_goes_where(tmp_path, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_tree(root, _good_files())
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(_manifest()), encoding="utf-8")
    code = pf.main(["--manifest", str(mpath), "--root", str(root), "--skip-export-check", "--print-plan"])
    out = capsys.readouterr().out
    assert code == 0
    assert "space acme/showcase" in out
    assert "oidc_resource=spaces/acme/showcase" in out
    for rel in ("README.md", "index.html", "styles.css", "assets/a.svg"):
        assert f"huggingface/showcase/{rel} -> {rel}" in out
    assert "delete_remote_files=false" in out


def _with_export(tmp_path: Path, exit_code: int) -> tuple[dict, Path]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "export_x.py").write_text(f"import sys\nprint('stale')\nsys.exit({exit_code})\n", encoding="utf-8")
    manifest = _manifest(showcase=_dest(export_check=["scripts/export_x.py", "--check"]))
    return manifest, root


@pytest.mark.parametrize(("exit_code", "expected"), [(0, 0), (1, 1)])
def test_the_export_check_gates_the_destination(exit_code, expected, tmp_path, capsys) -> None:
    manifest, root = _with_export(tmp_path, exit_code)
    _write_tree(root, _good_files())
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    code = pf.main(["--manifest", str(mpath), "--root", str(root)])
    err = capsys.readouterr().err
    assert code == expected, err
    if expected:
        assert "the exported data is stale" in err


def test_a_missing_export_script_fails(tmp_path, capsys) -> None:
    manifest = _manifest(showcase=_dest(export_check=["scripts/gone.py", "--check"]))
    root = tmp_path / "repo"
    root.mkdir()
    _write_tree(root, _good_files())
    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    assert pf.main(["--manifest", str(mpath), "--root", str(root)]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_the_export_check_runs_without_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "x")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("MY_API_SECRET", "x")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = pf._clean_env()
    assert "HF_TOKEN" not in env and "GITHUB_TOKEN" not in env and "MY_API_SECRET" not in env
    assert env["HF_HUB_OFFLINE"] == "1"


# --- no ability to publish ----------------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_preflight_has_no_ability_to_publish() -> None:
    path = SCRIPTS / "hf_preflight.py"
    imports = _imports(path)
    assert not {i for i in imports if i.split(".")[0] in {
        "huggingface_hub", "requests", "httpx", "socket", "http", "ftplib", "smtplib", "aiohttp", "websockets",
    }}, imports
    assert "urllib.request" not in imports and "urllib" not in imports
    assert imports <= {
        "__future__", "argparse", "html.parser", "ipaddress", "json", "os", "posixpath", "re",
        "shutil", "subprocess", "sys", "dataclasses", "pathlib", "urllib.parse", "yaml",
    }, imports
    source = path.read_text(encoding="utf-8")
    for needle in ("upload_file", "upload_folder", "create_commit", "create_repo", "HfApi", "hf upload",
                   "push_to_hub", "HF_TOKEN\"]", "get_token"):
        assert needle not in source, needle


def test_the_only_subprocess_runs_the_vetted_export_script() -> None:
    """subprocess is used in exactly one function, whose argv the schema pins to
    ['scripts/<name>.py', '--check']."""
    tree = ast.parse((SCRIPTS / "hf_preflight.py").read_text(encoding="utf-8"))
    users = [
        fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
        if any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "subprocess"
               for n in ast.walk(fn))
    ]
    assert users == ["run_export_check"], users


def test_the_scripts_name_their_encoding_for_text_io() -> None:
    for name in ("hf_preflight.py", "hf_collection.py"):
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "read_text()" not in source and "write_text(" not in source, name


def test_a_short_description_over_the_hubs_limit_is_rejected(tmp_path) -> None:
    # The Hub answers "Too big: expected string to have <=60 characters" and refuses the
    # push, so the preflight must say so first. 60 passes, 61 does not.
    assert pf.MAX_SHORT_DESCRIPTION == 60
    for length, ok in ((60, True), (61, False)):
        root = tmp_path / str(length)
        (root / "src").mkdir(parents=True)
        (root / "src" / "README.md").write_text(
            f"---\ntitle: T\nsdk: static\nshort_description: {'x' * length}\n---\n", encoding="utf-8"
        )
        dest = _dest(source_dir="src", files=["README.md", "index.html"], card_only=True)
        report = pf.Report()
        pf.check_card(root, "d", dest, dest["files"], report)
        messages = [str(e) for e in report.errors]
        assert (not messages) is ok, messages
        if not ok:
            assert any("short_description" in m for m in messages), messages
