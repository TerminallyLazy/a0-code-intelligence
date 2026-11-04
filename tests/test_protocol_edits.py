import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from usr.plugins.code_intelligence.helpers.protocol import Peer, ProtocolError, read_frame
from usr.plugins.code_intelligence.helpers.workspace import apply_text_edits, offset, project_file, snapshot
from usr.plugins.code_intelligence.helpers.edits import Proposals, replace_file


class Framing(unittest.IsolatedAsyncioTestCase):
    async def test_utf8_byte_length_and_fragmented_frames(self):
        reader = asyncio.StreamReader()
        message = {"text": "雪😀"}
        body = json.dumps(message, ensure_ascii=False).encode()
        async def feed():
            for b in f"Content-Length: {len(body)}\r\n\r\n".encode() + body:
                reader.feed_data(bytes([b]))
                await asyncio.sleep(0)
        task = asyncio.create_task(feed())
        self.assertEqual(await read_frame(reader), message)
        await task

    async def test_rejects_malformed_oversized_and_duplicate_lengths(self):
        for data in [b"Content-Length: 9000000\r\n\r\n", b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
                     b"Content-Length: -1\r\n\r\n", b"Content-Length: 2\r\n\r\n[]", b"Bad\r\n\r\n"]:
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            with self.assertRaises(ProtocolError):
                await read_frame(reader)

    async def test_crashed_process_fails_waiting_request_and_cleans_up(self):
        peer = Peer("lsp")
        await peer.start([sys.executable, "-c", "import time; time.sleep(.1)"], "/tmp")
        try:
            with self.assertRaises(ProtocolError):
                await peer.request("example", timeout=3)
        finally:
            await peer.close()
        self.assertIsNotNone(peer.proc.returncode)

    async def test_cancellation_removes_pending_request(self):
        peer = Peer("lsp")
        await peer.start([sys.executable, "-c", "import time; time.sleep(60)"], "/tmp")
        try:
            task = asyncio.create_task(peer.request("example", timeout=10))
            await asyncio.sleep(.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(peer.pending)
        finally:
            await peer.close()

    async def test_private_lease_eof_terminates_owned_process(self):
        with tempfile.TemporaryDirectory() as d:
            pidfile = Path(d, "pid")
            peer = Peer("lsp")
            await peer.start([sys.executable, "-c", "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)"], d)
            try:
                for _ in range(100):
                    if pidfile.exists(): break
                    await asyncio.sleep(.02)
                child = int(pidfile.read_text())
                os.close(peer.lease)
                peer.lease = None
                await asyncio.wait_for(peer.proc.wait(), 3)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
            finally:
                await peer.close()


class EditContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = self.root / "a.py"
        self.b = self.root / "b.py"
        self.a.write_text("thing = 1\n")
        self.b.write_text("from a import thing\n")
        self.server = SimpleNamespace(documents={}, encoding="utf-16", generation=1)
        self.proposals = Proposals(self.root, "owner", self.root / "journals")

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, path, start, end, text):
        return {"changes": {path.as_uri(): [{"range": {"start": {"line": 0, "character": start},
                                                        "end": {"line": 0, "character": end}}, "newText": text}]}}

    def test_unicode_and_crlf_coordinates(self):
        self.assertEqual(offset("😀x\r\ny", {"line": 0, "character": 2}), 1)
        self.assertEqual(offset("😀x\r\ny", {"line": 1, "character": 1}), 5)
        self.assertEqual(offset("😀x", {"line": 0, "character": 4}, "utf-8"), 1)
        with self.assertRaises(ValueError): offset("😀x", {"line": 0, "character": 1})

    def test_overlapping_edits_rejected(self):
        edits = self.edit(self.a, 0, 5, "name")["changes"][self.a.as_uri()]
        with self.assertRaises(ValueError): apply_text_edits("thing = 1\n", edits * 2, "utf-16")

    def test_stale_and_restarted_server_cannot_apply(self):
        proposal = self.proposals.create(self.edit(self.a, 0, 5, "name"), snapshot(self.root), self.server, "rename")
        with self.assertRaises(ValueError): self.proposals.apply(proposal["id"], {2})
        self.a.write_text("human = 2\n")
        with self.assertRaises(ValueError): self.proposals.apply(proposal["id"], {1})
        self.assertEqual(self.a.read_text(), "human = 2\n")

    def test_success_preserves_mode_and_consumes_proposal(self):
        self.a.chmod(0o751)
        p = self.proposals.create(self.edit(self.a, 0, 5, "name"), snapshot(self.root), self.server, "rename")
        self.proposals.apply(p["id"], {1})
        self.assertEqual(self.a.read_text(), "name = 1\n")
        self.assertEqual(self.a.stat().st_mode & 0o777, 0o751)
        with self.assertRaises(ValueError): self.proposals.apply(p["id"], {1})

    def test_resource_operations_and_symlink_escape_rejected(self):
        with self.assertRaises(ValueError):
            self.proposals.create({"documentChanges": [{"kind": "delete", "uri": self.a.as_uri()}]}, snapshot(self.root), self.server, "delete")
        link = self.root / "outside.py"
        link.symlink_to("/etc/passwd")
        with self.assertRaises(ValueError): project_file(self.root, str(link))

    def test_multi_file_failure_rolls_back_without_touching_human_change(self):
        edit = self.edit(self.a, 0, 5, "name")
        edit["changes"].update(self.edit(self.b, 14, 19, "name")["changes"])
        p = self.proposals.create(edit, snapshot(self.root), self.server, "rename")
        def fail(path, content):
            if path == self.b:
                self.a.write_text("human concurrent edit\n")
                raise OSError("synthetic write failure")
            replace_file(path, content)
        with patch("usr.plugins.code_intelligence.helpers.edits.replace_file", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "recovery_required"):
                self.proposals.apply(p["id"], {1})
        self.assertEqual(self.a.read_text(), "human concurrent edit\n")
        self.assertEqual(self.b.read_text(), "from a import thing\n")
        self.assertTrue(list((self.root / "journals").glob("*.json")))


if __name__ == "__main__": unittest.main()
