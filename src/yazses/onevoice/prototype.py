"""Dependency-free OneVoice *draft-only* proof of concept.

This module deliberately has no OS, microphone, network, model or daemon hooks.
It is a contract experiment pending ADR-025, not a production interaction kernel.
Only explicitly armed command-mode utterances are considered for routing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Operation(str, Enum):
    DRAFT = "draft_insert"
    SEND = "submit_external"


class Status(str, Enum):
    READY = "ready"
    CONFIRM_REQUIRED = "confirmation_required"
    UNRECOGNIZED = "not_a_route"
    UNKNOWN = "unknown_destination"
    AMBIGUOUS = "ambiguous_destination"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported_operation"
    REFUSED = "refused"
    VERIFIED = "draft_inserted_verified"
    UNVERIFIED = "insertion_unverified"


@dataclass(frozen=True)
class Destination:
    destination_id: str
    aliases: tuple[str, ...]
    operations: frozenset[Operation] = frozenset({Operation.DRAFT})


@dataclass(frozen=True)
class Target:
    destination_id: str
    instance_id: str
    field_id: str
    revision: int
    editable: bool = True
    secure: bool = False


@dataclass(frozen=True)
class Command:
    operation: Operation
    alias: str
    payload: str


@dataclass(frozen=True)
class Proposal:
    request_id: str
    operation: Operation
    destination_id: str
    payload: str
    target: Target


@dataclass(frozen=True)
class Decision:
    status: Status
    proposal: Proposal | None = None
    reason: str = ""


@dataclass(frozen=True)
class Grant:
    """Explicit, expiring permission for one destination and instance."""

    destination_id: str
    instance_id: str
    operations: frozenset[Operation]
    expires_at_s: float
    user_approved: bool = False


class DestinationAdapter(Protocol):
    def describe(self) -> Destination: ...
    def snapshot(self) -> Target | None: ...
    def insert_draft(self, expected: Target, payload: str, request_id: str) -> bool: ...
    def verify_draft(self, request_id: str, payload: str) -> bool | None: ...


def _key(alias: str) -> str:
    return " ".join(alias.casefold().split())


# A colon is an intentional boundary between a destination name and *data*.
# Do not search for command words inside the payload or normalized transcript.
_COMMAND = re.compile(
    r"^\s*(?:yazses[ ,]+)?(?P<verb>write to|draft for|ask|send to) "
    r"(?P<alias>[^:\n]{1,80}):[ \t]*(?P<payload>[^\n]+(?:\n[^\n]*)*)$",
    re.IGNORECASE,
)


def parse_command(utterance: str, *, command_mode: bool = False) -> Command | None:
    """Parse only command-mode phrases; preserve payload case and punctuation."""
    if not command_mode:
        return None
    match = _COMMAND.fullmatch(utterance)
    if match is None or not match["payload"].strip():
        return None
    operation = (
        Operation.DRAFT if match["verb"].casefold() in ("write to", "draft for")
        else Operation.SEND
    )
    return Command(operation, match["alias"].strip(), match["payload"])


class Registry:
    """A small in-memory allowlist, not automatic window/app discovery."""

    def __init__(self) -> None:
        self._by_id: dict[str, DestinationAdapter] = {}
        self._by_alias: dict[str, list[str]] = {}

    def register(self, adapter: DestinationAdapter) -> None:
        dest = adapter.describe()
        if not dest.destination_id.strip() or not dest.aliases:
            raise ValueError("Destination needs an id and at least one alias")
        if dest.destination_id in self._by_id:
            raise ValueError("Duplicate destination id")
        keys = {_key(x) for x in dest.aliases}
        if not keys or "" in keys:
            raise ValueError("Empty destination alias")
        self._by_id[dest.destination_id] = adapter
        for key in keys:
            self._by_alias.setdefault(key, []).append(dest.destination_id)

    def resolve(self, alias: str) -> tuple[DestinationAdapter, ...]:
        return tuple(self._by_id[x] for x in self._by_alias.get(_key(alias), ()))

    def get(self, destination_id: str) -> DestinationAdapter | None:
        return self._by_id.get(destination_id)


class Router:
    """Plan, authorize and verify a draft insertion; never submit externally."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._consumed: set[str] = set()

    def plan(self, utterance: str, *, command_mode: bool, request_id: str) -> Decision:
        command = parse_command(utterance, command_mode=command_mode)
        if command is None:
            return Decision(Status.UNRECOGNIZED)
        if not request_id.strip():
            return Decision(Status.REFUSED, reason="missing_request_id")
        matches = self.registry.resolve(command.alias)
        if not matches:
            return Decision(Status.UNKNOWN, reason="destination_not_registered")
        if len(matches) != 1:
            return Decision(Status.AMBIGUOUS, reason="multiple_matching_destinations")
        adapter = matches[0]
        try:
            dest = adapter.describe()
        except Exception:
            return Decision(Status.UNAVAILABLE, reason="capabilities_lookup_failed")
        if command.operation not in dest.operations:
            return Decision(Status.UNSUPPORTED, reason="operation_not_declared")
        try:
            target = adapter.snapshot()
        except Exception:  # no adapter failure should break normal dictation
            return Decision(Status.UNAVAILABLE, reason="target_lookup_failed")
        if target is None or target.destination_id != dest.destination_id:
            return Decision(Status.UNAVAILABLE, reason="target_not_found")
        if not target.editable or target.secure:
            return Decision(Status.REFUSED, reason="noneditable_or_secure_target")
        proposal = Proposal(request_id, command.operation, dest.destination_id,
                            command.payload, target)
        if command.operation is Operation.SEND:
            return Decision(Status.CONFIRM_REQUIRED, proposal, "external_send_not_implemented")
        return Decision(Status.READY, proposal)

    def execute_draft(self, proposal: Proposal, grant: Grant, *, now_s: float) -> Decision:
        """Only a fresh, bound, user-approved grant can produce a local draft."""
        if not proposal.request_id.strip() or proposal.request_id in self._consumed:
            return Decision(Status.REFUSED, reason="missing_or_replayed_request_id")
        if proposal.operation is not Operation.DRAFT:
            return Decision(Status.CONFIRM_REQUIRED, reason="external_send_not_implemented")
        if (not grant.user_approved or now_s >= grant.expires_at_s
                or grant.destination_id != proposal.destination_id
                or grant.instance_id != proposal.target.instance_id
                or proposal.operation not in grant.operations):
            return Decision(Status.REFUSED, reason="grant_missing_expired_or_wrong_scope")
        adapter = self.registry.get(proposal.destination_id)
        if adapter is None:
            return Decision(Status.REFUSED, reason="destination_no_longer_authorized")
        try:
            description = adapter.describe()
        except Exception:
            return Decision(Status.UNAVAILABLE, reason="capabilities_lookup_failed")
        if (description.destination_id != proposal.destination_id
                or proposal.operation not in description.operations):
            return Decision(Status.REFUSED, reason="destination_no_longer_authorized")
        try:
            target = adapter.snapshot()
        except Exception:
            return Decision(Status.UNAVAILABLE, reason="target_lookup_failed")
        if target != proposal.target or target is None or not target.editable or target.secure:
            return Decision(Status.REFUSED, reason="target_changed_or_invalid")
        self._consumed.add(proposal.request_id)
        try:
            inserted = adapter.insert_draft(target, proposal.payload, proposal.request_id)
            if not inserted:
                return Decision(Status.UNVERIFIED, reason="insertion_not_confirmed")
            verified = adapter.verify_draft(proposal.request_id, proposal.payload)
        except Exception:
            return Decision(Status.UNVERIFIED, reason="adapter_failed_after_attempt")
        if verified is True:
            return Decision(Status.VERIFIED)
        return Decision(Status.UNVERIFIED, reason="readback_missing_or_mismatched")


class FakeEditor:
    """Two of these simulate two apps; this class cannot touch actual OS windows."""

    def __init__(self, destination_id: str, aliases: tuple[str, ...], *,
                 instance_id: str, field_id: str = "document",
                 can_readback: bool = True,
                 operations: frozenset[Operation] = frozenset({Operation.DRAFT})) -> None:
        self._description = Destination(destination_id, aliases, operations)
        self.instance_id = instance_id
        self.field_id = field_id
        self.can_readback = can_readback
        self.content = ""
        self.revision = 0
        self.editable = True
        self.secure = False
        self.closed = False
        self._last_insert: tuple[str, str, str] | None = None

    def describe(self) -> Destination:
        return self._description

    def snapshot(self) -> Target | None:
        if self.closed:
            return None
        return Target(self._description.destination_id, self.instance_id,
                      self.field_id, self.revision, self.editable, self.secure)

    def insert_draft(self, expected: Target, payload: str, request_id: str) -> bool:
        if self.snapshot() != expected or not self.editable or self.secure:
            return False
        self.content += payload
        self.revision += 1
        self._last_insert = (request_id, payload, self.content)
        return True

    def verify_draft(self, request_id: str, payload: str) -> bool | None:
        if not self.can_readback or self.closed:
            return None
        return self._last_insert == (request_id, payload, self.content)

    def external_edit(self, new_content: str) -> None:
        self.content = new_content
        self.revision += 1
