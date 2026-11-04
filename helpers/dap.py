from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import re
import time
import uuid

from .protocol import Peer, ProtocolError
from .setup import DATA
from .workspace import project_file


class DebugSession:
    def __init__(self, root, owner, target, python, node, adapter=None, environment=None):
        self.root, self.owner, self.target = Path(root), owner, target
        self.python, self.node = python, node
        self.adapter = adapter
        self.environment = environment or {}
        self.id = uuid.uuid4().hex
        self.state = "starting"
        self.epoch = 0
        self.stop = {}
        self.output = ""
        self.output_truncated = False
        self.breakpoints = {}
        self.capabilities = {}
        self.frames, self.references = set(), set()
        self.initialized = asyncio.Event()
        self.changed = asyncio.Event()
        self.peer = Peer("dap", self._event, self._reverse)
        self.active = self.peer
        self.children = []
        self.port = None
        self.last_used = time.monotonic()
        self.control_lock = asyncio.Lock()

    async def _event(self, name, body):
        if name == "initialized":
            self.initialized.set()
        elif name == "stopped":
            self.state = "stopped"
            self.epoch += 1
            self.frames.clear()
            self.references.clear()
            self.stop = body
        elif name == "continued":
            self._resumed()
        elif name in ("terminated", "exited"):
            self.state = "terminated"
            self.frames.clear()
            self.references.clear()
        elif name == "output":
            self.output += str(body.get("output", ""))
            if len(self.output) > 32768:
                self.output = self.output[-32768:]
                self.output_truncated = True
        elif name == "breakpoint":
            bp = body.get("breakpoint", {})
            for values in self.breakpoints.values():
                for item in values:
                    if item.get("id") == bp.get("id"):
                        item.update(bp)
        self.changed.set()

    def _resumed(self):
        self.state = "running"
        self.frames.clear()
        self.references.clear()

    async def _initialize(self, peer):
        return await peer.request("initialize", {"clientID": "agent-zero", "adapterID": self.target["type"],
            "pathFormat": "path", "linesStartAt1": True, "columnsStartAt1": True,
            "supportsVariablePaging": True, "supportsRunInTerminalRequest": False,
            "supportsStartDebuggingRequest": self.target["type"] == "node"})

    async def _configure(self, peer, initialized, arguments):
        launch = asyncio.create_task(peer.request("launch", arguments, timeout=30))
        try:
            await asyncio.wait_for(initialized.wait(), 15)
            for path, lines in self._requested_breakpoints.items():
                result = await peer.request("setBreakpoints", {"source": {"path": path},
                                                              "breakpoints": [{"line": n} for n in lines]})
                self.breakpoints[path] = result.get("breakpoints", [])
            if self.capabilities.get("exceptionBreakpointFilters"):
                await peer.request("setExceptionBreakpoints", {"filters": []})
            if self.capabilities.get("supportsConfigurationDoneRequest"):
                await peer.request("configurationDone", {})
            await launch
        except BaseException:
            launch.cancel()
            await asyncio.gather(launch, return_exceptions=True)
            raise

    async def _reverse(self, command, args):
        # vscode-js-debug's standalone server bootstraps its one owned Node target
        # through a second connection. Never accept executable launch configuration.
        if command != "startDebugging" or self.target["type"] != "node" or self.children:
            raise ProtocolError("Reverse request is unsupported")
        config = args.get("configuration", {})
        if set(config) - {"type", "name", "__pendingTargetId"} or not isinstance(config.get("__pendingTargetId"), str):
            raise ProtocolError("Only the owned Node target bootstrap is allowed")
        if config.get("type") not in ("node", "pwa-node") or args.get("request") not in ("launch", "attach"):
            raise ProtocolError("Unsupported target bootstrap")
        initialized = asyncio.Event()

        async def event(name, body):
            if name == "initialized":
                initialized.set()
            else:
                await self._event(name, body)

        child = Peer("dap", event)
        self.children.append(child)
        try:
            await child.connect("127.0.0.1", self.port)
            self.capabilities = await self._initialize(child)
            self.active = child
            await self._configure(child, initialized, config)
            return {}
        except BaseException:
            await child.close()
            raise

    async def launch(self, breakpoints=None):
        program = project_file(self.root, self.target["program"])
        self._requested_breakpoints = {}
        for item in breakpoints or []:
            path = project_file(self.root, item["path"])
            lines = item.get("lines", [])
            if not isinstance(lines, list) or len(lines) > 100 or any(type(n) is not int or n < 1 for n in lines):
                raise ValueError("Breakpoints require up to 100 positive line numbers")
            self._requested_breakpoints[str(path)] = lines
        env = os.environ.copy()
        env.pop("NODE_OPTIONS", None)
        env.pop("PYTHONSTARTUP", None)
        env["PYTHONPATH"] = str(DATA / "tools/python")
        env["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"
        arguments = {"program": str(program), "cwd": str(self.root), "args": self.target.get("args", []),
                     "stopOnEntry": self.target.get("stop_on_entry", False), "console": "internalConsole",
                     "env": self.environment}
        try:
            if self.target["type"] == "python":
                await self.peer.start([self.python, "-m", "debugpy.adapter"], self.root, env)
                arguments.update(type="python", python=self.python, justMyCode=False, subProcess=False)
            elif self.target["type"] == "node":
                await self.peer.start([self.node, str(DATA / "tools/js-debug/src/dapDebugServer.js"), "0", "127.0.0.1"], self.root, env, tcp=True)
                line = await asyncio.wait_for(self.peer.proc.stdout.readline(), 10)
                match = re.fullmatch(rb"Debug server listening at 127\.0\.0\.1:(\d+)\s*", line)
                if not match:
                    raise ProtocolError("Adapter did not report an owned loopback endpoint")
                self.port = int(match[1])
                self.peer._task(self.peer._drain(self.peer.proc.stdout))
                await self.peer.connect("127.0.0.1", self.port)
                arguments.update(type="pwa-node", runtimeExecutable=self.node, autoAttachChildProcesses=False,
                                 stopOnEntry=True,
                                 sourceMaps=True, pauseForSourceMap=True, outFiles=[str(self.root / "**/*.js")],
                                 resolveSourceMapLocations=[str(self.root / "**"), "!**/node_modules/**"])
            else:
                if not self.adapter or not self.adapter.get("command"):
                    raise ValueError("No configured stdio debug adapter for this target type")
                extra = self.adapter.get("launch_arguments", {})
                if not isinstance(extra, dict) or set(extra) & {"request", "program", "cwd", "args", "env", "console", "processId", "connect", "listen"}:
                    raise ValueError("Custom adapter launch arguments cannot replace owned launch fields or configure attach")
                arguments.update(extra)
                await self.peer.start(self.adapter["command"], self.root, env)
            self.capabilities = await self._initialize(self.peer)
            self.state = "running"
            await self._configure(self.peer, self.initialized, arguments)
            if self.target["type"] == "node":
                # Hold entry until the standalone adapter has connected its target
                # and resolved source maps. Otherwise a short TS program can exit
                # before its source breakpoint is bound.
                end = time.monotonic() + 10
                while self.state == "running" and time.monotonic() < end:
                    self.changed.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self.changed.wait(), max(.01, end - time.monotonic()))
                if self.state == "stopped" and self.stop.get("reason") == "entry" and not self.target.get("stop_on_entry"):
                    end = time.monotonic() + 3
                    while any(not b.get("verified") for values in self.breakpoints.values() for b in values) and time.monotonic() < end:
                        self.changed.clear()
                        with contextlib.suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(self.changed.wait(), max(.01, end - time.monotonic()))
                    stack = await self.active.request("stackTrace", {"threadId": self.stop.get("threadId"), "levels": 1})
                    top = next(iter(stack.get("stackFrames", [])), {})
                    at_requested = top.get("line") in self._requested_breakpoints.get(top.get("source", {}).get("path"), [])
                    if not at_requested:
                        await self.control("continue", stop_generation=self.epoch, wait_seconds=1)
            return self.summary()
        except BaseException:
            await self.close()
            raise

    def summary(self):
        if self.active.failure and self.state != "terminated":
            self.state = "failed"
        return {"session_id": self.id, "state": self.state, "stop_generation": self.epoch,
                "stop": self.stop, "breakpoints": self.breakpoints, "output_truncated": self.output_truncated}

    async def control(self, action, **args):
        async with self.control_lock:
            self.last_used = time.monotonic()
            if action == "stop":
                await self.close()
                return self.summary()
            if action == "breakpoints":
                path = project_file(self.root, args["path"])
                lines = args.get("lines", [])
                if not isinstance(lines, list) or len(lines) > 100 or any(type(n) is not int or n < 1 for n in lines):
                    raise ValueError("Invalid breakpoint line numbers")
                result = await self.active.request("setBreakpoints", {"source": {"path": str(path)},
                                                "breakpoints": [{"line": line} for line in lines]})
                self.breakpoints[str(path)] = result.get("breakpoints", [])
            elif action in ("continue", "next", "step_in", "step_out", "pause"):
                if action != "pause":
                    self._require_stop(args.get("stop_generation"))
                elif self.state != "running":
                    raise ValueError("Pause requires a running session")
                thread = args.get("thread_id", self.stop.get("threadId"))
                if type(thread) is not int:
                    threads = await self.active.request("threads")
                    thread = next(iter(threads.get("threads", [])), {}).get("id")
                if type(thread) is not int:
                    raise ValueError("No live debugger thread")
                method = {"step_in": "stepIn", "step_out": "stepOut"}.get(action, action)
                previous = self.epoch
                if action != "pause":
                    self._resumed()
                await self.active.request(method, {"threadId": thread})
                end = time.monotonic() + min(float(args.get("wait_seconds", 1)), 10)
                while self.state == "running" and self.epoch == previous and time.monotonic() < end:
                    self.changed.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self.changed.wait(), max(0.01, end - time.monotonic()))
            else:
                raise ValueError("Unsupported debug control action")
            return self.summary()

    def _require_stop(self, epoch):
        if self.state != "stopped" or type(epoch) is not int or epoch != self.epoch:
            raise ValueError("Inspection/control requires the current stopped generation")

    async def inspect(self, action="status", **args):
        self.last_used = time.monotonic()
        if action == "status":
            return self.summary()
        if action == "output":
            return {"output": self.output, "truncated": self.output_truncated}
        if action == "threads":
            return await self.active.request("threads")
        self._require_stop(args.get("stop_generation"))
        epoch = self.epoch
        if action == "stack":
            result = await self.active.request("stackTrace", {"threadId": args.get("thread_id", self.stop.get("threadId")),
                                               "startFrame": max(0, int(args.get("start", 0))), "levels": 50})
            self.frames.update(f["id"] for f in result.get("stackFrames", [])[:50])
            result["stackFrames"] = result.get("stackFrames", [])[:50]
        elif action == "scopes":
            ident = args.get("frame_id")
            if ident not in self.frames:
                raise ValueError("Unknown frame handle")
            result = await self.active.request("scopes", {"frameId": ident})
            self.references.update(s["variablesReference"] for s in result.get("scopes", []))
        elif action == "variables":
            ident = args.get("variables_reference")
            if ident not in self.references or ident == 0:
                raise ValueError("Unknown variable handle")
            result = await self.active.request("variables", {"variablesReference": ident,
                                               "start": max(0, int(args.get("start", 0))), "count": 100})
            values = result.get("variables", [])
            result["truncated"] = len(values) > 100
            result["variables"] = values[:100]
            for value in result["variables"]:
                value["value"] = str(value.get("value", ""))[:2000]
                self.references.add(value.get("variablesReference", 0))
        else:
            raise ValueError("Unsupported debug inspection action")
        if self.state != "stopped" or self.epoch != epoch:
            raise ValueError("Program resumed while inspecting; request current state again")
        return {**result, "stop_generation": epoch}

    async def close(self):
        for peer in reversed(self.children + [self.peer]):
            with contextlib.suppress(Exception):
                await peer.request("disconnect", {"terminateDebuggee": True}, timeout=1)
        for peer in self.children + [self.peer]:
            await peer.close()
        self.state = "terminated"
        self.frames.clear()
        self.references.clear()
