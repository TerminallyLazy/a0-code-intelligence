import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from usr.plugins.code_intelligence.helpers.lsp import LanguageServer


class Freshness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name, "main.ts")
        self.path.write_text("export const value = 1;\n")
        self.server = LanguageServer(self.path.parent, "typescript", [])
        self.server.capabilities = {"executeCommandProvider": {"commands": ["typescript.tsserverRequest"]}}
        self.server.peer.notify = AsyncMock()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_disk_change_during_direct_request_is_stale(self):
        async def changed(*args, **kwargs):
            self.path.write_text('export const value: number = "wrong";\n')
            return {"body": []}
        self.server.peer.request = AsyncMock(side_effect=changed)
        result = await self.server.diagnostics(self.path)
        self.assertEqual(result["status"], "stale")

    async def test_direct_timeout_cannot_reuse_an_old_clean_report(self):
        await self.server.sync(self.path)
        self.server.results[self.path.as_uri()] = {"status": "unversioned", "diagnostics": []}
        async def delayed(*args, **kwargs):
            await asyncio.sleep(10)
        self.server.peer.request = AsyncMock(side_effect=delayed)
        result = await self.server.diagnostics(self.path, timeout=.01)
        self.assertEqual(result["status"], "pending")
        self.assertNotIn("diagnostics", result)

    async def test_malformed_direct_diagnostic_does_not_become_clean(self):
        self.server.peer.request = AsyncMock(return_value={"body": [{"message": "missing range"}]})
        result = await self.server.diagnostics(self.path, timeout=.01)
        self.assertEqual(result["status"], "pending")
        self.assertFalse(self.server.direct_diagnostics)

    async def test_pull_unchanged_without_prior_result_is_not_a_clean_verdict(self):
        self.server.capabilities = {"diagnosticProvider": True}
        self.server.peer.request = AsyncMock(return_value={"kind": "unchanged", "resultId": "unknown"})
        result = await self.server.diagnostics(self.path)
        self.assertEqual(result["status"], "pending")


if __name__ == "__main__":
    unittest.main()
