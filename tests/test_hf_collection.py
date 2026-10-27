"""scripts/hf_collection.py: an idempotent, dry-run-by-default Collection manager.

No network and no credentials: the Hub client is replaced by a fake that records every
call, and the credential check is injected. The contract under test is the one the
script's docstring makes: create only if missing, add only what is missing, update a
note only when it differs, skip `planned` items, never delete, and never mutate unless
`--apply` is given on top of an approved manifest and an available credential.
"""

from __future__ import annotations

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

pf = _load("hf_preflight")  # first: hf_collection imports it by name
hc = _load("hf_collection")


class FakeHub:
    """An in-memory Hub that records every call made to it."""

    def __init__(self, *, namespaces=("yazses",), writable=("yazses",)) -> None:
        self.namespaces = set(namespaces)
        self.writable = set(writable)
        self.collections: dict[str, hc.RemoteCollection] = {}
        self.calls: list[tuple] = []
        self._ids = 0
        self.token_arg: object = "unset"

    # reads
    def namespace_exists(self, owner):
        self.calls.append(("namespace_exists", owner))
        return owner in self.namespaces

    def list_collections(self, owner):
        self.calls.append(("list_collections", owner))
        return [c for c in self.collections.values() if c.slug.startswith(owner + "/")]

    def get_collection(self, slug):
        self.calls.append(("get_collection", slug))
        return copy.deepcopy(self.collections[slug])

    def writable_namespaces(self):
        self.calls.append(("writable_namespaces",))
        return set(self.writable)

    # mutations
    def create_collection(self, title, owner, description, private):
        self.calls.append(("create_collection", title, owner, description, private))
        slug = f"{owner}/{title.lower().replace(' ', '-')}-abc123"
        self.collections[slug] = hc.RemoteCollection(
            slug, title, description, f"https://huggingface.co/collections/{slug}"
        )
        return copy.deepcopy(self.collections[slug])

    def add_item(self, slug, item_id, item_type, note):
        self.calls.append(("add_item", slug, item_id, item_type, note))
        self._ids += 1
        self.collections[slug].items.append(hc.RemoteItem(f"obj{self._ids}", item_id, item_type, note))

    def update_item_note(self, slug, object_id, note):
        self.calls.append(("update_item_note", slug, object_id, note))
        col = self.collections[slug]
        col.items = [
            hc.RemoteItem(i.object_id, i.item_id, i.item_type, note if i.object_id == object_id else i.note)
            for i in col.items
        ]

    def update_description(self, slug, description):
        self.calls.append(("update_description", slug, description))
        self.collections[slug].description = description

    @property
    def mutating_calls(self):
        return [c for c in self.calls if c[0] in hc.MUTATING_METHODS]


#: Items the scenario below holds back as "planned", whatever the real manifest says today.
SCENARIO_PLANNED = {"2607.28878", "yazses/showcase", "yazses/yazses-benchmark-results"}


def _scenario(*, approved: bool) -> dict:
    """The real manifest, forced into a fixed scenario: three items still planned.

    These tests exercise the diff logic, so they must not depend on which Hub pages exist
    today. Reading the real manifest's live state here made seven tests fail the day the
    pages were published, although nothing in the script had changed."""
    data = json.loads(pf.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    data["collection"]["owner_approved"] = approved
    for item in data["collection"]["items"]:
        if item["id"] in SCENARIO_PLANNED:
            item["status"] = "planned"
            item["url"] = None
    return data


@pytest.fixture
def manifest_path(tmp_path):
    """The scenario with the collection approved, so --apply is reachable."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_scenario(approved=True)), encoding="utf-8")
    return path


def _run(manifest_path, *argv, hub=None, token=True):
    hub = hub or FakeHub()
    lines: list[str] = []
    factory_args: list[tuple] = []

    def factory(token_arg, owner):
        factory_args.append((token_arg, owner))
        return hub

    code = hc.main(
        ["--manifest", str(manifest_path), *argv],
        client_factory=factory,
        token_present=lambda: token,
        out=lines.append,
    )
    return code, "\n".join(lines), hub, factory_args


LIVE_ITEMS = {
    ("space", "mskazemi/yazses-offline-transcription-demo"),
    ("model", "Systran/faster-whisper-tiny.en"),
    ("model", "Systran/faster-whisper-base.en"),
    ("model", "Systran/faster-whisper-small.en"),
}


def test_the_scenario_has_the_expected_live_and_planned_items(manifest_path) -> None:
    items = json.loads(manifest_path.read_text(encoding="utf-8"))["collection"]["items"]
    assert {(i["type"], i["id"]) for i in items if i["status"] == "live"} == LIVE_ITEMS
    assert {i["id"] for i in items if i["status"] == "planned"} == SCENARIO_PLANNED


def test_the_real_manifest_lists_every_scenario_item() -> None:
    # Whatever is live today, the collection must still name the pages the scenario holds back.
    items = json.loads(pf.DEFAULT_MANIFEST.read_text(encoding="utf-8"))["collection"]["items"]
    assert SCENARIO_PLANNED <= {i["id"] for i in items}
    assert {i["id"] for i in items if i["status"] == "live"} >= {i for _, i in LIVE_ITEMS}


def test_first_apply_creates_the_collection_and_adds_only_live_items(manifest_path) -> None:
    code, out, hub, _ = _run(manifest_path, "--apply")
    assert code == 0, out
    kinds = [c[0] for c in hub.mutating_calls]
    assert kinds == ["create_collection"] + ["add_item"] * 4
    added = {(c[3], c[2]) for c in hub.mutating_calls if c[0] == "add_item"}
    assert added == LIVE_ITEMS
    assert not any("showcase" in str(c) or "2607.28878" in str(c) for c in hub.mutating_calls)
    assert "Collection URL: https://huggingface.co/collections/yazses/" in out


def test_second_apply_makes_zero_mutating_calls(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    before = len(hub.mutating_calls)
    code, out, hub, _ = _run(manifest_path, "--apply", hub=hub)
    assert code == 0, out
    assert len(hub.mutating_calls) == before
    assert "Nothing to do" in out
    assert "Collection URL: https://huggingface.co/collections/yazses/" in out


def test_a_changed_note_updates_exactly_that_item(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in data["collection"]["items"]:
        if item["id"] == "Systran/faster-whisper-base.en":
            item["note"] = "A brand new note."
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    hub.calls.clear()
    code, out, hub, _ = _run(manifest_path, "--apply", hub=hub)
    assert code == 0, out
    assert [c[0] for c in hub.mutating_calls] == ["update_item_note"]
    assert hub.mutating_calls[0][3] == "A brand new note."
    # and then it is idempotent again
    hub.calls.clear()
    _run(manifest_path, "--apply", hub=hub)
    assert hub.mutating_calls == []


def test_a_changed_description_is_updated_once(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["collection"]["description"] = "A different, still short description."
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    hub.calls.clear()
    _run(manifest_path, "--apply", hub=hub)
    assert [c[0] for c in hub.mutating_calls] == ["update_description"]


def test_a_planned_item_becomes_live_and_is_added_later(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for dest in data["destinations"].values():
        if dest["repo_id"] == "yazses/showcase":
            dest.update(status="live", url="https://huggingface.co/spaces/yazses/showcase")
    for item in data["collection"]["items"]:
        if item["id"] == "yazses/showcase":
            item.update(status="live", url="https://huggingface.co/spaces/yazses/showcase",
                        evidence="verified in test")
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    hub.calls.clear()
    code, out, hub, _ = _run(manifest_path, "--apply", hub=hub)
    assert code == 0, out
    assert [(c[0], c[2]) for c in hub.mutating_calls] == [("add_item", "yazses/showcase")]


def test_extra_remote_items_are_reported_and_never_removed(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    slug = next(iter(hub.collections))
    hub.collections[slug].items.append(hc.RemoteItem("objX", "someone/else", "model", "hand added"))
    hub.calls.clear()
    code, out, hub, _ = _run(manifest_path, "--apply", hub=hub)
    assert code == 0
    assert "LEAVE model someone/else" in out
    assert hub.mutating_calls == []
    assert any(i.item_id == "someone/else" for i in hub.collections[slug].items)


def test_item_matching_ignores_case_in_the_id(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    slug = next(iter(hub.collections))
    col = hub.collections[slug]
    col.items = [hc.RemoteItem(i.object_id, i.item_id.lower(), i.item_type, i.note) for i in col.items]
    hub.calls.clear()
    _run(manifest_path, "--apply", hub=hub)
    assert hub.mutating_calls == []


# --- dry run -----------------------------------------------------------------------


@pytest.mark.parametrize("argv", [[], ["--dry-run"]])
def test_dry_run_is_the_default_and_makes_no_mutating_call(argv, manifest_path) -> None:
    code, out, hub, factory_args = _run(manifest_path, *argv)
    assert code == 0, out
    assert hub.mutating_calls == []
    assert "DRY RUN" in out
    assert "CREATE collection" in out and "Nothing was changed" in out
    assert factory_args == [(False, "yazses")], "a dry run must read anonymously (token=False)"
    assert "Collection URL" not in out, "no URL may be printed for a collection the API has not returned"


def test_dry_run_never_asks_for_a_credential(manifest_path) -> None:
    def boom():
        raise AssertionError("a dry run must not look up credentials")

    lines: list[str] = []
    code = hc.main(["--manifest", str(manifest_path)], client_factory=lambda t, o: FakeHub(),
                   token_present=boom, out=lines.append)
    assert code == 0


def test_dry_run_against_an_existing_collection_shows_the_diff_and_the_api_url(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    slug = next(iter(hub.collections))
    hub.collections[slug].items = hub.collections[slug].items[:2]
    hub.calls.clear()
    code, out, hub, _ = _run(manifest_path, hub=hub)
    assert code == 0
    assert out.count("ADD ") == 2
    assert f"Collection URL: https://huggingface.co/collections/{slug}" in out
    assert hub.mutating_calls == []


def test_offline_makes_no_client_at_all(manifest_path) -> None:
    code, out, hub, factory_args = _run(manifest_path, "--offline")
    assert code == 0
    assert factory_args == [] and hub.calls == []
    assert "Hub not consulted" in out and "Collection URL" not in out


def test_planned_items_are_skipped_and_say_so(manifest_path) -> None:
    _, out, _, _ = _run(manifest_path, "--offline")
    assert out.count("SKIP ") == 3
    assert "planned: not live yet" in out


# --- refusals ----------------------------------------------------------------------


def test_apply_without_a_credential_is_a_clear_error_and_touches_nothing(manifest_path) -> None:
    code, out, hub, factory_args = _run(manifest_path, "--apply", token=False)
    assert code == 2
    assert "no Hugging Face credential found" in out and "hf auth login" in out
    assert factory_args == [] and hub.calls == []


def test_apply_with_an_unapproved_collection_is_refused(tmp_path) -> None:
    unapproved = tmp_path / "unapproved.json"
    unapproved.write_text(json.dumps(_scenario(approved=False)), encoding="utf-8")
    code, out, hub, factory_args = _run(unapproved, "--apply")
    assert code == 1
    assert "owner_approved is false" in out
    assert factory_args == [] and hub.calls == []


def test_a_missing_organisation_is_a_clear_error(manifest_path) -> None:
    code, out, hub, _ = _run(manifest_path, "--apply", hub=FakeHub(namespaces=()))
    assert code == 2
    assert "'yazses' does not exist" in out and "Create it in the Hub web UI" in out
    assert hub.mutating_calls == []


def test_a_missing_organisation_is_also_reported_in_a_dry_run(manifest_path) -> None:
    code, out, hub, _ = _run(manifest_path, hub=FakeHub(namespaces=()))
    assert code == 2
    assert "does not exist" in out and "Would-be plan" in out
    assert hub.mutating_calls == []


def test_a_credential_that_is_not_a_member_cannot_apply(manifest_path) -> None:
    code, out, hub, _ = _run(manifest_path, "--apply", hub=FakeHub(writable=("someone-else",)))
    assert code == 2 and "not a member of 'yazses'" in out
    assert hub.mutating_calls == []


def test_duplicate_titles_are_refused_not_guessed(manifest_path) -> None:
    hub = FakeHub()
    _run(manifest_path, "--apply", hub=hub)
    first = next(iter(hub.collections.values()))
    dup = copy.deepcopy(first)
    dup.slug = "yazses/duplicate-zzz"
    hub.collections[dup.slug] = dup
    hub.calls.clear()
    code, out, hub, _ = _run(manifest_path, "--apply", hub=hub)
    assert code == 1 and "titled" in out and hub.mutating_calls == []


def test_offline_and_apply_conflict(manifest_path) -> None:
    code, out, hub, _ = _run(manifest_path, "--apply", "--offline")
    assert code == 1 and hub.calls == []


def test_an_invalid_manifest_stops_before_any_client(tmp_path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    code, out, hub, factory_args = _run(path, "--apply")
    assert code == 1 and "FAIL" in out and factory_args == []


def test_a_token_in_the_environment_is_never_printed(manifest_path, monkeypatch) -> None:
    secret = "hf_" + "Z" * 34
    monkeypatch.setenv("HF_TOKEN", secret)
    for argv in (["--apply"], [], ["--offline"]):
        _, out, _, _ = _run(manifest_path, *argv)
        assert secret not in out


# --- the real client adapter, without a network ---------------------------------------


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _HttpError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code} with a secret-looking body")
        self.response = _Resp(code)


@pytest.mark.parametrize(
    ("code", "cls", "needle"),
    [
        (401, hc.AuthError, "rejected the credentials"),
        (403, hc.AuthError, "Write role"),
        (404, hc.ApiError, "not found"),
        (409, hc.ApiError, "conflict"),
        (500, hc.ApiError, "HTTP 500"),
    ],
)
def test_hub_errors_become_short_messages_without_the_body(code, cls, needle) -> None:
    err = hc._translate(_HttpError(code), "doing a thing", "yazses")
    assert isinstance(err, cls) and needle in str(err)
    assert "secret-looking" not in str(err)
    assert err.exit_code == (2 if cls is hc.AuthError else 3)


def test_the_script_calls_only_the_verified_huggingface_hub_api() -> None:
    """Every HfApi method the adapter names exists in the installed huggingface_hub."""
    import re

    hub = pytest.importorskip("huggingface_hub")
    source = (ROOT / "scripts" / "hf_collection.py").read_text(encoding="utf-8")
    used = set(re.findall(r"self\._api\.([a-z_]+)", source))
    assert {"list_collections", "get_collection", "create_collection", "add_collection_item",
            "update_collection_item", "update_collection_metadata"} <= used
    for name in used | {"get_organization_overview", "get_user_overview", "whoami"}:
        assert hasattr(hub.HfApi, name), name


def test_the_adapter_makes_dry_runs_anonymous(monkeypatch) -> None:
    """With token=False every call is forwarded token=False, the huggingface_hub spelling of
    'send no Authorization header'."""
    pytest.importorskip("huggingface_hub")
    seen: list[object] = []

    class Api:
        def get_organization_overview(self, owner, token=None):
            seen.append(token)

        def list_collections(self, owner=None, token=None):
            seen.append(token)
            return []

    client = hc.HfApiClient(False, "yazses")
    client._api = Api()
    assert client.namespace_exists("yazses") is True
    assert client.list_collections("yazses") == []
    assert seen == [False, False]
