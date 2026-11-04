import hashlib
import errno
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from helpers import cache, plugins
from usr.plugins.code_intelligence import hooks
from usr.plugins.code_intelligence.helpers import setup


class Installation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(setup.ROOT / "toolchain", self.root / "toolchain")
        self.data = self.root / ".runtime"
        self.tools = self.data / "tools"
        for name, value in (("ROOT", self.root), ("DATA", self.data)):
            patcher = patch.object(setup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.archives = {}
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("debugpy/adapter/__main__.py", "# synthetic adapter")
        self.archives["fixture:debugpy"] = wheel.getvalue()
        adapter = io.BytesIO()
        with tarfile.open(fileobj=adapter, mode="w:gz") as archive:
            content = b"// synthetic adapter"
            entry = tarfile.TarInfo("js-debug/src/dapDebugServer.js")
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
        self.archives["fixture:js-debug"] = adapter.getvalue()
        pins = {name: {"version": "fixture", "url": "fixture:" + name,
                       "sha256": hashlib.sha256(self.archives["fixture:" + name]).hexdigest()}
                for name in ("debugpy", "js-debug")}
        (self.root / "toolchain/downloads.json").write_text(json.dumps(pins))
        for target, kwargs in (
            ("shutil.which", {"return_value": "/usr/bin/fixture"}),
            ("subprocess.run", {"side_effect": self.npm_install}),
            ("urllib.request.urlopen", {"side_effect": lambda url, **kw: io.BytesIO(self.archives[url])}),
        ):
            patcher = patch("usr.plugins.code_intelligence.helpers.setup." + target, **kwargs)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if target == "subprocess.run":
                self.npm = mock

    def npm_install(self, command, cwd, **kwargs):
        self.assertEqual(command, ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"])
        self.assertTrue(kwargs["check"])
        for name in setup.REQUIRED_FILES[:3]:
            path = Path(cwd) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("// synthetic tool")

    def test_install_and_rerun_reuse_matching_tools_without_downloads(self):
        self.assertTrue(setup.setup_tools()["installed"])
        receipt = self.tools / "receipt.json"
        before = receipt.stat().st_mtime_ns
        with patch.object(setup.urllib.request, "urlopen", side_effect=AssertionError("unexpected download")):
            self.assertTrue(setup.setup_tools()["installed"])
        self.assertEqual(self.npm.call_count, 1)
        self.assertEqual(receipt.stat().st_mtime_ns, before)

    def test_changed_pins_and_missing_entrypoint_require_refresh(self):
        setup.setup_tools()
        lock = self.root / "toolchain/package-lock.json"
        lock.write_text(lock.read_text() + "\n")
        self.assertFalse(setup.status()["installed"])
        self.assertTrue(setup.setup_tools()["installed"])
        (self.tools / setup.REQUIRED_FILES[0]).unlink()
        self.assertFalse(setup.status()["installed"])
        self.assertTrue(setup.setup_tools()["installed"])
        self.assertEqual(self.npm.call_count, 3)

    def test_corrupt_receipt_is_not_installed(self):
        setup.setup_tools()
        (self.tools / "receipt.json").write_text("not json")
        self.assertFalse(setup.status()["installed"])
        self.assertTrue(setup.setup_tools()["installed"])

    def test_checksum_failure_preserves_existing_tools_and_recovery(self):
        setup.setup_tools()
        receipt = (self.tools / "receipt.json").read_bytes()
        journal = self.data / "recovery/workspace/operation.json"
        journal.parent.mkdir(parents=True)
        journal.write_text("originals")
        self.archives["fixture:debugpy"] = b"invalid archive"
        with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
            setup.setup_tools(force=True)
        self.assertEqual((self.tools / "receipt.json").read_bytes(), receipt)
        self.assertEqual(journal.read_text(), "originals")
        self.assertTrue(setup.status()["installed"])
        self.assertEqual({p.name for p in self.data.iterdir()}, {"tools", "recovery"})

    def test_npm_failure_does_not_leave_partial_install(self):
        self.npm.side_effect = subprocess.CalledProcessError(1, ["npm", "ci"])
        with self.assertRaises(subprocess.CalledProcessError):
            setup.setup_tools()
        self.assertFalse(setup.status()["installed"])
        self.assertEqual(list(self.data.iterdir()), [])

    def test_missing_prerequisites_fail_before_downloading(self):
        with patch.object(setup.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Node.js and npm"):
                setup.setup_tools()
        self.npm.assert_not_called()
        self.assertFalse(self.data.exists())

    def test_replacement_failure_rolls_back_previous_tools(self):
        setup.setup_tools()
        receipt = (self.tools / "receipt.json").read_bytes()
        move = shutil.move
        def fail_python(source, target):
            if Path(source).name == "python":
                raise OSError("synthetic disk failure")
            return move(source, target)
        with patch.object(setup.shutil, "move", side_effect=fail_python):
            with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                setup.setup_tools(force=True)
        self.assertEqual((self.tools / "receipt.json").read_bytes(), receipt)
        self.assertTrue(setup.status()["installed"])
        self.assertFalse((self.data / "tools.previous").exists())

    def test_hook_stops_sessions_and_propagates_setup_failure(self):
        events = []
        def install(force=False):
            events.append(("install", force))
            raise RuntimeError("synthetic failure")
        with patch.object(hooks, "shutdown", side_effect=lambda: events.append("stop")), \
             patch.object(hooks.runpy, "run_path", return_value={"setup_tools": install}):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                hooks.install(force=True)
        self.assertEqual(events, ["stop", ("install", True)])

    def test_pre_update_reloads_hooks_and_preserves_recovery_gate(self):
        cache.add(plugins.HOOKS_CACHE_AREA, "code_intelligence", object())
        self.addCleanup(cache.remove, plugins.HOOKS_CACHE_AREA, "code_intelligence")
        with patch.object(hooks, "shutdown"), patch.object(hooks, "DATA", self.data):
            self.assertTrue(hooks.pre_update())
            self.assertFalse(cache.has(plugins.HOOKS_CACHE_AREA, "code_intelligence"))
            journal = self.data / "recovery/workspace/operation.json"
            journal.parent.mkdir(parents=True)
            journal.write_text("originals")
            for action in (hooks.pre_update, hooks.uninstall):
                with self.assertRaisesRegex(RuntimeError, "recovery journals"):
                    action()
            self.assertEqual(journal.read_text(), "originals")

    def test_cleanup_retries_directory_race_but_not_permission_errors(self):
        with patch.object(setup.shutil, "rmtree", side_effect=[OSError(errno.ENOTEMPTY, "metadata race"), None]) as remove, \
             patch.object(setup.time, "sleep"):
            setup.remove_tree(self.tools)
            self.assertEqual(remove.call_count, 2)
        for error, calls in ((errno.ENOTEMPTY, 3), (errno.EACCES, 1)):
            with patch.object(setup.shutil, "rmtree", side_effect=OSError(error, "synthetic failure")) as remove, \
                 patch.object(setup.time, "sleep"):
                with self.assertRaises(OSError):
                    setup.remove_tree(self.tools)
                self.assertEqual(remove.call_count, calls)


if __name__ == "__main__":
    unittest.main()
