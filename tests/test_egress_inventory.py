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
from pathlib import Path, PureWindowsPath

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
#: Reaches the network by SPAWNING A PROGRAM, not by importing a network primitive.
#: The import scan cannot see these, which is how the most consequential transport in
#: the product stayed invisible to a guard written to enumerate exactly that.
#:
#: `remote/forwarder.py` is deliberately NOT a third SEND. The remote path is one logical
#: route -- dictated text -> loopback TCP (`local_proxy`) -> this SSH tunnel -> the agent
#: on the far host -- and counting it twice would overstate the exposure the project
#: publishes. What it does correct is the wording: `local_proxy` connects to 127.0.0.1
#: and nowhere else; this is the half that makes loopback reach the host the user named.
SHELL_OUT = {
    "remote/forwarder.py": (
        "spawns `ssh` to open the reverse tunnel carrying `remote/local_proxy.py`'s "
        "loopback traffic to the host named on the command line — the transport half of "
        "that SEND, not a separate one"
    ),
    "gitvoice/plan.py": (
        "builds a `git` argv from a dictated command; `cli.py` runs it only under "
        "`--run` (and `--yes` when destructive), so `git push` can reach the user's own "
        "remote. Carries repository content at explicit request, never dictation"
    ),
}

ALLOWED = {**FETCH, **SEND, **LOCAL_IPC}

#: Programs that can open an outbound connection when spawned. Conservative for the same
#: reason as `_NETWORK_ROOTS`: a false positive costs a line in the table above.
_NETWORK_TOOLS = frozenset(
    {"ssh", "scp", "sftp", "rsync", "curl", "wget", "nc", "ncat", "netcat", "ftp",
     "telnet", "git"}
)

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
            # `.as_posix()`, not `str()`: `str()` renders a WindowsPath with
            # backslashes (`ipc\client.py`), and the inventory below is keyed with
            # forward slashes. On Windows that made *every* module look undeclared
            # and *every* inventory entry look stale — 9 phantom egress findings
            # and a red `main`, while Linux and macOS stayed green. The key is a
            # stable identifier shared with a markdown table, so it must not vary
            # by the OS that happens to run the suite.
            found[path.relative_to(SRC).as_posix()] = sorted(hits)
    return found


def _modules_shelling_out_to_network_tools() -> dict[str, list[str]]:
    """Every `yazses` module that names a network-capable program and uses subprocess.

    Keyed and spelled exactly like the import scan, for the same OS-portability reason.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if not any(m in text for m in ("subprocess", "Popen", "shutil.which")):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:  # pragma: no cover - fails elsewhere, loudly
            continue
        hits = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in _NETWORK_TOOLS
        }
        if hits:
            found[path.relative_to(SRC).as_posix()] = sorted(hits)
    return found


def test_the_scan_finds_something():
    """Guard the guard: a broken detector must not read as a clean bill of health."""
    assert _modules_with_network_imports(), (
        "the network-import scan found nothing at all, which cannot be right — "
        "the detector is broken, not the codebase"
    )


def test_module_keys_are_posix_on_every_os():
    """The inventory key must not depend on which OS ran the suite.

    This scan keys modules by their path relative to `src/yazses`, and the same
    string is used in the ADR-019 markdown table. `str(WindowsPath(...))` renders
    backslashes, so on Windows every module missed the forward-slash inventory:
    nine phantom "undeclared egress" findings *and* nine phantom "stale entry"
    findings at once, with Linux and macOS green throughout.

    Asserting on the live scan would prove nothing here — on Linux both spellings
    agree. Constructing the Windows flavour explicitly is what makes this
    regression visible on any machine.
    """
    windows = PureWindowsPath("ipc/client.py")
    assert str(windows) == r"ipc\client.py", "precondition: str() uses backslashes"
    assert windows.as_posix() == "ipc/client.py"

    # And the keys the real scan produces agree with the inventory's spelling.
    for key in _modules_with_network_imports():
        assert "\\" not in key, f"module key is not POSIX-spelled: {key!r}"


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


def test_the_shell_out_scan_finds_something():
    """Guard the guard, second detector: an empty result must not read as clean."""
    assert _modules_shelling_out_to_network_tools(), (
        "the shell-out scan found nothing, which cannot be right — `remote/forwarder.py` "
        "spawns ssh. The detector is broken, not the codebase"
    )


def test_no_undeclared_module_can_spawn_a_network_tool():
    """The blind spot this closes.

    The import scan enumerates modules that `import socket` or `import urllib`. It cannot
    see `subprocess.Popen(["ssh", ...])`, and that is how the reverse tunnel — the
    transport that actually carries dictated text off this machine — sat outside an
    inventory written to enumerate exactly that. The documented limitation was
    "a dependency making its own call"; spawning a program was not mentioned.
    """
    found = _modules_shelling_out_to_network_tools()
    undeclared = {m: tools for m, tools in found.items() if m not in SHELL_OUT}
    assert not undeclared, (
        f"these modules spawn a network-capable program and are not declared: "
        f"{undeclared}\n\nAdd them to SHELL_OUT here and to the ADR-019 table. If the "
        f"program carries anything the user said, ADR-019's escalation rules apply."
    )


def test_the_shell_out_inventory_has_no_stale_entries():
    found = set(_modules_shelling_out_to_network_tools())
    stale = sorted(set(SHELL_OUT) - found)
    assert not stale, f"declared but no longer spawning a network tool: {stale}"


def test_the_ssh_tunnel_is_not_counted_as_a_third_send_path():
    """It is the transport half of an existing SEND, and the count is a public claim.

    `local_proxy` connects to 127.0.0.1 and nowhere else; the tunnel is what makes that
    loopback reach the host the user named. One logical route, declared in two places
    because two files implement it — counting it twice would overstate the exposure.
    """
    assert "remote/forwarder.py" in SHELL_OUT
    assert "remote/forwarder.py" not in SEND
    assert len(SEND) == 2


def test_the_git_path_is_declared_as_carrying_repository_content():
    """`yazses gitvoice "push" --run` reaches a remote. It carries the user's repository
    at their explicit request, never dictation — a distinction worth keeping in writing,
    because "it only runs git" is exactly the reasoning that would wave through a later
    change that piped a transcript into it."""
    assert "dictation" in SHELL_OUT["gitvoice/plan.py"]
    assert "gitvoice/plan.py" not in SEND
