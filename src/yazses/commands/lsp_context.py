"""LSP context provider for code-aware transcription (v0.4.0, ADR-v04-002).

Reads the active editor's language, scope, and recent identifiers via LSP and
injects the result into the faster-whisper initial_prompt to improve code vocabulary
recognition. All bridges implement EditorBridge; failure to connect returns None
cleanly — the transcription pipeline is never blocked.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


@dataclass
class CodeContext:
    language_id: str          # e.g. "python", "typescript"
    file_path: str            # active file
    scope_chain: list[str]    # e.g. ["class BatchProcessor", "method process_batch"]
    recent_identifiers: list[str]  # top-20 nearby symbols
    cursor_line: int = 0

    def to_prompt_string(self) -> str:
        """Format context as a Whisper initial_prompt string."""
        parts = [f"Language: {self.language_id}."]
        if self.scope_chain:
            parts.append(f"Scope: {', '.join(self.scope_chain)}.")
        if self.recent_identifiers:
            parts.append(f"Recent identifiers: {', '.join(self.recent_identifiers[:10])}.")
        return " ".join(parts)


class EditorBridge(Protocol):
    def connect(self) -> bool: ...
    def get_context(self) -> CodeContext | None: ...
    def get_symbols(self) -> dict[str, int]: ...
    def apply_motion(self, kind: str, payload: object) -> bool: ...


class NullBridge:
    """Fallback bridge that always returns None — used when no editor is detected."""

    def connect(self) -> bool:
        return False

    def get_context(self) -> CodeContext | None:
        return None

    def get_symbols(self) -> dict[str, int]:
        return {}

    def apply_motion(self, kind: str, payload: object) -> bool:
        return False


class NeovimBridge:
    """Bridge to a running Neovim instance via its RPC socket ($NVIM)."""

    _FILETYPE_TO_LANGUAGE_ID: dict[str, str] = {
        "python": "python",
        "typescript": "typescript",
        "typescriptreact": "typescriptreact",
        "javascript": "javascript",
        "javascriptreact": "javascriptreact",
        "go": "go",
        "rust": "rust",
        "c": "c",
        "cpp": "cpp",
        "java": "java",
        "lua": "lua",
        "ruby": "ruby",
        "sh": "shellscript",
        "bash": "shellscript",
        "zsh": "shellscript",
        "html": "html",
        "css": "css",
        "json": "json",
        "yaml": "yaml",
        "toml": "toml",
        "markdown": "markdown",
        "vim": "vim",
        "tex": "latex",
    }

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._nvim: Any = None
        self._available: bool = True

        try:
            import pynvim  # noqa: F401 — probe import only
        except ImportError:
            self._available = False

    def connect(self) -> bool:
        if not self._available:
            return False
        if not self._socket_path or not os.path.exists(self._socket_path):
            return False
        try:
            import pynvim

            self._nvim = pynvim.attach("socket", path=self._socket_path)
            return True
        except Exception:
            log.debug("NeovimBridge: failed to attach to %s", self._socket_path, exc_info=True)
            self._nvim = None
            return False

    def read_cursor_line(self) -> str | None:
        """Return the text of the line the cursor is on, or ``None`` on failure.

        Used by the learning loop's EditWatcher to read back what the user typed
        after a dictation. Never raises.
        """
        if self._nvim is None and not self.connect():
            return None
        try:
            nvim = self._nvim  # type: ignore[assignment]
            row, _col = nvim.current.window.cursor  # (1-based row, 0-based col)
            line: str = nvim.current.buffer[row - 1]
            return line
        except Exception:
            log.debug("NeovimBridge: read_cursor_line failed", exc_info=True)
            self._nvim = None
            return None

    def get_context(self) -> CodeContext | None:
        if self._nvim is None:
            if not self.connect():
                return None

        try:
            nvim = self._nvim  # type: ignore[assignment]

            # Language / filetype
            raw_ft: str = nvim.command_output("echo &filetype").strip()
            language_id = self._FILETYPE_TO_LANGUAGE_ID.get(raw_ft, raw_ft) if raw_ft else "plaintext"

            # Active file
            file_path: str = nvim.current.buffer.name or ""

            # Cursor position (0-based in API, convert to 1-based line number)
            row, _col = nvim.current.window.cursor  # (1-based row, 0-based col)
            cursor_line: int = int(row)

            # Scope chain via treesitter if available, gracefully degraded
            scope_chain = self._get_scope_chain(nvim, cursor_line)

            # Recent identifiers: words from nearby buffer lines
            recent_identifiers = self._get_nearby_identifiers(nvim, cursor_line)

            return CodeContext(
                language_id=language_id,
                file_path=file_path,
                scope_chain=scope_chain,
                recent_identifiers=recent_identifiers,
                cursor_line=cursor_line,
            )
        except Exception:
            log.debug("NeovimBridge: get_context failed", exc_info=True)
            # Invalidate connection — will reconnect on next call
            self._nvim = None
            return None

    def get_symbols(self) -> dict[str, int]:
        if self._nvim is None and not self.connect():
            return {}
        try:
            nvim = self._nvim  # type: ignore[assignment]
            lua_code = r"""
local params = { textDocument = vim.lsp.util.make_text_document_params() }
local results_by_client = vim.lsp.buf_request_sync(0, 'textDocument/documentSymbol', params, 1000)
local symbols = {}
if results_by_client then
    for _, res in pairs(results_by_client) do
        if res.result then
            local function traverse(items)
                for _, item in ipairs(items) do
                    local line = 1
                    if item.selectionRange then
                        line = item.selectionRange.start.line + 1
                    elseif item.location and item.location.range then
                        line = item.location.range.start.line + 1
                    elseif item.range then
                        line = item.range.start.line + 1
                    end
                    symbols[item.name] = line
                    if item.children then traverse(item.children) end
                end
            end
            traverse(res.result)
        end
    end
end
return symbols
"""
            result = nvim.exec_lua(lua_code)
            if isinstance(result, dict):
                return {str(k): int(v) for k, v in result.items()}
            return {}
        except Exception:
            log.debug("NeovimBridge: get_symbols failed", exc_info=True)
            self._nvim = None
            return {}

    def apply_motion(self, kind: str, payload: object) -> bool:
        if self._nvim is None and not self.connect():
            return False
        try:
            nvim = self._nvim  # type: ignore[assignment]
            if kind == "goto_line":
                nvim.current.window.cursor = (int(payload), 0)
                return True
            elif kind == "search":
                nvim.command(f"/\\V{payload}")
                return True
            return False
        except Exception:
            log.debug("NeovimBridge: apply_motion failed", exc_info=True)
            self._nvim = None
            return False

    def _get_scope_chain(self, nvim: object, cursor_line: int) -> list[str]:
        """Extract scope chain using Neovim's treesitter or LSP hover, degraded to empty list."""
        try:
            # Use a Lua snippet to query treesitter for containing nodes
            lua_code = r"""
local ok, ts = pcall(require, 'nvim-treesitter.ts_utils')
if not ok then return {} end
local node = ts.get_node_at_cursor()
if not node then return {} end
local scopes = {}
local parent = node:parent()
while parent do
    local ntype = parent:type()
    if ntype == 'function_definition' or ntype == 'function_declaration'
        or ntype == 'method_definition' or ntype == 'class_definition'
        or ntype == 'class_declaration' or ntype == 'impl_item'
        or ntype == 'function_item' then
        local start_row = parent:start()
        local line = vim.api.nvim_buf_get_lines(0, start_row, start_row + 1, false)[1] or ''
        local trimmed = vim.trim(line)
        if #trimmed > 0 and #trimmed < 120 then
            table.insert(scopes, 1, trimmed)
        end
    end
    parent = parent:parent()
end
return scopes
"""
            result = nvim.exec_lua(lua_code)  # type: ignore[attr-defined]
            if isinstance(result, list):
                # Limit to 4 scope levels to keep the prompt terse
                return [str(s) for s in result[:4]]
        except Exception:
            pass
        return []

    def _get_nearby_identifiers(self, nvim: object, cursor_line: int, window: int = 50) -> list[str]:
        """Extract unique identifier-like tokens from the buffer window around the cursor."""
        import re

        try:
            buf = nvim.current.buffer  # type: ignore[attr-defined]
            line_count = len(buf)
            start = max(0, cursor_line - window - 1)
            end = min(line_count, cursor_line + window)
            lines: list[str] = buf[start:end]

            # Extract identifiers: sequences of word chars with at least one letter,
            # length ≥ 3 and ≤ 40, excluding pure numbers.
            token_pattern = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]{2,39})\b')
            seen: dict[str, int] = {}
            for line in lines:
                for tok in token_pattern.findall(line):
                    seen[tok] = seen.get(tok, 0) + 1

            # Sort by frequency descending, return top 20
            ranked = sorted(seen.items(), key=lambda kv: -kv[1])
            return [tok for tok, _ in ranked[:20]]
        except Exception:
            log.debug("NeovimBridge: identifier extraction failed", exc_info=True)
            return []


class VSCodeBridge:
    """Bridge that reads context written by the YazSes VS Code extension.

    The extension writes a JSON file to the shared cache directory whenever
    the cursor moves (debounced to 200 ms). This bridge reads that file
    synchronously — no IPC required. Returns None if the file is absent or
    older than *_STALE_SECONDS*.
    """

    _CONTEXT_FILENAME = "vscode-context.json"
    _STALE_SECONDS = 5.0

    def __init__(self) -> None:
        import platformdirs

        self._context_file = (
            Path(platformdirs.user_cache_dir("yazses")) / self._CONTEXT_FILENAME
        )

    def connect(self) -> bool:
        return self._context_file.exists()

    def get_context(self) -> CodeContext | None:
        import json
        import time

        if not self._context_file.exists():
            return None

        try:
            age = time.time() - self._context_file.stat().st_mtime
        except OSError:
            return None

        if age > self._STALE_SECONDS:
            log.debug(
                "VSCodeBridge: context file is stale (%.1f s > %.0f s); ignoring",
                age,
                self._STALE_SECONDS,
            )
            return None

        try:
            data = json.loads(self._context_file.read_text(encoding="utf-8"))
            return CodeContext(
                language_id=data.get("languageId", "plaintext"),
                file_path=data.get("filePath", ""),
                scope_chain=data.get("scopeChain", []),
                recent_identifiers=data.get("recentIdentifiers", []),
                cursor_line=data.get("cursorLine", 0),
            )
        except Exception:
            log.debug("VSCodeBridge: failed to parse context file", exc_info=True)
            return None

    def get_symbols(self) -> dict[str, int]:
        return {}

    def apply_motion(self, kind: str, payload: object) -> bool:
        return False


class LspContextProvider:
    """Provides code context for transcription by querying the active editor.

    Wraps the editor bridge in a thread-based timeout so the transcription
    pipeline is never stalled beyond `timeout_ms` milliseconds.
    """

    def __init__(self, editor: str = "auto") -> None:
        self._bridge: EditorBridge = self._build_bridge(editor)
        self._warned_no_bridge: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_context(self, timeout_ms: int = 50) -> CodeContext | None:
        """Return the current editor context, or None if unavailable / too slow.

        The call completes within `timeout_ms` milliseconds regardless of editor
        responsiveness — the bridge is run on a daemon thread that is abandoned
        (not killed) if the deadline is exceeded.
        """
        result: list[CodeContext | None] = [None]
        exc: list[BaseException | None] = [None]

        def _run() -> None:
            try:
                result[0] = self._bridge.get_context()
            except Exception as e:  # noqa: BLE001
                exc[0] = e

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=timeout_ms / 1000.0)

        if t.is_alive():
            log.debug(
                "LspContextProvider: bridge timed out after %d ms — proceeding without context",
                timeout_ms,
            )
            return None

        if exc[0] is not None:
            log.debug("LspContextProvider: bridge raised %s", exc[0])
            return None

        return result[0]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_bridge(self, editor: str) -> EditorBridge:
        if editor == "neovim":
            socket_path = os.environ.get("NVIM", "")
            bridge: EditorBridge = NeovimBridge(socket_path)
            if not bridge.connect():  # type: ignore[attr-defined]
                log.info(
                    "LspContextProvider: NeovimBridge requested but could not connect "
                    "(NVIM=%r). Context injection disabled.",
                    socket_path,
                )
                return NullBridge()
            return bridge

        if editor == "vscode":
            bridge = VSCodeBridge()
            if not bridge.connect():
                log.info(
                    "LspContextProvider: VSCodeBridge requested but context file not found. "
                    "Install the YazSes VS Code extension. Context injection disabled."
                )
                return NullBridge()
            return bridge

        if editor == "auto":
            nvim_socket = os.environ.get("NVIM", "")
            if nvim_socket:
                bridge = NeovimBridge(nvim_socket)
                if bridge.connect():  # type: ignore[attr-defined]
                    log.info(
                        "LspContextProvider: connected to Neovim at %s",
                        nvim_socket,
                    )
                    return bridge
                log.debug(
                    "LspContextProvider: NVIM=%r set but connection failed; trying VS Code",
                    nvim_socket,
                )

            vscode_bridge = VSCodeBridge()
            if vscode_bridge.connect():
                log.info("LspContextProvider: using VS Code context file")
                return vscode_bridge

            log.info(
                "LspContextProvider: no supported editor detected. "
                "Context injection disabled (set $NVIM or install the VS Code extension)."
            )
            return NullBridge()

        # Unknown editor value — warn and degrade gracefully
        log.warning(
            "LspContextProvider: unknown editor %r — falling back to NullBridge",
            editor,
        )
        return NullBridge()
