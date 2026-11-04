import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from usr.plugins.code_intelligence.helpers.lsp import LanguageServer
from usr.plugins.code_intelligence.helpers.dap import DebugSession
from usr.plugins.code_intelligence.helpers.edits import Proposals
from usr.plugins.code_intelligence.helpers.setup import DATA
from usr.plugins.code_intelligence.helpers.workspace import snapshot

NODE = os.environ.get("CI_TEST_NODE", "/usr/bin/node")
PYTHON = os.environ.get("CI_TEST_PYTHON", "/opt/venv/bin/python")


class RealTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.resources = []

    async def asyncTearDown(self):
        for resource in self.resources:
            await resource.close()
        self.temp.cleanup()

    async def server(self, language):
        script = "pyright/langserver.index.js" if language == "python" else "typescript-language-server/lib/cli.mjs"
        settings = {"python": {"pythonPath": PYTHON, "analysis": {"typeCheckingMode": "basic"}}}
        server = LanguageServer(self.root, language, [NODE, str(DATA / "tools/node_modules" / script), "--stdio"], settings)
        self.resources.append(server)
        await server.start()
        return server

    async def test_python_type_feedback_references_and_multi_file_rename(self):
        a, b = self.root / "a.py", self.root / "b.py"
        a.write_text('value: int = "wrong"\n')
        b.write_text('from a import value\nprint(value)\nother_value = "value"\n')
        server = await self.server("python")
        diagnostic = await server.diagnostics(a, 10)
        self.assertEqual(diagnostic["status"], "current")
        self.assertTrue(any(d.get("severity") == 1 for d in diagnostic["diagnostics"]))
        await server.sync(b)
        refs = await server.query("references", a, 1, 1)
        self.assertGreaterEqual(len(refs), 3)
        before = snapshot(self.root)
        edit = await server.query("rename", a, 1, 1, new_name="renamed")
        proposals = Proposals(self.root, "test", self.root / "journal")
        p = proposals.create(edit, before, server, "rename")
        self.assertEqual(len(p["files"]), 2)
        proposals.apply(p["id"], {server.generation})
        self.assertIn('other_value = "value"', b.read_text())
        self.assertIn("from a import renamed", b.read_text())
        a.write_text("renamed: int = 4\n")
        self.assertFalse((await server.diagnostics(a, 10))["diagnostics"])

    async def test_typescript_type_error_and_import_quick_fix(self):
        (self.root / "tsconfig.json").write_text('{"compilerOptions":{"strict":true,"target":"ES2020","module":"commonjs"},"include":["*.ts"]}')
        (self.root / "math.ts").write_text("export function add(a: number, b: number) { return a + b; }\n")
        path = self.root / "main.ts"
        path.write_text('const value: number = "wrong";\nconst result = add(1, 2);\nconsole.log(value, result);\n')
        server = await self.server("typescript")
        report = await server.diagnostics(path, 10)
        self.assertIn(2322, [d.get("code") for d in report["diagnostics"]])
        self.assertEqual(report["status"], "current")
        self.assertEqual(report["method"], "typescript-sync")
        before = snapshot(self.root)
        actions = await server.query("actions", path, 2, 16)
        action = next(a for a in actions if a["title"].startswith("Add import"))
        self.assertFalse(action["command"]["arguments"][0]["action"].get("commands"))
        proposals = Proposals(self.root, "test", self.root / "journal")
        p = proposals.create(action["edit"], before, server, action["title"])
        proposals.apply(p["id"], {server.generation})
        self.assertIn('import { add } from "./math";', path.read_text())
        path.write_text(path.read_text().replace('"wrong"', "5"))
        report = await server.diagnostics(path, 10)
        # TS diagnostics can arrive in multiple batches. Wait for the semantic set.
        for _ in range(30):
            if not report["diagnostics"]: break
            await asyncio.sleep(.1)
            report = await server.diagnostics(path, 1)
        self.assertFalse(report["diagnostics"])
        self.assertEqual(report["status"], "current")
        # A late unversioned push must not overwrite the correlated clean result.
        await server._event("textDocument/publishDiagnostics", {"uri": path.as_uri(),
                           "diagnostics": [{"message": "obsolete error", "severity": 1}]})
        self.assertFalse(server.results[path.as_uri()]["diagnostics"])

    async def test_typescript_module_extensions_and_repeated_clean_edits(self):
        (self.root / "tsconfig.json").write_text('{"compilerOptions":{"strict":true,"module":"NodeNext"}}')
        server = await self.server("typescript")
        for suffix in (".mts", ".cts"):
            path = self.root / ("fixture" + suffix)
            path.write_text('export const value: number = "wrong";\n')
            self.assertIn(2322, [d.get("code") for d in (await server.diagnostics(path, 10))["diagnostics"]])
            for value in (1, 2):
                path.write_text(f"export const value: number = {value};\n")
                report = await server.diagnostics(path, 10)
                self.assertEqual(report["status"], "current")
                self.assertFalse(report["diagnostics"])

    async def debugger_case(self, kind, source_maps=False):
        filename = "fixture.py" if kind == "python" else ("fixture.ts" if source_maps else "fixture.js")
        path = self.root / filename
        path.write_text("value = 4\nvalue += 2\nprint(value)\n" if kind == "python" else "let value = 4;\nvalue += 2;\nconsole.log(value);\n")
        program = path.name
        if source_maps:
            subprocess.run([NODE, str(DATA / "tools/node_modules/typescript/bin/tsc"), "--sourceMap", "--target", "ES2020", str(path)], check=True, capture_output=True)
            program = "fixture.js"
        session = DebugSession(self.root, "owner", {"type": kind, "program": program}, PYTHON, NODE)
        self.resources.append(session)
        await session.launch([{"path": path.name, "lines": [2]}])
        for _ in range(100):
            if session.state == "stopped": break
            await asyncio.sleep(.1)
        self.assertEqual(session.state, "stopped")
        epoch = session.epoch
        stack = await session.inspect("stack", stop_generation=epoch)
        self.assertEqual(stack["stackFrames"][0]["line"], 2)
        self.assertTrue(stack["stackFrames"][0]["source"]["path"].endswith(filename))
        scopes = await session.inspect("scopes", stop_generation=epoch, frame_id=stack["stackFrames"][0]["id"])
        values = await session.inspect("variables", stop_generation=epoch, variables_reference=scopes["scopes"][0]["variablesReference"])
        self.assertEqual(next(v["value"] for v in values["variables"] if v["name"] == "value"), "4")
        await session.control("next", stop_generation=epoch, wait_seconds=5)
        with self.assertRaises(ValueError): await session.inspect("stack", stop_generation=epoch)
        self.assertGreater(session.epoch, epoch)
        stack = await session.inspect("stack", stop_generation=session.epoch)
        scopes = await session.inspect("scopes", stop_generation=session.epoch, frame_id=stack["stackFrames"][0]["id"])
        values = await session.inspect("variables", stop_generation=session.epoch, variables_reference=scopes["scopes"][0]["variablesReference"])
        self.assertEqual(next(v["value"] for v in values["variables"] if v["name"] == "value"), "6")
        await session.control("continue", stop_generation=session.epoch, wait_seconds=5)
        self.assertEqual(session.state, "terminated")

    async def test_python_debugger(self): await self.debugger_case("python")
    async def test_node_debugger(self): await self.debugger_case("node")
    async def test_typescript_source_mapped_debugger(self): await self.debugger_case("node", True)

    async def test_configured_stdio_adapter_uses_owned_launch(self):
        path = self.root / "custom.py"
        path.write_text("value = 4\nvalue += 2\nprint(value)\n")
        adapter = {"command": [PYTHON, "-m", "debugpy.adapter"],
                   "launch_arguments": {"type": "python", "subProcess": False}}
        session = DebugSession(self.root, "owner", {"type": "custom", "program": path.name}, PYTHON, NODE, adapter)
        self.resources.append(session)
        await session.launch([{"path": path.name, "lines": [2]}])
        for _ in range(100):
            if session.state == "stopped": break
            await asyncio.sleep(.05)
        self.assertEqual(session.state, "stopped")

    async def test_stale_push_diagnostics_are_discarded(self):
        path = self.root / "main.py"
        path.write_text("value = 4\n")
        server = await self.server("python")
        await server.sync(path)
        path.write_text("value = 5\n")
        doc = await server.sync(path)
        server.results.clear()
        await server._event("textDocument/publishDiagnostics", {"uri": path.as_uri(), "version": doc["version"] - 1,
                                                                 "diagnostics": [{"message": "old error"}]})
        self.assertNotIn(path.as_uri(), server.results)


if __name__ == "__main__": unittest.main()
