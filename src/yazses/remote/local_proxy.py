"""Local TCP proxy — bridges the daemon's InjectorBackend to the SSH-tunnelled agent.

The daemon (local machine) sends inject(text) JSON-RPC calls to localhost:9875.
SSH forwards port 9875 to the remote machine where yazses-agent is listening.
This means text flows: daemon → local_proxy → SSH tunnel → remote agent → remote injector.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


class RemoteInjectorProxy:
    """InjectorBackend-compatible class that forwards calls over TCP to the agent.

    Used by the daemon when in REMOTE_ACTIVE mode instead of the local injector.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9875, timeout: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    def inject(self, text: str) -> None:
        if not text:
            return
        asyncio.run(self._send_rpc("inject", {"text": text}))

    def inject_backspaces(self, count: int) -> None:
        """Forward a backspace run to the agent.

        These two were `pass  # Not forwarded in v0.3.0`, which made every voice COMMAND
        a silent no-op in remote mode: `commands/dispatch.py` routes everything that is
        not DICTATE through `inject_key_sequence`, so "save", "copy" and "undo" reached
        this method and stopped. Dictation worked, so nothing looked broken -- the user
        says "save", is watching the *remote* screen, and nothing happens or is said.

        The remote injector on the other end has implemented both all along
        (`remote/inject.py`); only the protocol had no way to ask.
        """
        if count <= 0:
            return
        asyncio.run(self._send_rpc("backspaces", {"count": int(count)}))

    def inject_key_sequence(self, keys: list[str]) -> None:
        """Forward a key sequence to the agent. See :meth:`inject_backspaces`.

        An older agent answers "Method not found", which `_send_rpc` already logs and
        survives -- so a new client against an old remote degrades to today's behaviour
        rather than failing.
        """
        if not keys:
            return
        asyncio.run(self._send_rpc("keys", {"keys": [str(k) for k in keys]}))

    async def _send_rpc(self, method: str, params: dict[str, Any]) -> Any:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
            request = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1})
            writer.write((request + "\n").encode())
            await writer.drain()
            data = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            if data:
                response = json.loads(data.decode())
                if "error" in response:
                    log.warning("remote agent error: %s", response["error"])
                return response.get("result")
        except asyncio.TimeoutError:
            log.warning("remote agent timeout after %.1fs", self._timeout)
        except (ConnectionRefusedError, OSError) as exc:
            log.warning("remote agent unreachable: %s", exc)
        return None

    def is_reachable(self) -> bool:
        """Check if the remote agent is reachable."""
        import socket
        try:
            with socket.create_connection((self._host, self._port), timeout=2.0):
                return True
        except (OSError, ConnectionRefusedError):
            return False
