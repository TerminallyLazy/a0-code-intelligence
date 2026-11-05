from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading

from .setup import DATA
from .workspace import digest

NAME = "code_intelligence"
TOOLS = {"code_inspect", "code_propose", "code_apply", "debug_launch", "debug_control", "debug_inspect"}
_lock = threading.RLock()


@dataclass(frozen=True)
class Scope:
    owner: str
    project: str | None
    root: Path
    fingerprint: str
    config: dict


def resolve(agent, tool="code_inspect", require_trust=True):
    from helpers import plugins, projects, runtime, files, settings
    from helpers.tool_policy import ensure_tool_allowed
    if tool not in TOOLS:
        raise ValueError("Unknown Code Intelligence tool")
    if NAME not in plugins.get_enabled_plugins(agent):
        raise PermissionError("Code Intelligence is disabled for this chat/profile")
    ensure_tool_allowed(agent, tool)
    if not runtime.is_dockerized():
        raise ValueError("Unsupported execution location: enable this plugin in the Docker runtime beside the workspace files")
    project = projects.get_context_project_name(agent.context) or None
    # Match native code execution and the chat file browser: a project's root,
    # otherwise Agent Zero's configured working directory. Never guess from cwd.
    folder = projects.get_project_folder(project) if project else settings.get_settings().get("workdir_path")
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("Configure Agent Zero's working directory before using Code Intelligence")
    root = Path(files.get_abs_path(files.normalize_a0_path(folder))).resolve(strict=bool(project))
    if root.exists() and not root.is_dir():
        raise ValueError("The coding workspace must be a directory")
    config = {**(plugins.get_default_plugin_config(NAME) or {}),
              **(plugins.get_plugin_config(NAME, agent=agent) or {})}
    if any(not isinstance(config.get(key, {}), dict) for key in ("servers", "adapters", "debug_targets")):
        raise ValueError("Server, adapter and debug target configuration must be JSON objects")
    receipt = DATA / "tools/receipt.json"
    executables = {}
    for key in ("python", "node"):
        path = Path(str(config.get(key, "")))
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"Configure an absolute executable {key} path in plugin settings")
        info = path.stat()
        executables[key] = [str(path.resolve()), info.st_size, info.st_mtime_ns]
    entries = {**{f"server:{k}": v for k, v in config.get("servers", {}).items()},
               **{f"adapter:{k}": v for k, v in config.get("adapters", {}).items()}}
    for name, server in entries.items():
        if not isinstance(server, dict):
            raise ValueError("Each server/adapter configuration must be an object")
        if name.startswith("server:") and not isinstance(server.get("initialization", {}), dict):
            raise ValueError("Language server initialization must be an object")
        command = server.get("command")
        if command is not None:
            if not isinstance(command, list) or not command or any(not isinstance(v, str) for v in command):
                raise ValueError("Server command must be a nonempty string array")
            executable = Path(command[0])
            if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError("Custom server executable must be an absolute executable path")
            for index, arg in enumerate(command):
                candidate = Path(arg)
                if candidate.is_absolute() and candidate.is_file():
                    info = candidate.stat()
                    executables[f"{name}:{index}"] = [str(candidate.resolve()), info.st_size, info.st_mtime_ns]
    identity = {"root": str(root), "profile": agent.config.profile, "config": config,
                "executables": executables, "tools": digest(receipt.read_bytes()) if receipt.is_file() else "missing"}
    if not project:
        # Keep existing project grants valid, but never inherit them just because
        # the global working directory happens to point at the same folder.
        identity["workspace_kind"] = "workdir"
    fingerprint = digest(json.dumps(identity, sort_keys=True))
    scope = Scope(str(agent.context.id) + ":" + str(agent.number), project, root, fingerprint, config)
    kind = "debug" if tool.startswith("debug_") else "semantic"
    if require_trust and not trusted(scope, kind):
        raise PermissionError(f"Workspace {kind} tools are not trusted for this configuration; review access in Code Intelligence")
    return scope


def grants():
    path = DATA / "grants.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def trusted(scope, kind):
    with _lock:
        return grants().get(scope.fingerprint, {}).get(kind) is True


def grant(scope, kind, fingerprint, enabled):
    if kind not in ("semantic", "debug") or fingerprint != scope.fingerprint:
        raise ValueError("Access review is stale; refresh the workspace status")
    if enabled and not scope.project:
        # Status is read-only. Prepare the configured folder only after review,
        # like native execution does before using a new working directory.
        scope.root.mkdir(parents=True, exist_ok=True)
    with _lock:
        DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
        values = grants()
        values.setdefault(fingerprint, {})[kind] = bool(enabled)
        temporary = DATA / "grants.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(values, stream)
        os.replace(temporary, DATA / "grants.json")


def public(scope):
    return {"project": scope.project, "workspace_kind": "project" if scope.project else "workdir",
            "workspace_label": scope.project or "Working directory",
            "root": str(scope.root), "execution_location": "Agent Zero Docker runtime",
            "fingerprint": scope.fingerprint, "semantic_trusted": trusted(scope, "semantic"),
            "debug_trusted": trusted(scope, "debug"), "python": scope.config["python"], "node": scope.config["node"],
            "servers": scope.config.get("servers", {}), "adapters": scope.config.get("adapters", {}),
            "debug_targets": scope.config.get("debug_targets", {})}


def masked(agent, value):
    from helpers.secrets import get_secrets_manager
    # Mask recursively so quotes in secret values do not break JSON serialization.
    manager = get_secrets_manager(agent.context)
    def visit(item):
        if isinstance(item, str):
            return manager.mask_values(item)
        if isinstance(item, list):
            return [visit(v) for v in item]
        if isinstance(item, dict):
            return {k: visit(v) for k, v in item.items()}
        return item
    result = visit(value)
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded) > 64000:
        return {"truncated": True, "excerpt": encoded[:60000], "reason": "Result exceeds the 64,000-character output limit; narrow the query"}
    return result
