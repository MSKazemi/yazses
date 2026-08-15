"""Every way data can leave this machine is declared (ADR-019).

ADR-011 promises nothing leaves the machine. That promise is only as strong as a
complete, true list of the exceptions — and until ADR-019 no such list existed. The
shipped product makes outbound connections for entirely legitimate reasons (model
downloads, an opt-in version check, a user's own SSH tunnel), documented one page at a
time, if at all.

So the inventory is enforced rather than written down. A module that gains an outbound
network primitive fails this test until it is registered below and classified:

* **FETCH** — data comes *in* only: model weights, a version string. No user content is
  transmitted.
* **SEND** — user content can go *out*. There are exactly two, and both are constrained:
  `llm_cleanup` is confined to loopback by `is_loopback_endpoint()`, and `local_proxy`
  goes only to a host the user named on the command line.

This is the same shape as `test_feature_wiring_honesty.py`, which stops the capability
registry lying about what is reachable. The privacy claim deserves at least the guard the
feature list already gets.

**Known limitation, and it is in the ADR too:** this detects primitives in *our* code by
AST. A dependency making its own call is not caught — `faster-whisper` fetching a model is
the obvious case. That is why the docs also publish a `--network none` container check:
this guards our code, the container guards the whole process.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import yazses

SRC = Path(yazses.__file__).resolve().parent

#: Modules allowed to contain an outbound network primitive, and why.
#: Keep in step with the table in `design/adr/adr-019-egress-inventory-and-escalation.md`.
FETCH = {
    "commands/model_manager.py": "downloads a GGUF from huggingface.co when an LLM feature is enabled",
    "gaze/download.py": "downloads the MediaPipe face-landmarker model",
    "recimport/download.py": "downloads sherpa-onnx diarization models",
    "tts/download.py": "downloads the Kokoro voice model",
    "system/updater.py": "reads a version string from PyPI or the GitHub API (opt-in)",
}
SEND = {
    "postprocess/llm_cleanup.py": "POSTs dictated text — CONFINED TO LOOPBACK by is_loopback_endpoint()",
    "remote/local_proxy.py": "sends dictated text to the SSH host the user named on the command line",
}
#: Imports `socket` and cannot reach the network at all: AF_UNIX is a filesystem
#: object, not an address. Recorded rather than excluded from the scan, because
#: "it's only IPC" is exactly the reasoning that would wave through an AF_INET
#: socket added to the same file later — the assertion below pins the family.
LOCAL_IPC = {
    "ipc/client.py": "AF_UNIX stream socket to the daemon's socket path",
    "ipc/server.py": "AF_UNIX stream socket, bound to the daemon's socket path",
}
ALLOWED = {**FETCH, **SEND, **LOCAL_IPC}

#: Import paths that can open an outbound connection. Deliberately conservative: a false
#: positive costs one line in the table above, a false negative costs the promise.
_NETWORK_ROOTS = {"urllib", "http", "socket", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}


def _modules_with_network_imports() -> dict[str, list[str]]:
    """Every `yazses` module importing a network primitive, and which."""
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere, loudly
            continue
        hits = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _NETWORK_ROOTS:
                        hits.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _NETWORK_ROOTS:
                    hits.add(node.module)
        if hits:
            found[str(path.relative_to(SRC))] = sorted(hits)
    return found


def test_the_scan_finds_something():
    """Guard the guard: a broken detector must not read as a clean bill of health."""
    assert _modules_with_network_imports(), (
        "the network-import scan found nothing at all, which cannot be right — "
        "the detector is broken, not the codebase"
    )


def test_no_undeclared_module_can_reach_the_network():
    """The whole point: a new outbound call is a decision, not an accident."""
    found = _modules_with_network_imports()
    undeclared = {m: imports for m, imports in found.items() if m not in ALLOWED}
    assert not undeclared, (
        "these modules can open an outbound connection and are not in the ADR-019 "
        f"inventory: {undeclared}\n\n"
        "If the call is legitimate, add it to FETCH or SEND here and to the table in "
        "design/adr/adr-019-egress-inventory-and-escalation.md. If it transmits anything "
        "the user said, it is a SEND and ADR-019's escalation rules apply: off by "
        "default, explicit per-invocation opt-in, credentials from a named environment "
        "variable, a consent prompt naming the host, and visible while it happens."
    )


def test_the_inventory_has_no_stale_entries():
    """An entry for a module that no longer reaches the network overstates the exposure
    and, worse, trains the next reader to skim the list."""
    found = set(_modules_with_network_imports())
    stale = sorted(set(ALLOWED) - found)
    assert not stale, (
        f"these are listed in the ADR-019 inventory but no longer import a network "
        f"primitive: {stale}. Remove them from the table and from here."
    )


def test_only_two_paths_can_send_what_the_user_said():
    """The claim the project makes in public, asserted directly.

    If this number grows, the sentence 'two code paths can send your words anywhere, one
    confined to your own machine and the other only where you told it' stops being true
    — and that sentence is load-bearing in the README, the docs and ADR-011.
    """
    assert len(SEND) == 2, (
        f"the inventory now lists {len(SEND)} paths that can transmit user content. "
        f"That is a change to the project's central privacy claim and needs an ADR, "
        f"not a test edit."
    )


def test_the_one_configurable_send_path_is_loopback_guarded():
    """`llm_cleanup` takes a user-supplied URL, so its guard is the whole protection.

    It once POSTed dictated text to any host the config named. The guard deliberately
    does not trust DNS: a name resolving to 127.0.0.1 today can resolve elsewhere
    tomorrow, and `http://127.0.0.1@evil.com` parses to `evil.com`.
    """
    from yazses.postprocess.llm_cleanup import is_loopback_endpoint

    assert is_loopback_endpoint("http://localhost:11434")
    assert is_loopback_endpoint("http://127.0.0.1:11434")
    for hostile in (
        "http://127.0.0.1@evil.com",
        "http://evil.com",
        "http://localhost.evil.com",
        "",
        "not a url",
    ):
        assert not is_loopback_endpoint(hostile), f"{hostile!r} must not count as local"


@pytest.mark.parametrize("module", sorted(SEND))
def test_every_send_path_is_documented_in_the_adr(module: str):
    """The ADR table and this file must not drift apart."""
    adr = (SRC.parent.parent / "design/adr/adr-019-egress-inventory-and-escalation.md")
    assert module in adr.read_text(encoding="utf-8"), (
        f"{module} can transmit user content but is not named in ADR-019"
    )


@pytest.mark.parametrize("module", sorted(LOCAL_IPC))
def test_the_ipc_sockets_stay_local_only(module: str):
    """`AF_UNIX` is what makes IPC non-network. If one of these ever names `AF_INET`,
    the daemon becomes reachable from off the machine and the promise is gone — so the
    family is asserted rather than assumed from the module's name.
    """
    source = (SRC / module).read_text(encoding="utf-8")
    assert "AF_UNIX" in source, f"{module} no longer uses AF_UNIX"
    assert "AF_INET" not in source, (
        f"{module} mentions AF_INET. A network-family IPC socket makes the daemon "
        f"reachable from another machine; that is an ADR-019 change, not a refactor."
    )
