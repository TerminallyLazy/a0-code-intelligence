import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from helpers import runtime
runtime.args["dockerized"] = True
from agent import AgentConfig, AgentContext
from helpers import extension, plugins, projects, settings
from usr.plugins.code_intelligence.api.command import Command
from usr.plugins.code_intelligence.helpers import access, service


class WithoutProject(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ci_workdir_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workdir"
        self.root.mkdir()
        self.settings = {**settings.get_settings(), "workdir_path": str(self.root)}
        self.config = {"debug_targets": {"example": {"type": "python", "program": "debug.py"}}}
        original = plugins.get_plugin_config
        def config(name, *args, **kwargs):
            return self.config if name == access.NAME else original(name, *args, **kwargs)
        for patcher in (patch.object(settings, "get_settings", side_effect=lambda: self.settings),
                        patch.object(plugins, "get_plugin_config", side_effect=config)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.context = AgentContext(AgentConfig(mcp_servers="", profile="default"))
        self.agent = self.context.agent0
        self.contexts = [self.context]
        self.assertIsNone(projects.get_context_project_name(self.context))
        self.scope = access.resolve(self.agent, require_trust=False)

    async def asyncTearDown(self):
        await asyncio.to_thread(service.shutdown)
        with AgentContext._contexts_lock:
            for context in self.contexts:
                AgentContext._contexts.pop(context.id, None)

    def allow(self, kind="semantic"):
        scope = access.resolve(self.agent, require_trust=False)
        access.grant(scope, kind, scope.fingerprint, True)
        return scope

    async def test_status_and_grant_work_without_creating_a_project(self):
        self.settings["workdir_path"] = str(self.root / "new-folder")
        api = Command(None, threading.RLock())
        with patch.object(projects, "create_project", side_effect=AssertionError("must not create a project")):
            status = await api.process({"operation": "status", "context_id": self.context.id}, None)
            self.assertTrue(status["ok"], status)
            self.assertIsNone(status["scope"]["project"])
            self.assertEqual(status["scope"]["workspace_kind"], "workdir")
            self.assertEqual(status["scope"]["root"], self.settings["workdir_path"])
            self.assertFalse(Path(self.settings["workdir_path"]).exists())
            granted = await api.process({"operation": "grant", "context_id": self.context.id,
                                        "kind": "semantic", "enabled": True,
                                        "fingerprint": status["scope"]["fingerprint"]}, None)
            self.assertTrue(granted["ok"], granted)
            self.assertTrue(granted["scope"]["semantic_trusted"])
            self.assertFalse(granted["scope"]["debug_trusted"])
            self.assertTrue(Path(self.settings["workdir_path"]).is_dir())
            self.assertIsNone(projects.get_context_project_name(self.context))

    async def test_native_edit_feedback_and_semantic_rename_in_workdir(self):
        path = self.root / "main.py"
        path.write_text('value: int = "wrong"\nprint(value)\n')
        self.allow()
        await extension.call_extensions_async("text_editor_write_after", agent=self.agent,
                                              data={"path": str(path), "total_lines": 2})
        reports = await service.drain(self.agent, 5)
        self.assertTrue(any(r["status"] == "current" and r["diagnostics"] for r in reports))
        refs = await service.dispatch(self.agent, "code_inspect", {"action": "references", "path": "main.py", "line": 1, "column": 1})
        self.assertGreaterEqual(len(refs["items"]), 2)
        proposal = await service.dispatch(self.agent, "code_propose", {"action": "rename", "path": "main.py", "line": 1, "column": 1, "new_name": "renamed"})
        result = await service.dispatch(self.agent, "code_apply", {"proposal_id": proposal["id"]})
        self.assertEqual(result["status"], "applied")
        self.assertIn("print(renamed)", path.read_text())

    async def test_workdir_typescript_diagnostics(self):
        (self.root / "main.ts").write_text('const value: number = "wrong";\n')
        self.allow()
        report = await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": "main.ts"})
        self.assertEqual(report["status"], "current")
        self.assertTrue(any(d.get("code") == 2322 for d in report["diagnostics"]))

    async def test_debug_launch_requires_separate_grant_and_stays_chat_owned(self):
        (self.root / "debug.py").write_text("value = 4\nvalue += 2\nprint(value)\n")
        self.allow()
        with self.assertRaises(PermissionError):
            await service.dispatch(self.agent, "debug_launch", {"target": "example"})
        self.allow("debug")
        launched = await service.dispatch(self.agent, "debug_launch", {"target": "example", "breakpoints": [{"path": "debug.py", "lines": [2]}]})
        for _ in range(80):
            if launched["state"] == "stopped":
                break
            await asyncio.sleep(.1)
            launched = await service.dispatch(self.agent, "debug_inspect", {"session_id": launched["session_id"]})
        self.assertEqual(launched["state"], "stopped")
        stack = await service.dispatch(self.agent, "debug_inspect", {"action": "stack", "session_id": launched["session_id"], "stop_generation": launched["stop_generation"]})
        self.assertEqual(stack["stackFrames"][0]["line"], 2)
        other = AgentContext(AgentConfig(mcp_servers="", profile="default"))
        self.contexts.append(other)
        with self.assertRaises(PermissionError):
            await service.dispatch(other.agent0, "debug_inspect", {"session_id": launched["session_id"]})
        stopped = await service.dispatch(self.agent, "debug_control", {"action": "stop", "session_id": launched["session_id"]})
        self.assertEqual(stopped["state"], "terminated")

    async def test_workdir_change_revokes_access_and_closes_old_server(self):
        (self.root / "main.py").write_text("value = 1\n")
        before = self.allow()
        await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": "main.py"})
        workspace = next(iter(service._manager.workspaces.values()))
        server = workspace.servers["python"]
        self.settings["workdir_path"] = str(self.root / "different")
        after = access.resolve(self.agent, require_trust=False)
        self.assertNotEqual(before.fingerprint, after.fingerprint)
        self.assertFalse(access.trusted(after, "semantic"))
        with self.assertRaises(PermissionError):
            await service.dispatch(self.agent, "code_inspect", {"action": "status"})
        with self.assertRaisesRegex(ValueError, "stale"):
            access.grant(after, "semantic", before.fingerprint, True)
        for _ in range(60):
            if server.peer.closed and workspace.closed:
                break
            await asyncio.sleep(.1)
        self.assertTrue(server.peer.closed)
        self.assertTrue(workspace.closed)

    async def test_project_precedence_and_no_grant_inheritance_at_same_path(self):
        workdir = self.allow()
        self.context.set_data("project", "synthetic-project")
        with patch.object(projects, "get_project_folder", return_value=str(self.root)):
            project = access.resolve(self.agent, require_trust=False)
            self.assertEqual(project.project, "synthetic-project")
            self.assertNotEqual(project.fingerprint, workdir.fingerprint)
            self.assertFalse(access.trusted(project, "semantic"))
            self.settings["workdir_path"] = str(self.root / "ignored")
            self.assertEqual(access.resolve(self.agent, require_trust=False).root, self.root)

    async def test_unset_invalid_and_escaping_paths_are_rejected(self):
        self.allow()
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("outside = 1\n")
        (self.root / "link.py").symlink_to(outside)
        for path in ("../outside.py", "link.py", str(outside)):
            with self.assertRaisesRegex(ValueError, "outside"):
                await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": path})
        for value in ("", None, str(outside)):
            self.settings["workdir_path"] = value
            with self.assertRaises(ValueError):
                access.resolve(self.agent, require_trust=False)


if __name__ == "__main__":
    unittest.main()
