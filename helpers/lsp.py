from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
import time

from .protocol import Peer, ProtocolError
from .workspace import digest, project_file, read_text

LANGUAGES = {".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "typescriptreact",
             ".mts": "typescript", ".cts": "typescript", ".js": "javascript", ".jsx": "javascriptreact",
             ".mjs": "javascript", ".cjs": "javascript"}


class LanguageServer:
    def __init__(self, root, name, command, settings=None, env=None, language_id=None, initialization=None):
        self.root, self.name, self.command = Path(root), name, command
        self.settings, self.env = settings or {}, env
        self.language_id = language_id
        self.initialization = initialization or {}
        self.direct_diagnostics = None
        self.peer = Peer("lsp", self._event, self._request)
        self.documents = {}
        self.results = {}
        self.changed = asyncio.Event()
        self.capabilities = {}
        self.encoding = "utf-16"
        self.generation = time.monotonic_ns()
        self.last_used = time.monotonic()
        self.sync_lock = asyncio.Lock()

    async def start(self):
        await self.peer.start(self.command, self.root, self.env)
        try:
            reply = await self.peer.request("initialize", {
                "processId": None, "clientInfo": {"name": "Agent Zero Code Intelligence", "version": "0.2.2"},
                "rootUri": self.root.as_uri(), "rootPath": str(self.root),
                "workspaceFolders": [{"uri": self.root.as_uri(), "name": self.root.name}],
                "capabilities": {
                    "general": {"positionEncodings": ["utf-16", "utf-8"]},
                    "workspace": {"configuration": True, "workspaceFolders": True, "applyEdit": False,
                                  "workspaceEdit": {"documentChanges": True, "resourceOperations": []}},
                    "textDocument": {"synchronization": {"didSave": True}, "publishDiagnostics": {"versionSupport": True},
                                     "diagnostic": {"dynamicRegistration": False},
                                     "rename": {"prepareSupport": True},
                                     "codeAction": {"codeActionLiteralSupport": {"codeActionKind": {"valueSet": ["quickfix", "refactor", "source.organizeImports"]}},
                                                    "resolveSupport": {"properties": ["edit"]}}}},
                "initializationOptions": {"hostInfo": "agent-zero", **self.initialization},
            }, timeout=30)
            self.capabilities = reply.get("capabilities", {})
            self.encoding = self.capabilities.get("positionEncoding", "utf-16")
            if self.encoding not in ("utf-16", "utf-8"):
                raise ProtocolError("Unsupported position encoding")
            await self.peer.notify("initialized", {})
            await self.peer.notify("workspace/didChangeConfiguration", {"settings": self.settings})
            return self
        except BaseException:
            await self.peer.close()
            raise

    async def _request(self, method, params):
        if method == "workspace/configuration":
            result = []
            for item in params.get("items", []):
                value = self.settings
                for component in item.get("section", "").split("."):
                    value = value.get(component, {}) if isinstance(value, dict) and component else value
                result.append(value)
            return result
        if method == "workspace/workspaceFolders":
            return [{"uri": self.root.as_uri(), "name": self.root.name}]
        if method == "workspace/applyEdit":
            return {"applied": False, "failureReason": "Use an explicit Code Intelligence edit proposal"}
        if method in ("window/workDoneProgress/create", "client/registerCapability", "client/unregisterCapability"):
            if method == "client/registerCapability":
                # Servers may register watched-file notifications; polling emits them.
                if any(r.get("method") != "workspace/didChangeWatchedFiles" for r in params.get("registrations", [])):
                    raise ProtocolError("Dynamic feature registration is unsupported")
            return None
        raise ProtocolError("Unsupported server request")

    async def _event(self, method, params):
        if method != "textDocument/publishDiagnostics":
            return
        uri = params.get("uri")
        doc = self.documents.get(uri)
        if not doc:
            return
        version = params.get("version")
        if version is not None and version != doc["version"]:
            return
        # An unsolicited unversioned push cannot supersede a correlated response.
        current = self.results.get(uri, {})
        if version is None and current.get("status") == "current" and current.get("digest") == doc["digest"]:
            return
        self.results[uri] = {"status": "current" if version is not None else "unversioned",
                             "version": version, "digest": doc["digest"],
                             "diagnostics": params.get("diagnostics", [])[:100], "server": self.name,
                             "generation": self.generation}
        self.changed.set()

    async def sync(self, path):
        async with self.sync_lock:
            path = project_file(self.root, str(path))
            first_stat = path.stat()
            text = read_text(path)
            last_stat = path.stat()
            if (first_stat.st_mtime_ns, first_stat.st_size) != (last_stat.st_mtime_ns, last_stat.st_size):
                raise ValueError("File changed while synchronizing the language server")
            uri, fingerprint = path.as_uri(), digest(text)
            old = self.documents.get(uri)
            if old and old["digest"] == fingerprint:
                return old
            version = old["version"] + 1 if old else 1
            doc = {"version": version, "digest": fingerprint, "text": text, "uri": uri, "path": str(path)}
            doc["stat"] = (last_stat.st_mtime_ns, last_stat.st_size)
            self.documents[uri] = doc
            self.results.pop(uri, None)
            if not old:
                await self.peer.notify("textDocument/didOpen", {"textDocument": {
                    "uri": uri, "languageId": self.language_id or LANGUAGES.get(path.suffix, "plaintext"), "version": version, "text": text}})
            else:
                sync = self.capabilities.get("textDocumentSync", 1)
                kind = sync.get("change", 1) if isinstance(sync, dict) else sync
                change = {"text": text}
                if kind == 2:
                    last = old["text"].split("\n")[-1]
                    units = len(last.encode("utf-16-le")) // 2 if self.encoding == "utf-16" else len(last.encode())
                    change["range"] = {"start": {"line": 0, "character": 0},
                                       "end": {"line": old["text"].count("\n"), "character": units}}
                await self.peer.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": version}, "contentChanges": [change]})
            sync = self.capabilities.get("textDocumentSync", {})
            if isinstance(sync, dict) and sync.get("save"):
                await self.peer.notify("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})
            self.last_used = time.monotonic()
            return doc

    async def diagnostics(self, path, timeout=5):
        self.last_used = time.monotonic()
        doc = await self.sync(path)
        uri, version, fingerprint = doc["uri"], doc["version"], doc["digest"]
        commands = self.capabilities.get("executeCommandProvider", {}).get("commands", [])
        if self.name == "typescript" and "typescript.tsserverRequest" in commands and self.direct_diagnostics is not False:
            try:
                items = await asyncio.wait_for(self._typescript_diagnostics(path), timeout)
            except asyncio.TimeoutError:
                return {"status": "pending", "path": str(path), "server": self.name, "digest": fingerprint}
            except ProtocolError:
                self.direct_diagnostics = False
            else:
                self.direct_diagnostics = True
                if self.documents.get(uri, {}).get("version") != version or digest(read_text(Path(path))) != fingerprint:
                    return {"status": "stale", "path": str(path), "server": self.name}
                result = {"status": "current", "version": version, "digest": fingerprint,
                          "diagnostics": items[:100], "server": self.name, "generation": self.generation,
                          "method": "typescript-sync", "path": str(path)}
                self.results[uri] = result
                return result
        if self.capabilities.get("diagnosticProvider"):
            report = await self.peer.request("textDocument/diagnostic", {"textDocument": {"uri": uri}}, timeout=timeout)
            # No previousResultId was sent: an unchanged response cannot prove clean.
            if report.get("kind") == "full" and self.documents[uri]["version"] == version and digest(read_text(Path(path))) == fingerprint:
                self.results[uri] = {"status": "current", "version": version, "digest": fingerprint,
                                     "diagnostics": report.get("items", [])[:100], "server": self.name, "generation": self.generation}
            else:
                return {"status": "pending", "path": str(path), "server": self.name, "digest": fingerprint}
        else:
            end = time.monotonic() + timeout
            while uri not in self.results and time.monotonic() < end:
                self.changed.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.changed.wait(), max(0.01, end - time.monotonic()))
        result = self.results.get(uri)
        if not result:
            return {"status": "pending", "path": str(path), "server": self.name, "digest": fingerprint}
        if digest(read_text(Path(path))) != result["digest"]:
            return {"status": "stale", "path": str(path), "server": self.name}
        return {**result, "path": str(path)}

    async def _typescript_diagnostics(self, path):
        # Fixed read-only tsserver requests, never commands supplied by the model
        # or by a code action. TLS forwards these against the last synced text.
        diagnostics = []
        severity = {"error": 1, "warning": 2, "message": 3, "suggestion": 4}
        for command in ("syntacticDiagnosticsSync", "semanticDiagnosticsSync"):
            response = await self.peer.request("workspace/executeCommand", {
                "command": "typescript.tsserverRequest", "arguments": [command,
                    {"file": str(path), "includeLinePosition": True}, {"executionTarget": 0}]})
            if not isinstance(response, dict) or response.get("success") is False or not isinstance(response.get("body"), list):
                raise ProtocolError("TypeScript did not return a diagnostics verdict")
            for item in response["body"]:
                try:
                    start, end = item["startLocation"], item["endLocation"]
                    positions = [start["line"], start["offset"], end["line"], end["offset"]]
                    if any(type(p) is not int or p < 1 for p in positions):
                        raise ValueError("Invalid diagnostic position")
                    diagnostics.append({"range": {
                        "start": {"line": start["line"] - 1, "character": start["offset"] - 1},
                        "end": {"line": end["line"] - 1, "character": end["offset"] - 1}},
                        "severity": severity.get(item.get("category"), 1), "code": item.get("code"),
                        "message": str(item["message"]), "source": "typescript"})
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProtocolError("Invalid TypeScript diagnostic; cannot confirm a clean file") from exc
        return diagnostics

    async def query(self, action, path=None, line=1, column=1, query="", new_name=""):
        self.last_used = time.monotonic()
        if action == "workspace_symbols":
            if not self.capabilities.get("workspaceSymbolProvider"):
                raise ValueError("Server does not support workspace symbols")
            return await self.peer.request("workspace/symbol", {"query": query})
        doc = await self.sync(path)
        params = {"textDocument": {"uri": doc["uri"]}}
        methods = {"definition": ("definitionProvider", "textDocument/definition"),
                   "references": ("referencesProvider", "textDocument/references"),
                   "hover": ("hoverProvider", "textDocument/hover"),
                   "symbols": ("documentSymbolProvider", "textDocument/documentSymbol"),
                   "rename": ("renameProvider", "textDocument/rename"),
                   "actions": ("codeActionProvider", "textDocument/codeAction")}
        capability, method = methods[action]
        if not self.capabilities.get(capability):
            raise ValueError(f"Server does not support {action}")
        if type(line) is not int or type(column) is not int or min(line, column) < 1:
            raise ValueError("Line and column are one-based positive integers")
        pos = {"line": line - 1, "character": column - 1}
        if action != "symbols":
            params["position"] = pos
        if action == "references":
            params["context"] = {"includeDeclaration": True}
        if action == "rename":
            rename = self.capabilities[capability]
            if isinstance(rename, dict) and rename.get("prepareProvider"):
                if await self.peer.request("textDocument/prepareRename", params) is None:
                    raise ValueError("This position cannot be renamed")
            params["newName"] = new_name
        if action == "actions":
            params.pop("position", None)
            params["range"] = {"start": pos, "end": pos}
            params["context"] = {"diagnostics": self.results.get(doc["uri"], {}).get("diagnostics", [])}
        return await self.peer.request(method, params)

    async def close(self):
        with contextlib.suppress(Exception):
            await self.peer.request("shutdown", timeout=1)
            await self.peer.notify("exit", {})
        await self.peer.close()
