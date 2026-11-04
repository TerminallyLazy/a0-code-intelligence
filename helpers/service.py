from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import json
import os
import re
from pathlib import Path
import sys
import threading
import time
import uuid

from . import access
from .dap import DebugSession
from .edits import Proposals
from .lsp import LanguageServer, LANGUAGES
from .setup import DATA
from .workspace import digest, project_file, read_text, snapshot

_module = sys.modules[__name__]
_manager = None
_manager_lock = threading.Lock()


def language_for(path, config):
    for name, spec in config.get("servers", {}).items():
        extensions = spec.get("extensions", [])
        if not isinstance(extensions, list) or any(not isinstance(v, str) or not v.startswith(".") or "/" in v for v in extensions):
            raise ValueError("Custom server extensions must be an array such as ['.rs']")
        if path.suffix in extensions:
            if spec.get("disabled"):
                raise ValueError("Language server is disabled for this file type")
            if not spec.get("command") or not spec.get("language_id"):
                raise ValueError("Custom servers require command and language_id")
            return name, spec["language_id"]
    language = LANGUAGES.get(path.suffix)
    if not language:
        raise ValueError("No language server configured for this file type")
    name = "python" if language == "python" else "typescript"
    if config.get("servers", {}).get(name, {}).get("disabled"):
        raise ValueError("Language server is disabled for this file type")
    return name, None


class Workspace:
    def __init__(self, agent, scope):
        self.agent, self.scope = agent, scope
        self.servers = {}
        self.jobs = {}
        self.reports = {}
        self.delivered = {}
        self.baselines = {}
        self.monitored = {}
        self.actions = {}
        self.debuggers = {}
        self.proposals = Proposals(scope.root, scope.owner, DATA / "recovery" / digest(scope.owner))
        self.lock = asyncio.Lock()
        self.last_used = time.monotonic()
        self.deferred = set()
        self.watcher = "code_intelligence:" + uuid.uuid4().hex
        self.closed = False
        self.closing = None
        from helpers import watchdog
        loop = asyncio.get_running_loop()

        def changed(events):
            paths = [path for path, _ in events]
            if not self.closed and not loop.is_closed():
                loop.call_soon_threadsafe(self.schedule_paths, paths)

        extensions = set(LANGUAGES) | {".json", ".toml"}
        for server in scope.config.get("servers", {}).values():
            extensions.update(server.get("extensions", []))
        watchdog.add_watchdog(self.watcher, roots=[str(scope.root)],
                             patterns=[f"**/*{suffix}" for suffix in sorted(extensions)],
                             ignore_patterns=["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/__pycache__/**", "**/.runtime/**"],
                             debounce=0.25, handler=changed)

    def schedule_paths(self, paths):
        if self.closed:
            return
        for path in paths[:100]:
            try:
                self.queue(path)
            except (ValueError, PermissionError):
                continue

    async def server(self, path):
        path = project_file(self.scope.root, str(path))
        name, language_id = language_for(path, self.scope.config)
        current = self.servers.get(name)
        if current and not current.peer.failure:
            return current
        if current:
            await current.close()
        config = self.scope.config
        tools = DATA / "tools/node_modules"
        command = ([config["node"], str(tools / "pyright/langserver.index.js"), "--stdio"] if name == "python" else
                   [config["node"], str(tools / "typescript-language-server/lib/cli.mjs"), "--stdio"])
        settings = {"python": {"pythonPath": config["python"], "analysis": {"typeCheckingMode": "basic", "diagnosticMode": "openFilesOnly"}}} if name == "python" else {}
        custom = config.get("servers", {}).get(name, {})
        if custom:
            command = custom.get("command", command)
            settings = custom.get("settings", settings)
        if not isinstance(command, list) or not command or any(not isinstance(s, str) for s in command):
            raise ValueError("Server command must be an argv array")
        if not Path(command[0]).is_absolute():
            raise ValueError("Server executable must be an absolute path")
        env = os.environ.copy()
        env.pop("NODE_OPTIONS", None)
        if len(self.servers) >= 4 and name not in self.servers:
            raise ValueError("Four active language servers reached for this workspace")
        value = LanguageServer(self.scope.root, name, command, settings, env, language_id, custom.get("initialization"))
        self.servers[name] = await value.start()
        return value

    def queue(self, path):
        if not self.scope.config.get("automatic_diagnostics", True):
            return
        access.resolve(self.agent, "code_inspect")
        path = project_file(self.scope.root, str(path), exists=False)
        self.last_used = time.monotonic()
        if path.suffix in {".json", ".toml"}:
            for server in self.servers.values():
                server.results.clear()
            for filename in list(self.monitored):
                if filename != str(path) and Path(filename).suffix not in {".json", ".toml"}:
                    self.queue(filename)
        try:
            language_for(path, self.scope.config)
        except ValueError:
            return
        key = str(path)
        if key in self.jobs:
            self.jobs[key].cancel()
        self.jobs[key] = asyncio.create_task(self._diagnose(path))

    async def _diagnose(self, path):
        try:
            async with self.lock:
                if not path.exists():
                    for server in self.servers.values():
                        if path.as_uri() in server.documents:
                            await server.peer.notify("textDocument/didClose", {"textDocument": {"uri": path.as_uri()}})
                            server.documents.pop(path.as_uri(), None)
                            server.results.pop(path.as_uri(), None)
                        await server.peer.notify("workspace/didChangeWatchedFiles", {"changes": [{"uri": path.as_uri(), "type": 3}]})
                    self.reports.pop(str(path), None)
                    self.monitored.pop(str(path), None)
                    return
                server = await self.server(path)
                await server.peer.notify("workspace/didChangeWatchedFiles", {"changes": [{"uri": path.as_uri(), "type": 2}]})
                previous = self.reports.get(str(path))
                result = await server.diagnostics(path, timeout=5)
                self.remember_documents(server)
                if previous and previous.get("status") == "current" and result.get("status") == "current":
                    # Only report a count delta; moved diagnostics are not claimed new.
                    result["previous_error_count"] = len(previous.get("diagnostics", []))
                self.reports[str(path)] = result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.reports[str(path)] = {"status": "unavailable", "path": str(path), "reason": str(exc)[:300]}

    async def drain(self, wait=0):
        access.resolve(self.agent, "code_inspect")
        active = [t for t in self.jobs.values() if not t.done()]
        if active and wait:
            await asyncio.wait(active, timeout=wait)
        self.jobs = {k: t for k, t in self.jobs.items() if not t.done()}
        results = []
        for path, report in list(self.reports.items()):
            try:
                if report.get("digest") and digest(read_text(Path(path))) != report["digest"]:
                    continue
            except (ValueError, OSError):
                continue
            stamp = digest(json.dumps(report, sort_keys=True))
            if self.delivered.get(path) != stamp:
                self.delivered[path] = stamp
                results.append(report)
        if self.jobs:
            results.append({"status": "pending", "paths": list(self.jobs)[:20]})
        return results[:20]

    async def execute(self, tool, args):
        action = args.get("action", "status")
        if tool == "code_inspect" and action == "status":
            debug_visible = False
            try:
                access.resolve(self.agent, "debug_inspect")
                debug_visible = True
            except Exception:
                pass
            return {"monitor": {"active": not self.closed and self.scope.config.get("automatic_diagnostics", True),
                                "tracked_files": len(self.monitored), "idle_seconds": self.scope.config.get("idle_seconds", 300)},
                    "servers": [{"name": name, "encoding": s.encoding, "failed": bool(s.peer.failure)} for name, s in self.servers.items()],
                    "diagnostics": list(self.reports.values())[:50], "pending": list(self.jobs),
                    "proposals": [self.proposals.public(p) for p in self.proposals.items.values()],
                    "debuggers": [s.summary() for s in self.debuggers.values()] if debug_visible else []}
        self.last_used = time.monotonic()
        if tool.startswith("debug_"):
            return await self.debug(tool, args)
        async with self.lock:
            if tool == "code_apply":
                return self.proposals.apply(str(args.get("proposal_id", "")), {s.generation for s in self.servers.values()})
            path = project_file(self.scope.root, args.get("path", ""))
            server = await self.server(path)
            if tool == "code_inspect":
                if action == "diagnostics":
                    result = await server.diagnostics(path)
                    self.remember_documents(server)
                    self.reports[str(path)] = result
                    return result
                if action not in {"definition", "references", "hover", "symbols", "workspace_symbols"}:
                    raise ValueError("Unsupported semantic query")
                result = await server.query(action, path, args.get("line", 1), args.get("column", 1), args.get("query", ""))
                self.remember_documents(server)
                if isinstance(result, list):
                    return {"items": result[:100], "truncated": len(result) > 100, "encoding": server.encoding}
                return {"result": result, "encoding": server.encoding}
            suffixes = [suffix for spec in self.scope.config.get("servers", {}).values() for suffix in spec.get("extensions", [])]
            before = snapshot(self.scope.root, suffixes)
            if action == "rename":
                name = args.get("new_name")
                if not isinstance(name, str) or not name or len(name) > 200:
                    raise ValueError("new_name is required (maximum 200 characters)")
                edit = await server.query("rename", path, args.get("line", 1), args.get("column", 1), new_name=name)
                return self.proposals.create(edit, before, server, f"Rename to {name}")
            if action == "actions":
                actions = await server.query("actions", path, args.get("line", 1), args.get("column", 1)) or []
                self.actions.clear()
                result = []
                for action_item in actions[:30]:
                    ident = uuid.uuid4().hex
                    self.actions[ident] = (action_item, before, server, time.monotonic())
                    result.append({"action_id": ident, "title": action_item.get("title"), "kind": action_item.get("kind"),
                                   "disabled": action_item.get("disabled"), "command_only": bool(action_item.get("command") and not action_item.get("edit"))})
                return {"actions": result}
            if action == "resolve_action":
                item = self.actions.get(args.get("action_id"))
                if not item:
                    raise ValueError("Unknown code action; request actions again")
                value, before, server, created = item
                if time.monotonic() - created > 120 or server.peer.failure:
                    raise ValueError("Code action expired")
                if value.get("disabled"):
                    raise ValueError("Language server disabled this action")
                provider = server.capabilities.get("codeActionProvider", {})
                if not value.get("edit") and isinstance(provider, dict) and provider.get("resolveProvider"):
                    value = await server.peer.request("codeAction/resolve", value)
                command = value.get("command")
                # TLS 6.0.3 adds a no-op follow-up command to edit-only quick fixes.
                # Its implementation executes only action.commands; never execute it.
                no_op = (server.name == "typescript" and isinstance(command, dict)
                         and command.get("command") == "_typescript.applyCodeActionCommand"
                         and isinstance(command.get("arguments"), list) and len(command["arguments"]) == 1
                         and isinstance(command["arguments"][0], dict)
                         and isinstance(command["arguments"][0].get("action"), dict)
                         and not command["arguments"][0]["action"].get("commands"))
                if (command and not no_op) or not value.get("edit"):
                    raise ValueError("Command-based code actions are unsupported; no command was executed")
                return self.proposals.create(value["edit"], before, server, value.get("title", "Code action"))
            raise ValueError("Unsupported proposal action")

    async def debug(self, tool, args):
        if tool == "debug_launch":
            targets = self.scope.config.get("debug_targets", {})
            target = targets.get(args.get("target"))
            if not isinstance(target, dict):
                raise ValueError("Select a configured debug target")
            if set(target) - {"type", "program", "args", "stop_on_entry", "env_secrets"}:
                raise ValueError("Unsupported debug-target field")
            if not isinstance(target.get("args", []), list) or any(not isinstance(v, str) for v in target.get("args", [])):
                raise ValueError("Target args must be a string array")
            if any(s.state not in ("failed", "terminated") for s in self.debuggers.values()):
                raise ValueError("Stop the existing debug session before launching another")
            references = target.get("env_secrets", {})
            if not isinstance(references, dict) or any(
                    not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                    or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                    for key, name in references.items()):
                raise ValueError("env_secrets must map environment variable names to secret names")
            from helpers.secrets import get_secrets_manager
            secrets = get_secrets_manager(self.agent.context).load_secrets() if references else {}
            if any(name.upper() not in secrets for name in references.values()):
                raise ValueError("A configured debug environment secret is missing")
            environment = {key: secrets[name.upper()] for key, name in references.items()}
            value = DebugSession(self.scope.root, self.scope.owner, target, self.scope.config["python"], self.scope.config["node"],
                                 self.scope.config.get("adapters", {}).get(target.get("type")), environment)
            self.debuggers.clear()
            self.debuggers[value.id] = value
            return await value.launch(args.get("breakpoints", []))
        value = self.debuggers.get(args.get("session_id"))
        if not value or value.owner != self.scope.owner:
            raise PermissionError("Debug session is not owned by this context")
        options = {k: v for k, v in args.items() if k not in {"action", "session_id"}}
        if tool == "debug_control":
            return await value.control(args.get("action"), **options)
        return await value.inspect(args.get("action", "status"), **options)

    async def close(self):
        if self.closing is None:
            self.closing = asyncio.create_task(self._close_resources())
        await asyncio.shield(self.closing)

    async def _close_resources(self):
        self.closed = True
        from helpers.watchdog import remove_watchdog
        remove_watchdog(self.watcher)
        for task in self.jobs.values():
            task.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in self.debuggers.values()), return_exceptions=True)
        await asyncio.gather(*(s.close() for s in self.servers.values()), return_exceptions=True)

    def remember_documents(self, server):
        for doc in server.documents.values():
            self.monitored.pop(doc["path"], None)
            self.monitored[doc["path"]] = doc.get("stat")
        while len(self.monitored) > 200:
            self.monitored.pop(next(iter(self.monitored)))

    async def suspend_idle_servers(self, now=None):
        idle = float(self.scope.config.get("idle_seconds", 300))
        if idle == 0 or self.lock.locked() or any(not t.done() for t in self.jobs.values()):
            return
        idle = max(30, min(3600, idle))
        now = time.monotonic() if now is None else now
        async with self.lock:
            for name, server in list(self.servers.items()):
                if now - server.last_used > idle:
                    self.remember_documents(server)
                    await server.close()
                    self.servers.pop(name, None)
                    self.actions = {key: value for key, value in self.actions.items() if value[2] is not server}

    def reconcile_open_documents(self):
        # Bind mounts can drop OS file events. Reconcile only bounded open files;
        # do not recursively scan the project on every model/tool turn.
        for server in self.servers.values():
            self.remember_documents(server)
        for path, stat in list(self.monitored.items()):
            if path in self.jobs and not self.jobs[path].done():
                continue
            try:
                info = Path(path).stat()
                changed = (info.st_mtime_ns, info.st_size) != stat
            except FileNotFoundError:
                changed = True
            if changed:
                self.queue(path)


class Manager:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.workspaces = {}
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="code-intelligence", daemon=True)
        self.thread.start()
        self.ready.wait(5)
        atexit.register(self.close)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.reaper = self.loop.create_task(self._reap())
        self.ready.set()
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    async def _reap(self):
        while True:
            await asyncio.sleep(1)
            if sys.modules.get(__name__) is not _module:
                await self._close()
                self.loop.call_soon(self.loop.stop)
                return
            for key, workspace in list(self.workspaces.items()):
                valid = True
                try:
                    tool = "debug_inspect" if workspace.debuggers and not workspace.servers else "code_inspect"
                    scope = access.resolve(workspace.agent, tool)
                    if workspace.debuggers:
                        access.resolve(workspace.agent, "debug_launch")
                        access.resolve(workspace.agent, "debug_inspect")
                    valid = scope.fingerprint == workspace.scope.fingerprint and scope.owner == workspace.scope.owner
                    from agent import AgentContext
                    valid = valid and AgentContext.get(workspace.agent.context.id) is workspace.agent.context
                except Exception:
                    valid = False
                if not valid:
                    await workspace.close()
                    self.workspaces.pop(key, None)
                else:
                    with contextlib.suppress(Exception):
                        workspace.reconcile_open_documents()
                        await workspace.suspend_idle_servers()
                        # Debug sessions retain their separate idle cleanup; only
                        # language-server idling preserves project monitoring.
                        idle = max(30, min(3600, float(workspace.scope.config.get("idle_seconds", 300)) or 300))
                        if workspace.debuggers and time.monotonic() - workspace.last_used > idle:
                            await asyncio.gather(*(s.close() for s in workspace.debuggers.values()), return_exceptions=True)
                            workspace.debuggers.clear()

    async def workspace(self, agent, scope):
        key = (scope.owner, scope.fingerprint)
        if key not in self.workspaces:
            if len(self.workspaces) >= 4:
                raise ValueError("Four active plugin workspaces reached; close an idle workspace")
            self.workspaces[key] = Workspace(agent, scope)
        return self.workspaces[key]

    async def _dispatch(self, agent, tool, args, scope):
        workspace = await self.workspace(agent, scope)
        if tool == "_queue":
            workspace.queue(args["path"])
            return {}
        if tool == "_drain":
            return await workspace.drain(args.get("wait", 0))
        return await workspace.execute(tool, args)

    async def call(self, agent, tool, args, scope):
        future = asyncio.run_coroutine_threadsafe(self._dispatch(agent, tool, args, scope), self.loop)
        return await asyncio.wrap_future(future)

    async def _close(self):
        await asyncio.gather(*(w.close() for w in self.workspaces.values()), return_exceptions=True)
        self.workspaces.clear()

    def close(self):
        if not self.loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self._close(), self.loop)
        with contextlib.suppress(Exception):
            future.result(timeout=10)
        self.loop.call_soon_threadsafe(self.reaper.cancel)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


def manager():
    global _manager
    with _manager_lock:
        if _manager is None or not _manager.loop.is_running():
            _manager = Manager()
        return _manager


async def dispatch(agent, tool, args):
    scope = access.resolve(agent, tool)
    result = await manager().call(agent, tool, args, scope)
    if tool == "code_apply" and result.get("status") == "applied":
        from helpers.extension import call_extensions_async
        await call_extensions_async("workdir_file_mutation_after", agent=agent,
                                    data={"action": "edit", "paths": result["paths"]})
        for path in result["paths"]:
            await manager().call(agent, "_queue", {"path": path}, scope)
    return access.masked(agent, result)


async def queue(agent, path):
    scope = access.resolve(agent, "code_inspect")
    return await manager().call(agent, "_queue", {"path": path}, scope)


async def drain(agent, wait=0):
    scope = access.resolve(agent, "code_inspect")
    return access.masked(agent, await manager().call(agent, "_drain", {"wait": wait}, scope))


def shutdown():
    global _manager
    with _manager_lock:
        if _manager:
            _manager.close()
            _manager = None
