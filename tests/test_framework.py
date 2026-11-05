import asyncio
import json
from pathlib import Path
import shutil
import time
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from helpers import runtime
runtime.args["dockerized"] = True
from agent import AgentContext, AgentConfig, LoopData
from helpers import extension, plugins, projects, responses_tools, tool_policy
from helpers.tool import Response
from usr.plugins.code_intelligence.helpers import access, hooks, service
from usr.plugins.code_intelligence.helpers.setup import DATA


class Framework(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.name = "ci_test_" + uuid.uuid4().hex[:10]
        projects.create_project(self.name, {"title": "Synthetic CI fixture", "description": "Plugin acceptance"})
        self.root = Path(projects.get_project_folder(self.name))
        self.path = self.root / "main.py"
        self.path.write_text('value: int = "wrong"\nprint(value)\n')
        self.context = AgentContext(AgentConfig(mcp_servers="", profile="default"), data={"project": self.name})
        self.agent = self.context.agent0
        self.agent.loop_data = LoopData()
        self.scope = access.resolve(self.agent, require_trust=False)
        access.grant(self.scope, "semantic", self.scope.fingerprint, True)

    async def asyncTearDown(self):
        await asyncio.to_thread(service.shutdown)
        with AgentContext._contexts_lock:
            AgentContext._contexts.pop(self.context.id, None)
        shutil.rmtree(self.root)

    async def test_native_discovery_has_typed_schemas_and_six_separate_policy_ids(self):
        self.assertEqual(plugins.get_plugin_meta("code_intelligence").name, "code_intelligence")
        tools, names = responses_tools.build_responses_function_tools(self.agent)
        actual = {t["name"]: t for t in tools if t["name"] in access.TOOLS}
        self.assertEqual(set(actual), access.TOOLS)
        self.assertIn("line", actual["code_inspect"]["parameters"]["properties"])
        identities = {tool_policy._tool_identity(self.agent, name)[0] for name in access.TOOLS}
        self.assertEqual(len(identities), 6)
        manifest = extension.get_webui_extension_manifest(self.agent)
        self.assertTrue(any("code_intelligence" in str(v) for v in manifest.values()))

    async def test_actual_edit_hooks_feed_diagnostics_and_preserve_editor_response(self):
        await extension.call_extensions_async("text_editor_write_after", agent=self.agent,
                                             data={"path": str(self.path), "total_lines": 2})
        response = Response("write succeeded", False)
        # Give the cold server time to initialize; the normal post-edit budget is smaller.
        await service.drain(self.agent, 0)
        await asyncio.sleep(2)
        await extension.call_extensions_async("tool_execute_after", agent=self.agent, response=response, tool_name="text_editor")
        self.assertIn("write succeeded", response.message)
        self.assertIn("Code Intelligence", response.message)
        self.assertFalse(response.break_loop)

    async def test_completion_deferral_is_bounded_and_pending_is_not_clean(self):
        reports = [{"status": "current", "path": str(self.path), "digest": "one", "diagnostics": [{"severity": 1, "message": "type mismatch"}]}]
        with patch.object(service, "drain", AsyncMock(return_value=reports)):
            first = Response("finished", True)
            await hooks.after_tool(self.agent, first)
            self.assertFalse(first.break_loop)
            second = Response("finished", True)
            await hooks.after_tool(self.agent, second)
            self.assertTrue(second.break_loop)
        with patch.object(service, "drain", AsyncMock(return_value=[{"status": "pending", "paths": [str(self.path)]}])):
            final = Response("finished", True)
            await hooks.after_tool(self.agent, final)
            self.assertTrue(final.break_loop)
            self.assertIn("pending", final.message)

    async def test_both_core_dispatch_paths_execute_plugin_tool(self):
        # No model call: dispatch real tool requests through both core paths.
        self.agent.handle_intervention = AsyncMock()
        with patch.object(service, "dispatch", AsyncMock(return_value={"proof": "plugin-dispatched"})) as call:
            await self.agent._execute_tool_request("code_inspect", {"action": "status"}, "native fixture")
            await self.agent.process_tools(json.dumps({"tool_name": "code_inspect", "tool_args": {"action": "status"}}))
            self.assertEqual(call.await_count, 2)

    async def test_policy_blocks_tools_and_automatic_hooks(self):
        original = tool_policy.resolve_tool(self.agent, "code_inspect")
        with patch.object(tool_policy, "ensure_tool_allowed", side_effect=PermissionError("synthetic policy block")):
            with self.assertRaises(PermissionError):
                await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})
            await hooks.after_edit(self.agent, {"path": str(self.path)})
            self.assertIsNone(service._manager)
        self.assertTrue(original.allowed)

    async def test_untrusted_or_split_runtime_is_rejected(self):
        access.grant(self.scope, "semantic", self.scope.fingerprint, False)
        with self.assertRaises(PermissionError): access.resolve(self.agent)
        with patch.object(runtime, "is_dockerized", return_value=False):
            with self.assertRaisesRegex(ValueError, "execution location"):
                access.resolve(self.agent, require_trust=False)

    async def test_actual_policy_and_api_reject_blocked_tool(self):
        from usr.plugins.code_intelligence.api.command import Command
        identity = tool_policy._tool_identity(self.agent, "code_apply")[0]
        plugins.save_plugin_config("_tool_access", self.name, "default", {
            "mode": "custom", "default": "allow", "blocked": [identity]})
        with self.assertRaises(Exception):
            await service.dispatch(self.agent, "code_apply", {"proposal_id": "unknown"})
        self.assertFalse(tool_policy.resolve_tool(self.agent, "code_apply").allowed)
        api = Command(None, threading.RLock())
        result = await api.process({"operation": "tool", "context_id": self.context.id,
                                    "tool": "code_apply", "args": {"proposal_id": "unknown"}}, None)
        self.assertFalse(result["ok"])
        self.assertIn('Tool "code_apply" is blocked', result["error"])
        self.assertTrue(Command.requires_auth())
        self.assertTrue(Command.requires_csrf())

    async def test_debug_session_is_context_owned_and_revocation_cleans_up(self):
        self.path.write_text("value = 4\nvalue += 2\nprint(value)\n")
        plugins.save_plugin_config("code_intelligence", self.name, "default", {
            "debug_targets": {"fixture": {"type": "python", "program": "main.py"}}})
        scope = access.resolve(self.agent, "debug_launch", require_trust=False)
        access.grant(scope, "debug", scope.fingerprint, True)
        launched = await service.dispatch(self.agent, "debug_launch", {"target": "fixture", "breakpoints": [{"path": "main.py", "lines": [2]}]})
        other = AgentContext(AgentConfig(mcp_servers="", profile="default"), data={"project": self.name})
        try:
            with self.assertRaises(PermissionError):
                await service.dispatch(other.agent0, "debug_inspect", {"session_id": launched["session_id"]})
            workspace = next(w for w in service._manager.workspaces.values() if w.scope.owner == scope.owner)
            debugger = workspace.debuggers[launched["session_id"]]
            access.grant(scope, "debug", scope.fingerprint, False)
            for _ in range(60):
                if debugger.peer.closed: break
                await asyncio.sleep(.1)
            await asyncio.to_thread(service.shutdown)
            self.assertTrue(debugger.peer.closed)
            self.assertIsNotNone(debugger.peer.proc.returncode)
        finally:
            with AgentContext._contexts_lock:
                AgentContext._contexts.pop(other.id, None)

    async def test_debug_environment_references_resolve_and_output_is_masked(self):
        from helpers.secrets import SecretsManager
        secret_file = self.root / "fixture-secrets.env"
        secret_file.write_text("FIXTURE_TOKEN=synthetic-token-for-acceptance\n")
        secret_manager = SecretsManager(str(secret_file))
        self.path.write_text('import os\nprint(os.environ["FIXTURE_ENV"])\n')
        plugins.save_plugin_config("code_intelligence", self.name, "default", {
            "debug_targets": {"fixture": {"type": "python", "program": "main.py",
                                          "env_secrets": {"FIXTURE_ENV": "FIXTURE_TOKEN"}}}})
        scope = access.resolve(self.agent, "debug_launch", require_trust=False)
        access.grant(scope, "debug", scope.fingerprint, True)
        with patch("helpers.secrets.get_secrets_manager", return_value=secret_manager):
            launched = await service.dispatch(self.agent, "debug_launch", {"target": "fixture"})
            for _ in range(100):
                status = await service.dispatch(self.agent, "debug_inspect", {"session_id": launched["session_id"]})
                if status["state"] == "terminated": break
                await asyncio.sleep(.05)
            self.assertEqual(status["state"], "terminated")
            output = await service.dispatch(self.agent, "debug_inspect", {"session_id": launched["session_id"], "action": "output"})
            self.assertNotIn("synthetic-token-for-acceptance", str(output))
            self.assertIn("FIXTURE_TOKEN", str(output))

    async def test_reload_closes_old_manager_before_modules_are_purged(self):
        await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})
        old = service._manager
        workspace = next(iter(old.workspaces.values()))
        # Exercise the actual extensible function start path without purging the
        # test runner's own imported classes out of sys.modules.
        extension.call_extensions_sync("_functions/helpers/plugins/after_plugin_change/start",
                                       data={"args": (["code_intelligence"],), "kwargs": {"python_change": True}})
        self.assertTrue(workspace.closed)
        self.assertFalse(old.loop.is_running())

    async def test_scope_disable_closes_owned_language_server(self):
        await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})
        current = service._manager
        self.assertTrue(current.workspaces)
        workspace = next(iter(current.workspaces.values()))
        peer = next(iter(workspace.servers.values())).peer
        plugins.toggle_plugin("code_intelligence", False, project_name=self.name)
        for _ in range(40):
            if peer.closed: break
            await asyncio.sleep(.1)
        self.assertTrue(peer.closed)
        self.assertIsNotNone(peer.proc.returncode)

    async def test_external_edits_refresh_and_context_removal_cleans_up(self):
        first = await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})
        self.assertTrue(first["diagnostics"])
        self.path.write_text("value: int = 4\nprint(value)\n")
        current = service._manager
        workspace = next(iter(current.workspaces.values()))
        for _ in range(60):
            await asyncio.sleep(.1)
            report = workspace.reports.get(str(self.path), {})
            if report.get("status") == "current" and not report.get("diagnostics"): break
        self.assertEqual(report.get("status"), "current")
        self.assertFalse(report["diagnostics"])
        with AgentContext._contexts_lock:
            AgentContext._contexts.pop(self.context.id, None)
        for _ in range(50):
            if workspace.closed: break
            await asyncio.sleep(.1)
        self.assertTrue(workspace.closed)

    async def test_idle_server_sleeps_but_monitor_wakes_it_without_file_events(self):
        await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})
        current = service._manager
        workspace = next(iter(current.workspaces.values()))
        original = workspace.servers["python"]
        # Drop OS events deliberately: bind-mount reconciliation must work even
        # after the LSP's in-memory documents have been released.
        from helpers.watchdog import remove_watchdog
        remove_watchdog(workspace.watcher)
        async def sleep_server():
            original.last_used -= 301
            await workspace.suspend_idle_servers()
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(sleep_server(), current.loop))
        self.assertTrue(original.peer.closed)
        self.assertFalse(workspace.closed)
        self.assertFalse(workspace.servers)
        status = await service.dispatch(self.agent, "code_inspect", {"action": "status"})
        self.assertTrue(status["monitor"]["active"])
        self.assertEqual(status["monitor"]["tracked_files"], 1)
        self.path.write_text("value: int = 4\nprint(value)\n")
        for _ in range(80):
            await asyncio.sleep(.1)
            report = workspace.reports.get(str(self.path), {})
            if report.get("status") == "current" and not report.get("diagnostics"):
                break
        self.assertEqual(report.get("status"), "current")
        self.assertFalse(report["diagnostics"])
        self.assertNotEqual(original.generation, workspace.servers["python"].generation)

    async def test_keep_warm_setting_and_status_do_not_fake_server_activity(self):
        plugins.save_plugin_config("code_intelligence", self.name, "default", {"idle_seconds": 0})
        scope = access.resolve(self.agent, require_trust=False)
        access.grant(scope, "semantic", scope.fingerprint, True)
        await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})
        current = service._manager
        workspace = next(iter(current.workspaces.values()))
        original = workspace.servers["python"]
        last_used = original.last_used
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(
            workspace.suspend_idle_servers(now=last_used + 4000), current.loop))
        self.assertFalse(original.peer.closed)
        await service.dispatch(self.agent, "code_inspect", {"action": "status"})
        self.assertEqual(original.last_used, last_used)

    async def test_disabled_language_does_not_spawn_and_config_change_revokes_access(self):
        plugins.save_plugin_config("code_intelligence", self.name, "default", {"servers": {"python": {"disabled": True}}})
        with self.assertRaises(PermissionError):
            access.resolve(self.agent)
        scope = access.resolve(self.agent, require_trust=False)
        access.grant(scope, "semantic", scope.fingerprint, True)
        await hooks.after_edit(self.agent, {"path": str(self.path)})
        status = await service.dispatch(self.agent, "code_inspect", {"action": "status"})
        self.assertFalse(status["servers"])
        self.assertFalse(status["pending"])
        with self.assertRaisesRegex(ValueError, "disabled"):
            await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(self.path)})

    async def test_code_action_pipeline_uses_safe_edit_without_command_execution(self):
        (self.root / "tsconfig.json").write_text('{"compilerOptions":{"strict":true,"target":"ES2020"},"include":["*.ts"]}')
        (self.root / "math.ts").write_text("export const answer = 42;\n")
        path = self.root / "main.ts"
        path.write_text("console.log(answer);\n")
        await service.dispatch(self.agent, "code_inspect", {"action": "diagnostics", "path": str(path)})
        actions = await service.dispatch(self.agent, "code_propose", {"action": "actions", "path": str(path), "line": 1, "column": 13})
        action = next(a for a in actions["actions"] if a["title"].startswith("Add import"))
        proposal = await service.dispatch(self.agent, "code_propose", {"action": "resolve_action", "path": str(path), "action_id": action["action_id"]})
        await service.dispatch(self.agent, "code_apply", {"proposal_id": proposal["id"]})
        self.assertIn('import { answer }', path.read_text())


if __name__ == "__main__": unittest.main()
