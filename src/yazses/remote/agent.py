"""yazses-agent — lightweight remote text injection agent.

Listens on a local TCP port and accepts JSON-RPC inject(text) calls.
Has zero faster-whisper, sounddevice, or audio dependencies (ADR-001).

Usage:
    yazses-agent --listen 9875
"""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger(__name__)


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, injector) -> None:
    try:
        data = await reader.readline()
        if not data:
            return
        try:
            request = json.loads(data.decode())
        except json.JSONDecodeError as e:
            response = {"jsonrpc": "2.0", "error": {"code": -32700, "message": str(e)}, "id": None}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
            return

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        if method == "inject":
            text = params.get("text", "")
            try:
                injector.inject(text)
                response = {"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(exc)}, "id": req_id}
        elif method == "keys":
            # The remote injector has always implemented these; the protocol had no way
            # to ask for them, so every voice COMMAND ("save", "copy", "undo") was a
            # silent no-op in remote mode while dictation worked.
            keys = params.get("keys") or []
            try:
                injector.inject_key_sequence([str(k) for k in keys])
                response = {"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(exc)}, "id": req_id}
        elif method == "backspaces":
            try:
                injector.inject_backspaces(int(params.get("count") or 0))
                response = {"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(exc)}, "id": req_id}
        elif method == "ping":
            response = {"jsonrpc": "2.0", "result": {"pong": True}, "id": req_id}
        else:
            response = {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {method}"},
                "id": req_id,
            }

        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
    except Exception as exc:
        log.error("agent client handler error: %s", exc)
    finally:
        writer.close()


async def _run_server(port: int, injector) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, injector),
        host="127.0.0.1",
        port=port,
    )
    log.info("yazses-agent listening on 127.0.0.1:%d", port)
    async with server:
        await server.serve_forever()


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="YazSes remote text injection agent")
    parser.add_argument(
        "--listen",
        type=int,
        default=9875,
        metavar="PORT",
        help="Local TCP port to listen on (default: 9875)",
    )
    args = parser.parse_args()

    from yazses.remote.inject import get_remote_injector
    injector = get_remote_injector()
    log.info("yazses-agent using injector: %s", type(injector).__name__)

    try:
        asyncio.run(_run_server(args.listen, injector))
    except KeyboardInterrupt:
        log.info("yazses-agent stopped")


if __name__ == "__main__":
    main()
