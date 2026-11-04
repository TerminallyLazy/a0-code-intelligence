"""Bounded framing shared by LSP and DAP; their message semantics stay separate."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import sys
from typing import Callable

MAX_FRAME = 8 * 1024 * 1024


class ProtocolError(RuntimeError):
    pass


async def read_frame(reader):
    try:
        header = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.LimitOverrunError, asyncio.IncompleteReadError) as exc:
        raise ProtocolError("Protocol stream ended or header exceeded its limit") from exc
    lengths = []
    for line in header[:-4].split(b"\r\n"):
        key, sep, value = line.partition(b":")
        if not sep:
            raise ProtocolError("Malformed protocol header")
        if key.lower() == b"content-length":
            try:
                lengths.append(int(value.strip()))
            except ValueError as exc:
                raise ProtocolError("Invalid frame length") from exc
    if len(lengths) != 1 or not 0 < lengths[0] <= MAX_FRAME:
        raise ProtocolError("Missing, duplicate or oversized frame length")
    try:
        result = json.loads(await reader.readexactly(lengths[0]))
    except (ValueError, asyncio.IncompleteReadError) as exc:
        raise ProtocolError("Invalid JSON frame") from exc
    if not isinstance(result, dict):
        raise ProtocolError("Protocol message must be an object")
    return result


class Peer:
    def __init__(self, kind: str, on_event: Callable | None = None, on_request: Callable | None = None):
        self.kind = kind
        self.on_event = on_event
        self.on_request = on_request
        self.seq = 0
        self.pending = {}
        self.tasks = set()
        self.proc = None
        self.writer = None
        self.lease = None
        self.closed = False
        self.closing = None
        self.failure = None
        self.lock = asyncio.Lock()

    async def start(self, command, cwd, env=None, tcp=False):
        read_fd, self.lease = os.pipe()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("guard.py")), str(read_fd), *command,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=str(cwd), env=env,
                pass_fds=(read_fd,), limit=16384,
            )
        except BaseException:
            os.close(self.lease)
            self.lease = None
            raise
        finally:
            os.close(read_fd)
        self._task(self._drain(self.proc.stderr))
        if not tcp:
            self.reader, self.writer = self.proc.stdout, self.proc.stdin
            self._task(self._read())
        return self

    async def connect(self, host, port):
        self.reader, self.writer = await asyncio.open_connection(host, port, limit=16384)
        self._task(self._read())

    def _task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _drain(self, stream):
        # Drain without retaining protocol stderr, which may contain source/secrets.
        while await stream.read(4096):
            pass

    async def send(self, data):
        if self.closed or self.failure or self.writer is None:
            raise ProtocolError(self.failure or "Protocol is closed")
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_FRAME:
            raise ProtocolError("Outgoing frame exceeds limit")
        async with self.lock:
            self.writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            await self.writer.drain()

    async def request(self, method, params=None, timeout=15):
        self.seq += 1
        ident = self.seq
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        message = ({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}}
                   if self.kind == "lsp" else
                   {"seq": ident, "type": "request", "command": method, "arguments": params or {}})
        try:
            await self.send(message)
            return await asyncio.wait_for(future, timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if self.kind == "lsp":
                with contextlib.suppress(Exception):
                    await self.notify("$/cancelRequest", {"id": ident})
            raise
        finally:
            self.pending.pop(ident, None)

    async def notify(self, method, params):
        await self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _serve_request(self, message):
        try:
            if self.kind == "lsp":
                value = await self.on_request(message["method"], message.get("params", {})) if self.on_request else None
                await self.send({"jsonrpc": "2.0", "id": message["id"], "result": value})
            else:
                value = None
                error = None
                try:
                    if not self.on_request:
                        raise ProtocolError("Reverse requests are not supported by this client")
                    value = await self.on_request(message["command"], message.get("arguments", {}))
                except Exception as exc:
                    error = str(exc)[:300]
                self.seq += 1
                await self.send({"seq": self.seq, "type": "response", "request_seq": message["seq"],
                                 "command": message["command"], "success": error is None,
                                 "body": value or {}, **({"message": error} if error else {})})
        except Exception:
            if self.kind == "lsp":
                with contextlib.suppress(Exception):
                    await self.send({"jsonrpc": "2.0", "id": message["id"],
                                     "error": {"code": -32601, "message": "Unsupported server request"}})

    async def _read(self):
        try:
            while True:
                message = await read_frame(self.reader)
                is_request = ("method" in message and "id" in message) if self.kind == "lsp" else message.get("type") == "request"
                if is_request:
                    self._task(self._serve_request(message))
                    continue
                ident = message.get("id") if self.kind == "lsp" else message.get("request_seq")
                if ident in self.pending:
                    future = self.pending[ident]
                    if not future.done():
                        error = message.get("error") if self.kind == "lsp" else (None if message.get("success") else message.get("message", "DAP request failed"))
                        if error:
                            future.set_exception(ProtocolError(str(error)[:500]))
                        else:
                            future.set_result(message.get("result") if self.kind == "lsp" else message.get("body", {}))
                elif self.on_event:
                    await self.on_event(message.get("method") if self.kind == "lsp" else message.get("event"),
                                        message.get("params", {}) if self.kind == "lsp" else message.get("body", {}))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.failure = f"{self.kind.upper()} connection ended: {type(exc).__name__}"
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ProtocolError(self.failure or "Connection closed"))

    async def close(self):
        if self.closing is None:
            self.closing = asyncio.create_task(self._finish_close())
        await asyncio.shield(self.closing)

    async def _finish_close(self):
        self.closed = True
        if self.writer:
            self.writer.close()
            with contextlib.suppress(Exception):
                await self.writer.wait_closed()
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None
        if self.proc:
            if self.proc.stdin:
                self.proc.stdin.close()
                with contextlib.suppress(Exception):
                    await self.proc.stdin.wait_closed()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), 3)
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=0.2)
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.sleep(0)
