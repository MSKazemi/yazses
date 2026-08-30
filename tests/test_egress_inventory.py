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

#: Local by construction, but not by AF_UNIX — so they cannot join `LOCAL_IPC`, whose
#: whole assertion is the address family. Each is pinned by its own proof below, because
#: "it's local" is a claim about one line of code and needs a test that reads that line.
LOCAL_BOUND = {
    "remote/agent.py": (
        "`asyncio.start_server` bound to 127.0.0.1 — the far end of the SSH tunnel, "
        "reachable only through it. `host='0.0.0.0'` here would put a text-injection "
        "port on the LAN, and it is a one-word diff"
    ),
    "platform/emg/ble_backend.py": (
        "imports `asyncio` to drive a Bluetooth LE muscle sensor; a radio is not an IP "
        "network and no socket is opened. Declared rather than excluded, for the reason "
        "given above `_NETWORK_ROOTS`"
    ),
}

#: Reaches the network by HANDING A URL TO ANOTHER PROGRAM. The fourth mechanism, found
#: the same way as the second and third: by asking what the existing scans still cannot
#: see. We open no connection — the user's browser does — but we choose the destination
#: and the moment, and one caller chooses a payload.
HANDOFF = {
    "system/browser.py": (
        "`webbrowser.open(url)` hands a URL to the desktop's browser. Every caller but "
        "one passes a fixed documentation or release URL. The exception is "
        "`core/daemon.py::_open_issue_report`, which builds a pre-filled GitHub issue "
        "URL: the diagnostic report travels to github.com percent-encoded in the query "
        "string **when the page opens**, not when the user presses submit. The body is "
        "`report.collect`'s redacted output — the same redaction `yazses report` uses, "
        "so no dictation is in it — but it is a real transmission and belongs here"
    ),
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
    "system/deps.py": (
        "runs `uv pip install` (or `python -m pip install`) so `yazses features enable "
        "<name>` can fetch that feature's optional extras from PyPI. Sends only package "
        "names; what comes back is **code that then runs in this interpreter**, which "
        "is why it belongs in the inventory rather than being waved through as tooling"
    ),
    "system/setup.py": (
        "runs `sudo apt-get update` and `sudo apt-get install` for the OS packages "
        "`yazses setup` needs (ydotool, wl-clipboard). Reaches the distribution's "
        "mirrors, with root, at the user's explicit request"
    ),
    "system/updater.py": (
        "spawns the upgrade the user chose -- `snap refresh`, `uv tool upgrade`, `pipx "
        "upgrade`, `pip install --upgrade`, winget/choco/scoop -- which downloads and "
        "installs a new version. Its FETCH row covers reading the version *string*; "
        "this is the much larger transfer that follows a yes"
    ),
}

#: Reaches the network by ASKING A DEPENDENCY TO LOAD A MODEL BY NAME, not by importing a
#: socket and not by spawning a program. The third mechanism, found the same way as the
#: second: by asking what the two existing scans still cannot see.
#:
#: `WhisperModel("base.en")`, `onnx_asr.load_model(...)`, `EncoderClassifier.from_hparams(...)`
#: and `Pipeline.from_pretrained(...)` all take a *repository id*, and the library resolves
#: it against huggingface.co. Nothing in this repository imports `requests`; the fetch is
#: real regardless. ADR-019 named `faster-whisper` in prose as "the obvious case" — these are
#: the three that were not obvious, and one of them sends a credential.
DEPENDENCY_FETCH = {
    "stt/faster_whisper.py": (
        "faster-whisper resolves the model id against huggingface.co. Tries the local "
        "cache first (`local_files_only=True`) and only downloads on a miss"
    ),
    "stt/parakeet.py": "onnx-asr resolves the Parakeet model id against huggingface.co",
    "stt/moonshine.py": (
        "useful-moonshine-onnx resolves the Moonshine model id against huggingface.co. "
        "Found by `tests/test_model_cache_first.py` and missed here for a release: that "
        "file's loader vocabulary listed `MoonshineOnnxModel` and this one did not, so "
        "the module fell between two guards over the same mechanism -- the identical "
        "failure this file already records about `download_model`"
    ),
    "voiceprint/ecapa.py": (
        "speechbrain fetches `speechbrain/spkrec-ecapa-voxceleb` (~20 MB) from "
        "huggingface.co when a voiceprint is enrolled or matched"
    ),
    "recimport/pyannote_backend.py": (
        "pyannote fetches a gated pipeline from huggingface.co **carrying the user's HF "
        "token** — the only fetch here that identifies who is asking"
    ),
    "stt/download.py": (
        "calls `faster_whisper.utils.download_model` to fetch a Whisper checkpoint on "
        "purpose, with progress — the deliberate version of what `stt/faster_whisper.py` "
        "used to do implicitly on the daemon's startup path (issue #310)"
    ),
    "cli.py": "invokes `download_stt_model` for `yazses model download`",
    "voiceprint/resemblyzer_backend.py": (
        "resemblyzer's `VoiceEncoder()` loads weights shipped inside its own wheel. "
        "Declared anyway: the scan cannot tell a bundled load from a fetch, and this "
        "file's rule is that a false positive costs one line and a false negative costs "
        "the promise"
    ),
}

#: Loader calls that take a model *name* and may resolve it over the network. Same
#: conservatism as `_NETWORK_ROOTS`: over-matching costs a row above.
#: `download_model`, `snapshot_download` and `hf_hub_download` were missing, so the one
#: module whose entire job is to fetch a checkpoint -- `stt/download.py`, written for
#: issue #310 -- was the one this scan could not see. `test_model_cache_first.py` already
#: knew `snapshot_download`: two guards over the same mechanism kept separate vocabularies,
#: and the file fell between them.
_DEPENDENCY_LOADERS = frozenset(
    {"WhisperModel", "load_model", "from_hparams", "from_pretrained", "VoiceEncoder",
     "download_model", "snapshot_download", "hf_hub_download", "MoonshineOnnxModel"}
)

ALLOWED = {**FETCH, **SEND, **LOCAL_IPC, **LOCAL_BOUND, **HANDOFF}

#: Programs that can open an outbound connection when spawned. Conservative for the same
#: reason as `_NETWORK_ROOTS`: a false positive costs a line in the table above.
#:
#: The **package managers** were added by asking this file's own question once more —
#: what can the scan still not see? It listed transports (`ssh`, `curl`, `git`) and no
#: installers, so the two modules that fetch and then *execute* third-party code were
#: invisible: `system/deps.py` runs `uv pip install` when a feature is enabled, and
#: `system/setup.py` runs `sudo apt-get install`. Downloading code to run is the largest
#: thing that can cross this wire, and it was the one class of program the list omitted.
_NETWORK_TOOLS = frozenset(
    {"ssh", "scp", "sftp", "rsync", "curl", "wget", "nc", "ncat", "netcat", "ftp",
     "telnet", "git",
     # installers: fetch a package index, then fetch and run code
     "uv", "pip", "pip3", "pipx", "apt", "apt-get", "brew", "npm",
     "snap", "winget", "choco", "scoop"}
)

#: Import paths that can open an outbound connection. Deliberately conservative: a false
#: positive costs one line in the table above, a false negative costs the promise.
#:
#: `asyncio` and `webbrowser` were added after a sweep asked the opposite question — not
#: "is every declared module still here" but "is every network-capable import in the tree
#: on this list". Three modules were invisible to the scan because neither name was:
#: `remote/agent.py` (`asyncio.start_server`), `platform/emg/ble_backend.py`, and
#: `system/browser.py` — the last of which is the one that actually carries a payload.
#: Both names have overwhelmingly non-network uses, and that is fine: over-matching costs
#: a row below and under-matching costs the promise this whole file exists to keep.
_NETWORK_ROOTS = {"urllib", "http", "socket", "requests", "httpx", "aiohttp", "ftplib",
                  "smtplib", "asyncio", "webbrowser"}


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
        # Inside a list literal, which is the shape an argv has. Any string constant
        # would do, and did until the tool list grew: `windowctl/focus.py` compares a
        # layout action against `("snap", "center")`, and declaring that module as a
        # spawner of `snap` would put a false row in a table the project publishes.
        # Every hit the looser rule found is still found -- checked, not assumed.
        hits = {
            element.value
            for node in ast.walk(tree)
            if isinstance(node, ast.List)
            for element in node.elts
            if isinstance(element, ast.Constant)
            and isinstance(element.value, str)
            and element.value in _NETWORK_TOOLS
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


def test_the_remote_agent_listens_only_on_loopback():
    """The one-word diff that would expose a text-injection port to the network.

    `yazses-agent` accepts text and types it into whatever has focus. Bound to
    127.0.0.1 it is reachable only through the user's own SSH tunnel; bound to 0.0.0.0
    it is reachable from the LAN. Nothing else in the tree would notice the change --
    the import scan could not even see this module until `asyncio` was added to
    `_NETWORK_ROOTS`.
    """
    source = (SRC / "remote/agent.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in source, "the agent no longer pins its bind to loopback"
    for wildcard in ('"0.0.0.0"', '"::"', "host=None"):
        assert wildcard not in source, (
            f"remote/agent.py binds {wildcard} — that is an ADR-019 change, not a refactor"
        )


def test_the_ble_backend_opens_no_socket():
    """`asyncio` here drives a radio, not an address. If that stops being true, say so."""
    source = (SRC / "platform/emg/ble_backend.py").read_text(encoding="utf-8")
    for primitive in ("start_server", "open_connection", "AF_INET", "import socket"):
        assert primitive not in source, (
            f"platform/emg/ble_backend.py now uses {primitive} — it is no longer "
            f"local-by-construction and needs a real inventory row"
        )


@pytest.mark.parametrize("module", sorted(HANDOFF))
def test_a_handoff_opens_no_connection_of_its_own(module: str):
    """The distinction the category rests on: we choose a URL, we do not fetch it."""
    source = (SRC / module).read_text(encoding="utf-8")
    for primitive in ("urlopen", "requests.", "httpx.", "socket."):
        assert primitive not in source, (
            f"{module} is declared as a handoff but calls {primitive} itself"
        )


def test_the_issue_url_says_when_the_report_actually_travels():
    """`issue_url`'s docstring said "submits nothing", which invited the wrong reading.

    True of the *issue*: GitHub's form is not submitted. Not true of the *report*, which
    is in the query string of the GET that opens the page — so it reaches github.com at
    the click, before the user has read a word of it. The payload is redacted either way;
    the timing is what a reader deserves to be told.
    """
    source = (SRC / "system/report.py").read_text(encoding="utf-8")
    start = source.index("def issue_url(")
    doc = source[start:start + 1200]
    assert "before" in doc or "when the page opens" in doc, (
        "issue_url's docstring must say the body reaches GitHub when the page opens, "
        "not when the user submits"
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


def _modules_fetching_through_a_dependency() -> dict[str, list[str]]:
    """Every `yazses` module that asks a dependency to load a model by name.

    Keyed and spelled exactly like the other two scans, for the same OS-portability
    reason recorded in `test_module_keys_are_posix_on_every_os`.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - fails elsewhere, loudly
            continue
        hits = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else None
            )
            if name in _DEPENDENCY_LOADERS:
                hits.add(name)
        if hits:
            found[path.relative_to(SRC).as_posix()] = sorted(hits)
    return found


def test_the_dependency_fetch_scan_finds_something():
    """Guard the guard, third detector: an empty result must not read as clean.

    The product cannot run without loading a speech model, so a scan that finds no
    loader at all has stopped working — it has not discovered that YazSes stopped
    downloading anything.
    """
    assert _modules_fetching_through_a_dependency(), (
        "the dependency-loader scan found nothing at all, which cannot be right — "
        "the detector is broken, not the codebase"
    )


def test_no_undeclared_module_can_fetch_through_a_dependency():
    """The gap ADR-019 wrote down and then only half-closed.

    The ADR states the limitation plainly — *"a dependency making its own network calls
    is not caught — `faster-whisper` fetching a model is the obvious case"* — and stops
    at naming the obvious one. Three more were already in the tree: Parakeet, ECAPA and
    pyannote. A stated limitation is not a guard; this is the guard.
    """
    found = _modules_fetching_through_a_dependency()
    undeclared = {m: calls for m, calls in found.items() if m not in DEPENDENCY_FETCH}
    assert not undeclared, (
        "these modules ask a dependency to load a model by name and are not in the "
        f"ADR-019 inventory: {undeclared}\n\n"
        "Add them to DEPENDENCY_FETCH here and to the table in "
        "design/adr/adr-019-egress-inventory-and-escalation.md. If the load carries a "
        "credential, say so in both places — an anonymous model GET and an "
        "authenticated one are different disclosures."
    )


def test_the_dependency_fetch_inventory_has_no_stale_entries():
    """Same reason as the import inventory: an entry for a module that no longer loads a
    model overstates the exposure and teaches the next reader to skim."""
    found = set(_modules_fetching_through_a_dependency())
    stale = sorted(set(DEPENDENCY_FETCH) - found)
    assert not stale, (
        f"these are listed as dependency fetches but no longer call a model loader: "
        f"{stale}. Remove them from the table and from here."
    )


@pytest.mark.parametrize("module", sorted(DEPENDENCY_FETCH))
def test_every_dependency_fetch_is_documented_in_the_adr(module: str):
    """The ADR table and this file must not drift apart — the reason the ADR exists is
    that an auditor can read one table instead of grepping."""
    adr = (SRC.parent.parent / "design/adr/adr-019-egress-inventory-and-escalation.md")
    assert module in adr.read_text(encoding="utf-8"), (
        f"{module} fetches a model through a dependency but is not named in ADR-019"
    )


def test_the_one_credentialed_fetch_is_singled_out():
    """An anonymous model download and an authenticated one are different disclosures.

    Every other fetch here is a public GET that says nothing about who is asking. The
    pyannote pipeline is gated, so the request carries the user's Hugging Face token —
    which identifies the account to a third party, on a machine whose headline claim is
    that nothing leaves it. That difference has to survive in writing, or the next
    reader files it under "downloads a model, like the others".
    """
    assert "token" in DEPENDENCY_FETCH["recimport/pyannote_backend.py"]
    source = (SRC / "recimport/pyannote_backend.py").read_text(encoding="utf-8")
    assert "token=" in source, (
        "pyannote_backend no longer passes a token — if the fetch became anonymous, "
        "say so here and in ADR-019 rather than deleting this test"
    )
    credentialed = [m for m, why in DEPENDENCY_FETCH.items() if "token" in why]
    assert credentialed == ["recimport/pyannote_backend.py"], (
        f"a second credentialed fetch appeared: {credentialed}. That is an ADR-019 "
        f"change, not a refactor."
    )


def test_a_dependency_fetch_is_not_counted_as_a_send_path():
    """These pull weights down; none of them pushes anything up.

    Worth asserting rather than assuming, because the public claim is a *count* — "two
    code paths can send your words anywhere" — and the cheapest way to break it is to
    add a fifth inventory whose entries quietly also transmit.
    """
    for module in DEPENDENCY_FETCH:
        assert module not in SEND
    assert len(SEND) == 2


#: Every inventory in this file, so the cross-check below cannot omit one by being
#: written per-inventory. `SEND`, `HANDOFF` and `DEPENDENCY_FETCH` each had their own
#: ADR check; `FETCH`, `SHELL_OUT`, `LOCAL_IPC` and `LOCAL_BOUND` had none, so four of
#: the seven could gain a module that never reached the table an auditor actually reads.
_INVENTORIES = {
    "FETCH": FETCH, "SEND": SEND, "LOCAL_IPC": LOCAL_IPC, "LOCAL_BOUND": LOCAL_BOUND,
    "HANDOFF": HANDOFF, "SHELL_OUT": SHELL_OUT, "DEPENDENCY_FETCH": DEPENDENCY_FETCH,
}


@pytest.mark.parametrize(
    ("inventory", "module"),
    [(name, module) for name, entries in _INVENTORIES.items() for module in sorted(entries)],
    ids=lambda value: value.replace("/", ".") if "/" in str(value) else value,
)
def test_every_declared_module_reaches_the_published_table(inventory: str, module: str) -> None:
    """The ADR is what an auditor reads; this file is what the build enforces.

    ADR-019 already records one of these drifting: a hand-written "seven" stayed after
    the count had been five for months, and the ADR names that as "the same failure the
    enforced inventory exists to prevent, one level up". This is the general form —
    derived from the inventories rather than written per-inventory, so a new class of
    egress is covered the day someone adds the dict.
    """
    adr = (SRC.parent.parent / "design/adr/adr-019-egress-inventory-and-escalation.md")
    assert module in adr.read_text(encoding="utf-8"), (
        f"{module} is declared in {inventory} here but is named nowhere in ADR-019. "
        "The table is the artefact people audit; a module known only to the test suite "
        "is undocumented egress with a passing build."
    )


def test_the_cross_check_covers_every_inventory_in_this_file() -> None:
    """Guards the guard: a new inventory dict that nobody adds to `_INVENTORIES` would
    be checked by nothing, and this file would still be green."""
    declared = {
        name for name, value in globals().items()
        # `ALLOWED` is these dicts merged, not a source of its own; including it would
        # make the check pass by counting the same modules twice.
        if name.isupper() and name != "ALLOWED" and isinstance(value, dict)
        and value and all(str(key).endswith(".py") for key in value)
    }
    assert declared == set(_INVENTORIES), (
        f"these inventories are not in `_INVENTORIES` and so reach no ADR check: "
        f"{sorted(declared - set(_INVENTORIES))}"
    )
