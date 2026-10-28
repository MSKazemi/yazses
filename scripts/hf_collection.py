#!/usr/bin/env python3
"""Idempotent manager for the YazSes Hugging Face Collection.

The collection is defined once, in ``huggingface/manifest.json`` (``collection``). This
script makes the Hub match it, and it is safe to run again and again:

* the collection is found by **owner + title**, and created only if it is missing;
* an item is added only if it is not already in the collection;
* an item's note is updated only if it differs from the manifest;
* items marked ``planned`` (the Hub resource does not exist yet) are skipped until
  someone flips them to ``live`` in the manifest;
* nothing is ever removed: items on the Hub that the manifest does not mention are
  reported and left alone.

The default is a **dry run**: it reads the public Hub anonymously (no credential is read
or sent), prints exactly what ``--apply`` would do, and calls no mutating API.
``--offline`` skips even that read.

    uv run python scripts/hf_collection.py                # dry run, anonymous read
    uv run python scripts/hf_collection.py --offline      # dry run, no network at all
    uv run python scripts/hf_collection.py --apply        # mutate (owner only)

``--apply`` needs two things beyond the flag: ``collection.owner_approved`` set to true
in the manifest, and a credential already available to ``huggingface_hub`` (``HF_TOKEN``
or ``hf auth login``). The credential is never read into a variable, printed or logged.
The Hub organisation (``collection.owner``) must already exist; this script does not
create it.

API surface used (huggingface_hub 1.23, read from the installed source, not assumed):
``HfApi.list_collections(owner=)``, ``get_collection``, ``create_collection``,
``add_collection_item``, ``update_collection_item``, ``update_collection_metadata``,
plus ``get_organization_overview``/``get_user_overview`` and ``whoami`` for the owner
checks. Failures surface as ``HfHubHTTPError`` and are translated here to short
messages (status code only).

Exit status: 0 success (including a dry run that shows work to do), 1 bad manifest, bad
usage or a refused ``--apply``, 2 missing credentials or missing/unwritable owner,
3 a Hub API error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hf_preflight import (  # noqa: E402
    DEFAULT_MANIFEST,
    ManifestError,
    Report,
    load_manifest,
    validate_schema,
)

EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_API = 0, 1, 2, 3


# --- errors ----------------------------------------------------------------------


class CollectionError(Exception):
    """A failure with a user-readable message and the exit status to use."""

    exit_code = EXIT_USAGE


class AuthError(CollectionError):
    exit_code = EXIT_AUTH


class NamespaceError(CollectionError):
    exit_code = EXIT_AUTH


class ApiError(CollectionError):
    exit_code = EXIT_API


# --- the client seam -------------------------------------------------------------


@dataclass(frozen=True)
class RemoteItem:
    object_id: str
    item_id: str
    item_type: str
    note: str | None = None


@dataclass
class RemoteCollection:
    slug: str
    title: str
    description: str | None
    url: str
    items: list[RemoteItem] = field(default_factory=list)


class HubClient(Protocol):
    """Everything this script needs from the Hub. Tests inject a fake."""

    # reads
    def namespace_exists(self, owner: str) -> bool: ...
    def list_collections(self, owner: str) -> list[RemoteCollection]: ...
    def get_collection(self, slug: str) -> RemoteCollection: ...
    def writable_namespaces(self) -> set[str]: ...
    # mutations (only ever called under --apply)
    def create_collection(
        self, title: str, owner: str, description: str, private: bool
    ) -> RemoteCollection: ...
    def add_item(self, slug: str, item_id: str, item_type: str, note: str) -> None: ...
    def update_item_note(self, slug: str, object_id: str, note: str) -> None: ...
    def update_description(self, slug: str, description: str) -> None: ...


MUTATING_METHODS = frozenset(
    {"create_collection", "add_item", "update_item_note", "update_description"}
)


def _status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _translate(exc: BaseException, what: str, owner: str) -> CollectionError:
    code = _status(exc)
    if code == 401:
        return AuthError(
            f"the Hub rejected the credentials (HTTP 401) while {what}. "
            "Run `hf auth login`, or export a token with write access."
        )
    if code == 403:
        return AuthError(
            f"the credential cannot write to '{owner}' (HTTP 403) while {what}; it needs the "
            "Write role in that organisation"
        )
    if code == 404:
        return ApiError(f"not found (HTTP 404) while {what}")
    if code == 409:
        return ApiError(f"conflict (HTTP 409) while {what}")
    return ApiError(f"Hub error{f' (HTTP {code})' if code else ''} while {what}: {type(exc).__name__}")


class HfApiClient:
    """The real client: a thin adapter over ``huggingface_hub.HfApi``.

    ``token=False`` (dry run) makes every call anonymous. ``token=None`` (``--apply``)
    lets huggingface_hub resolve the credential itself, so this module never holds it.
    """

    def __init__(self, token: bool | None, owner: str) -> None:
        import httpx
        from huggingface_hub import HfApi, get_session  # lazy: the offline path never needs them

        # huggingface_hub's shared client has no timeout at all (timeout=None); on a host
        # with a dead IPv6 route a read would hang forever. Bound every call.
        get_session().timeout = httpx.Timeout(30.0, connect=10.0)
        self._api: Any = HfApi()
        self._token = token
        self._owner = owner

    def _call(self, what: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        from huggingface_hub.errors import HfHubHTTPError

        try:
            return fn(*args, token=self._token, **kwargs)
        except HfHubHTTPError as exc:
            raise _translate(exc, what, self._owner) from None

    @staticmethod
    def _view(c: Any) -> RemoteCollection:
        return RemoteCollection(
            slug=c.slug,
            title=c.title,
            description=c.description,
            url=c.url,
            items=[
                RemoteItem(i.item_object_id, i.item_id, i.item_type, i.note) for i in c.items
            ],
        )

    def namespace_exists(self, owner: str) -> bool:
        from huggingface_hub.errors import HfHubHTTPError

        for method in ("get_organization_overview", "get_user_overview"):
            try:
                getattr(self._api, method)(owner, token=self._token)
                return True
            except HfHubHTTPError as exc:
                if _status(exc) != 404:
                    raise _translate(exc, f"looking up '{owner}'", owner) from None
        return False

    def list_collections(self, owner: str) -> list[RemoteCollection]:
        found = self._call(
            f"listing collections of '{owner}'",
            lambda token: list(self._api.list_collections(owner=owner, token=token)),
        )
        return [self._view(c) for c in found]

    def get_collection(self, slug: str) -> RemoteCollection:
        return self._view(
            self._call(f"reading collection {slug}", self._api.get_collection, slug)
        )

    def writable_namespaces(self) -> set[str]:
        info = self._call("checking who the credential belongs to", self._api.whoami)
        names = {info.get("name", "")}
        names.update(o.get("name", "") for o in info.get("orgs", []) or [])
        return {n for n in names if n}

    def create_collection(
        self, title: str, owner: str, description: str, private: bool
    ) -> RemoteCollection:
        return self._view(
            self._call(
                f"creating collection '{title}'",
                self._api.create_collection,
                title,
                namespace=owner,
                description=description,
                private=private,
            )
        )

    def add_item(self, slug: str, item_id: str, item_type: str, note: str) -> None:
        self._call(
            f"adding {item_type} {item_id}",
            self._api.add_collection_item,
            slug,
            item_id,
            item_type,
            note=note,
        )

    def update_item_note(self, slug: str, object_id: str, note: str) -> None:
        self._call("updating a note", self._api.update_collection_item, slug, object_id, note=note)

    def update_description(self, slug: str, description: str) -> None:
        self._call(
            "updating the description",
            self._api.update_collection_metadata,
            slug,
            description=description,
        )


def default_token_present() -> bool:
    """True if huggingface_hub can find a credential. The value is never kept."""
    try:
        from huggingface_hub import get_token

        return get_token() is not None
    except Exception as exc:  # noqa: BLE001 - OIDC exchange failures raise; report the class only
        raise AuthError(
            f"looking up the Hub credential failed ({type(exc).__name__}); check HF_TOKEN / "
            "`hf auth login` / HF_OIDC_RESOURCE"
        ) from None


# --- planning (pure) -------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    kind: str  # create-collection | update-description | add-item | update-note | skip-planned | extra-remote
    item_type: str = ""
    item_id: str = ""
    note: str = ""
    object_id: str = ""
    detail: str = ""

    @property
    def mutating(self) -> bool:
        return self.kind in {"create-collection", "update-description", "add-item", "update-note"}

    def describe(self) -> str:
        if self.kind == "create-collection":
            return f"CREATE collection {self.detail}"
        if self.kind == "update-description":
            return "UPDATE description"
        if self.kind == "add-item":
            return f"ADD {self.item_type} {self.item_id}"
        if self.kind == "update-note":
            return f"UPDATE note on {self.item_type} {self.item_id}"
        if self.kind == "skip-planned":
            return f"SKIP {self.item_type} {self.item_id} (planned: not live yet)"
        return f"LEAVE {self.item_type} {self.item_id} ({self.detail})"


def build_plan(cfg: dict, remote: RemoteCollection | None) -> list[Action]:
    """Diff the manifest's collection against the Hub. Pure: no I/O."""
    actions: list[Action] = []
    if remote is None:
        actions.append(Action("create-collection", detail=f"'{cfg['title']}' under {cfg['owner']}"))
    elif (remote.description or "") != cfg["description"]:
        actions.append(Action("update-description"))

    existing = {} if remote is None else {(i.item_type, i.item_id.lower()): i for i in remote.items}
    wanted: set[tuple[str, str]] = set()
    for item in cfg["items"]:
        key = (item["type"], item["id"].lower())
        if item["status"] != "live":
            actions.append(Action("skip-planned", item["type"], item["id"]))
            continue
        wanted.add(key)
        have = existing.get(key)
        if have is None:
            actions.append(Action("add-item", item["type"], item["id"], note=item["note"]))
        elif (have.note or "").strip() != item["note"].strip():
            actions.append(
                Action("update-note", item["type"], item["id"], item["note"], have.object_id)
            )
    planned_keys = {(i["type"], i["id"].lower()) for i in cfg["items"]}
    for key, have in sorted(existing.items()):
        if key not in wanted and key not in planned_keys:
            actions.append(
                Action("extra-remote", have.item_type, have.item_id, detail="not in the manifest; never removed")
            )
    return actions


# --- driver ----------------------------------------------------------------------


def _find_remote(client: HubClient, cfg: dict) -> RemoteCollection | None:
    owner, title = cfg["owner"], cfg["title"]
    matches = [
        c
        for c in client.list_collections(owner)
        if c.title.strip() == title.strip() and c.slug.lower().startswith(owner.lower() + "/")
    ]
    if len(matches) > 1:
        raise CollectionError(
            f"{len(matches)} collections of '{owner}' are titled '{title}' "
            f"({', '.join(m.slug for m in matches)}); delete the duplicates by hand, then re-run"
        )
    return client.get_collection(matches[0].slug) if matches else None


def execute(client: HubClient, cfg: dict, remote: RemoteCollection | None, actions: list[Action]) -> RemoteCollection:
    """Apply the mutating actions in order and return the collection as the API reports it."""
    slug = remote.slug if remote else ""
    for action in actions:
        if not action.mutating:
            continue
        if action.kind == "create-collection":
            created = client.create_collection(
                cfg["title"], cfg["owner"], cfg["description"], bool(cfg.get("private", False))
            )
            slug = created.slug
        elif action.kind == "update-description":
            client.update_description(slug, cfg["description"])
        elif action.kind == "add-item":
            client.add_item(slug, action.item_id, action.item_type, action.note)
        elif action.kind == "update-note":
            client.update_item_note(slug, action.object_id, action.note)
    return client.get_collection(slug)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Idempotent manager for the YazSes Hugging Face Collection (dry run by default).",
        epilog="Exit status: 0 ok, 1 bad manifest/usage/refused, 2 credentials or owner, 3 Hub API error.",
    )
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the diff, mutate nothing (default)")
    mode.add_argument("--apply", action="store_true", help="make the Hub match the manifest")
    p.add_argument("--offline", action="store_true", help="dry run without any network read")
    return p


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[[bool | None, str], HubClient] | None = None,
    token_present: Callable[[], bool] = default_token_present,
    out: Callable[[str], None] = print,
) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.offline:
        out("hf_collection: ERROR: --offline cannot be combined with --apply")
        return EXIT_USAGE
    factory = client_factory or HfApiClient

    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        out(f"hf_collection: ERROR: {exc}")
        return EXIT_USAGE
    report = Report()
    validate_schema(manifest, report)
    if report.errors:
        for line in report.errors:
            out(f"FAIL {line}")
        return EXIT_USAGE
    cfg = manifest["collection"]
    owner = cfg["owner"]

    try:
        if args.apply:
            if cfg["owner_approved"] is not True:
                raise CollectionError(
                    "collection.owner_approved is false in huggingface/manifest.json; refusing "
                    "--apply. The owner approves by editing that flag in a reviewed commit."
                )
            if not token_present():
                raise AuthError(
                    "no Hugging Face credential found. Run `hf auth login` or set HF_TOKEN "
                    "(the value is never printed), then re-run with --apply."
                )

        remote: RemoteCollection | None = None
        client: HubClient | None = None
        if not args.offline:
            client = factory(None if args.apply else False, owner)
            if not client.namespace_exists(owner):
                out(format_plan(cfg, build_plan(cfg, None), None, args, header="Would-be plan"))
                raise NamespaceError(
                    f"the Hub user or organisation '{owner}' does not exist. Create it in the Hub "
                    "web UI first (the owner does this; this script cannot)."
                )
            if args.apply and owner not in client.writable_namespaces():
                raise NamespaceError(
                    f"the credential is not a member of '{owner}', so it cannot create a "
                    "collection there"
                )
            remote = _find_remote(client, cfg)

        actions = build_plan(cfg, remote)
        out(format_plan(cfg, actions, remote, args))

        if args.apply:
            assert client is not None
            if not any(a.mutating for a in actions):
                out("Nothing to do: the collection already matches the manifest.")
                final: RemoteCollection | None = remote
            else:
                final = execute(client, cfg, remote, actions)
                out(f"Applied {sum(a.mutating for a in actions)} change(s).")
            if final is not None:
                out(f"Collection URL: {final.url}")
        elif remote is not None:
            out(f"Collection URL: {remote.url}")
    except CollectionError as exc:
        out(f"hf_collection: ERROR: {exc}")
        return exc.exit_code
    return EXIT_OK


def format_plan(
    cfg: dict,
    actions: list[Action],
    remote: RemoteCollection | None,
    args: argparse.Namespace,
    *,
    header: str | None = None,
) -> str:
    mode = "APPLY" if args.apply else ("DRY RUN (offline)" if args.offline else "DRY RUN")
    if remote is None and not args.apply and not args.offline:
        where = "not found on the Hub"
    elif args.offline:
        where = "Hub not consulted"
    else:
        where = remote.slug if remote else "will be created"
    lines = [f"{header or 'Collection'}: '{cfg['title']}' under {cfg['owner']} [{mode}] ({where})"]
    lines += [f"  {a.describe()}" for a in actions]
    if not any(a.mutating for a in actions):
        lines.append("  (no changes needed)")
    elif not args.apply:
        lines.append("  Nothing was changed. Re-run with --apply to make these changes.")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
