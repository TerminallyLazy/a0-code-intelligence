from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import uuid

from .workspace import apply_text_edits, digest, project_file, read_text


def replace_file(path: Path, content: str):
    original = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=".code-intelligence-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
            os.fchmod(stream.fileno(), stat.S_IMODE(original.st_mode))
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                os.fchown(stream.fileno(), original.st_uid, original.st_gid)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Proposals:
    def __init__(self, root, owner, journal_dir):
        self.root, self.owner, self.journal_dir = Path(root), owner, Path(journal_dir)
        self.items = {}

    def create(self, workspace_edit, before, server, title):
        if not isinstance(workspace_edit, dict):
            raise ValueError("Server did not return a WorkspaceEdit")
        if workspace_edit.get("changeAnnotations"):
            raise ValueError("Annotated edits require an unsupported confirmation protocol")
        grouped = {}
        for uri, edits in workspace_edit.get("changes", {}).items():
            grouped[uri] = list(edits)
        for change in workspace_edit.get("documentChanges", []):
            if "kind" in change:
                raise ValueError("File create, rename and delete operations are not supported")
            document = change["textDocument"]
            uri = document["uri"]
            expected = document.get("version")
            known = server.documents.get(uri)
            if expected is not None and (not known or known["version"] != expected):
                raise ValueError("WorkspaceEdit has a stale document version")
            if uri in grouped:
                raise ValueError("WorkspaceEdit specifies a document more than once")
            grouped[uri] = change["edits"]
        if not grouped or len(grouped) > 100:
            raise ValueError("Edit must affect between 1 and 100 existing files")
        changes = []
        seen = set()
        for uri, edits in grouped.items():
            path = project_file(self.root, uri)
            if path in seen:
                raise ValueError("Duplicate canonical file in edit")
            seen.add(path)
            old = before.get(str(path))
            if old is None or read_text(path) != old:
                raise ValueError("File changed during the language-server request; propose again")
            new = apply_text_edits(old, edits, server.encoding)
            if new == old:
                continue
            changes.append({"path": str(path), "before": old, "after": new,
                            "before_digest": digest(old), "after_digest": digest(new)})
        if not changes:
            raise ValueError("Proposal contains no changes")
        now = time.monotonic()
        self.items = {k: v for k, v in self.items.items() if now - v["created"] < 600}
        if len(self.items) >= 20:
            self.items.pop(next(iter(self.items)))
        proposal = {"id": uuid.uuid4().hex, "owner": self.owner, "title": title[:160], "created": now,
                    "server_generation": server.generation, "changes": changes, "status": "proposed"}
        self.items[proposal["id"]] = proposal
        return self.public(proposal)

    def public(self, proposal):
        changes = []
        for change in proposal["changes"]:
            name = str(Path(change["path"]).relative_to(self.root))
            diff = "".join(difflib.unified_diff(change["before"].splitlines(True), change["after"].splitlines(True),
                                               fromfile=name, tofile=name))
            changes.append({"path": name, "before_digest": change["before_digest"],
                            "after_digest": change["after_digest"], "diff": diff[:16000], "truncated": len(diff) > 16000})
        return {"id": proposal["id"], "title": proposal["title"], "status": proposal["status"],
                "files": changes, "expires_in_seconds": max(0, int(600 - time.monotonic() + proposal["created"]))}

    def apply(self, ident, server_generations):
        proposal = self.items.get(ident)
        if not proposal or proposal["owner"] != self.owner or proposal["status"] != "proposed":
            raise ValueError("Unknown or already consumed proposal")
        if time.monotonic() - proposal["created"] > 600 or proposal["server_generation"] not in server_generations:
            raise ValueError("Proposal expired or its language server restarted")
        for change in proposal["changes"]:
            path = project_file(self.root, change["path"])
            if digest(read_text(path)) != change["before_digest"]:
                raise ValueError("Proposal is stale; files changed since preview")
        self.journal_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        journal = self.journal_dir / (ident + ".json")
        record = {"owner": self.owner, "status": "prepared", "changes": proposal["changes"]}
        fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        written = []
        try:
            for change in proposal["changes"]:
                path = project_file(self.root, change["path"])
                if digest(read_text(path)) != change["before_digest"]:
                    raise ValueError("Concurrent edit detected while applying proposal")
                replace_file(path, change["after"])
                written.append(change)
        except Exception as exc:
            conflicts = []
            for change in reversed(written):
                path = Path(change["path"])
                try:
                    if digest(read_text(path)) != change["after_digest"]:
                        conflicts.append(change["path"])
                    else:
                        replace_file(path, change["before"])
                except Exception:
                    conflicts.append(change["path"])
            proposal["status"] = "recovery_required" if conflicts else "rolled_back"
            record.update(status=proposal["status"], conflicts=conflicts)
            journal.write_text(json.dumps(record))
            if not conflicts:
                journal.unlink()
            raise ValueError(f"Apply failed ({type(exc).__name__}); {proposal['status']}; recovery journal: {journal}") from exc
        proposal["status"] = "applied"
        # Successful edits need no retained copy of project source.
        journal.unlink()
        return {"status": "applied", "proposal_id": ident, "paths": [c["path"] for c in written]}
