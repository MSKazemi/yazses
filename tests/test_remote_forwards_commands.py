"""In remote mode every voice *command* was a silent no-op.

`RemoteInjectorProxy` is the InjectorBackend the daemon uses while forwarding to an SSH
host. Two of its three methods were stubs:

    def inject_backspaces(self, count): pass  # Not forwarded in v0.3.0
    def inject_key_sequence(self, keys): pass  # Not forwarded in v0.3.0

`commands/dispatch.py` routes everything that is **not** DICTATE through
`inject_key_sequence`. So in remote mode "save", "copy", "paste" and "undo" reached that
`pass` and stopped — while dictation kept working, which is what made it invisible. The
user says "save", is watching the *remote* screen, and nothing happens and nothing is said.

It was never a missing capability. `remote/inject.py` — the injector running on the remote
host — has implemented `inject_backspaces` and `inject_key_sequence` all along. The agent's
JSON-RPC dispatch simply had no method for them, so there was no way to ask.

## Version skew

An older agent answers ``Method not found`` to the new methods, which `_send_rpc` already
logs and survives. A new client against an old remote therefore degrades to exactly
today's behaviour rather than failing — which is why this needed no protocol version.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from yazses.remote.agent import _handle_client
from yazses.remote.local_proxy import RemoteInjectorProxy


class _Injector:
    """Stands in for the remote host's real injector."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def inject(self, text: str) -> None:
        self.calls.append(("inject", text))

    def inject_backspaces(self, count: int) -> None:
        self.calls.append(("backspaces", count))

    def inject_key_sequence(self, keys) -> None:
        self.calls.append(("keys", list(keys)))


def _serve_in_thread(handler):
    """Run `handler` as a loopback server on an EPHEMERAL port; return that port.

    Port 0, not a fixed number: a fixed one collided between tests here as soon as there
    was more than one, and would also collide with whatever the developer happens to be
    running.
    """
    ready: list = []
    started = threading.Event()

    async def _serve():
        server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
        ready.append(server.sockets[0].getsockname()[1])
        started.set()
        async with server:
            await asyncio.sleep(5)

    threading.Thread(target=lambda: asyncio.run(_serve()), daemon=True).start()
    assert started.wait(3), "the test server never started"
    time.sleep(0.05)
    return ready[0]


@pytest.fixture
def agent():
    """A real agent on a real loopback socket, with a fake injector behind it."""
    injector = _Injector()
    port = _serve_in_thread(lambda r, w: _handle_client(r, w, injector))
    yield injector, RemoteInjectorProxy(port=port)


def test_dictation_still_crosses_the_tunnel(agent) -> None:
    """It always did; a regression here would be worse than the bug."""
    injector, proxy = agent
    proxy.inject("hello world")
    time.sleep(0.2)
    assert ("inject", "hello world") in injector.calls


def test_a_voice_command_reaches_the_remote_host(agent) -> None:
    """The defect: this used to stop at a `pass`."""
    injector, proxy = agent
    proxy.inject_key_sequence(["ctrl+s"])
    time.sleep(0.2)
    assert ("keys", ["ctrl+s"]) in injector.calls, (
        "a voice command was silently dropped in remote mode"
    )


def test_backspaces_reach_the_remote_host(agent) -> None:
    injector, proxy = agent
    proxy.inject_backspaces(3)
    time.sleep(0.2)
    assert ("backspaces", 3) in injector.calls


@pytest.mark.parametrize("call,arg", [("inject_key_sequence", []), ("inject_backspaces", 0)])
def test_an_empty_request_never_reaches_the_wire(agent, call, arg) -> None:
    """A round trip per empty command would be latency on the dictation hot path."""
    injector, proxy = agent
    getattr(proxy, call)(arg)
    time.sleep(0.2)
    assert injector.calls == []


def test_an_old_agent_is_survived_not_crashed() -> None:
    """Version skew: the remote may predate these methods.

    It answers "Method not found", which `_send_rpc` logs and swallows, so the client
    degrades to the old behaviour instead of raising into the dictation path.
    """
    async def _old_handle(reader, writer):
        import json

        await reader.readline()
        writer.write(
            (json.dumps({"jsonrpc": "2.0",
                         "error": {"code": -32601, "message": "Method not found: keys"},
                         "id": 1}) + "\n").encode()
        )
        await writer.drain()
        writer.close()

    port = _serve_in_thread(_old_handle)
    RemoteInjectorProxy(port=port).inject_key_sequence(["ctrl+s"])  # must not raise


def test_an_unreachable_agent_does_not_raise() -> None:
    """Nothing is listening: the daemon must not take an exception on the hot path."""
    proxy = RemoteInjectorProxy(port=9984, timeout=0.5)
    proxy.inject_key_sequence(["ctrl+s"])
    proxy.inject_backspaces(2)
    proxy.inject("text")
