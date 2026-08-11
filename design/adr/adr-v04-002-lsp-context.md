# ADR-v04-002: LSP Context Injection for Whisper Decoder Priming

| Field | Value |
|---|---|
| **ID** | ADR-v04-002 |
| **Status** | Accepted |
| **Date** | 2026-05-17 |
| **Module** | `src/yazses/commands/lsp_context.py` |

---

## Context

Whisper is a general-purpose speech recognition model trained on broad internet audio. It has no knowledge of the active codebase, project naming conventions, or programming language in use. When a developer dictates code by voice — identifiers, method names, domain-specific abbreviations — the decoder frequently substitutes phonetically similar common words for the intended technical terms.

The `faster-whisper` `WhisperModel.transcribe()` method accepts an `initial_prompt` string. This string is prepended to the decoder context and biases the token probability distribution toward vocabulary that appears in the prompt. Injecting a short excerpt of the active file (function names, identifiers, imports) materially reduces correction rates for technical dictation without requiring model retraining.

Fetching that context requires communicating with the active editor. Two editor communication protocols cover the majority of the target user base: the Language Server Protocol (LSP) used by VS Code and most modern editors, and Neovim's msgpack-RPC API.

---

## Decision

Use `pygls >= 1.3.0` for JSON-RPC LSP transport and `pynvim >= 0.5.0` for Neovim msgpack-RPC. Both libraries are wrapped behind an `EditorBridge` protocol:

```python
class EditorBridge(Protocol):
    def connect(self) -> bool: ...
    def get_context(self) -> CodeContext | None: ...
```

`CodeContext` carries the active file path, language identifier, a short identifier list extracted from the visible range, and the current line content. This structure is serialised into the `initial_prompt` string at transcription time.

A hard 50 ms timeout is enforced on every `get_context()` call. If the editor does not respond within that window — or if no editor bridge is connected — the call returns `None` and transcription proceeds with no `initial_prompt`. Context injection is never allowed to block or delay the audio pipeline.

LSP context injection is disabled by default. It is enabled by setting `[commands] lsp_enabled = true` in `config.toml`.

---

## Rationale

**`pygls` is the reference Python LSP library.** It is used internally by `python-lsp-server` (pylsp) and is actively maintained. Using the reference implementation reduces the risk of protocol edge cases and gives access to its typed message models.

**`pynvim` is the official Neovim Python client.** It is maintained by the Neovim project and is the only supported path for out-of-process Python integration with Neovim's msgpack-RPC API.

**`EditorBridge` protocol enables future editors without daemon changes.** Emacs (via `eglot` or direct RPC), Helix, and Zed can be added by implementing the two-method protocol in a new module and registering it in `lsp_context.py`. The daemon sees only `EditorBridge`; it does not need to know which editor is active.

**Voice is primary; context is optional refinement.** The 50 ms hard timeout and `None`-on-failure design guarantee that a misbehaving editor extension, a stalled LSP server, or a missing `$NVIM` socket never interrupts or degrades dictation. Context improves transcription accuracy when available; absence of context is the safe state.

**Asymmetric coupling.** YazSes queries the editor; the editor does not query YazSes. The editor's LSP server continues to operate normally. There is no persistent connection: each transcription that needs context opens a short-lived query and closes it.

---

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| **Direct JSON-RPC via stdlib `socket` + `json`** | Possible but requires reimplementing LSP framing, capability negotiation, and response matching — comparable lines of code to `pygls` with no benefit |
| **VS Code Language Server direct connection** | VS Code does not expose a public socket for client connections; would require a companion VS Code extension even for basic context (deferred to a future release) |
| **Reading the active buffer from the filesystem** | File on disk is not always current (unsaved edits); no language metadata; no visible range information |

---

## Consequences

- **Two new optional deps** under the `lsp` extra. Neither is imported at daemon startup unless `lsp_enabled = true`.
- **Neovim integration** requires `$NVIM` environment variable to be set in the shell that launches YazSes, pointing to the active Neovim socket. When absent, the Neovim bridge silently returns `None`.
- **VS Code integration** requires a companion extension to relay context over a local socket. The extension is deferred; VS Code support in v0.4.0 is limited to connecting to a running LSP server if it exposes a socket.
- **Partial context is still useful.** If `get_context()` returns a `CodeContext` with only the language identifier and file path (no identifier list), the `initial_prompt` still biases the decoder toward code formatting.
- **Privacy note.** Context strings are passed to the local Whisper model only. No data leaves the machine. This must be documented in the user-facing config reference.

---

## Configuration

```toml
[commands]
lsp_enabled = false
lsp_editor = "auto"   # "auto" | "neovim" | "vscode"
```

`lsp_editor = "auto"` probes `$NVIM` first, then falls back to LSP socket discovery.

---

## Dependency

Optional dep group `lsp` in `pyproject.toml`:

```toml
[project.optional-dependencies]
lsp = [
    "pygls >= 1.3.0",
    "pynvim >= 0.5.0",
]
```

Install with:

```bash
uv sync --extra lsp
```
