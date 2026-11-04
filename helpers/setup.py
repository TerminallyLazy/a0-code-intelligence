"""Pinned, plugin-owned setup called by the installation lifecycle hook."""
from __future__ import annotations

import hashlib
import errno
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".runtime"
REQUIRED_FILES = (
    "node_modules/pyright/langserver.index.js",
    "node_modules/typescript/lib/typescript.js",
    "node_modules/typescript-language-server/lib/cli.mjs",
    "python/debugpy/adapter/__main__.py",
    "js-debug/src/dapDebugServer.js",
)


def remove_tree(path):
    # Host-mounted Docker folders can gain metadata files during removal.
    # Retry that race only; permission and other filesystem errors still fail.
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            if exc.errno != errno.ENOTEMPTY or attempt == 2:
                raise
            time.sleep(0.1 * (attempt + 1))


def setup_tools(force=False):
    if not force and status()["installed"]:
        return status()
    if not shutil.which("npm") or not shutil.which("node"):
        raise RuntimeError("Code Intelligence installation requires Node.js and npm in the Agent Zero runtime")
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = json.loads((ROOT / "toolchain/downloads.json").read_text())
    with tempfile.TemporaryDirectory(dir=DATA) as temporary:
        stage = Path(temporary)
        for name in ("package.json", "package-lock.json"):
            shutil.copy2(ROOT / "toolchain" / name, stage / name)
        subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                       cwd=stage, check=True, timeout=240, capture_output=True)
        for name, item in lock.items():
            archive = stage / (name + ".archive")
            with urllib.request.urlopen(item["url"], timeout=60) as source, archive.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Checksum mismatch: {name}")
            if name == "debugpy":
                dest = stage / "python"
                dest.mkdir()
                with zipfile.ZipFile(archive) as package:
                    for entry in package.infolist():
                        target = (dest / entry.filename).resolve()
                        if not target.is_relative_to(dest):
                            raise ValueError("Archive path escapes setup directory")
                    package.extractall(dest)
            else:
                with tarfile.open(archive) as package:
                    package.extractall(stage, filter="data")
        if not all((stage / name).is_file() for name in REQUIRED_FILES):
            raise RuntimeError("Code Intelligence toolchain is incomplete; existing tools were preserved")
        # All downloads validated before replacing the plugin-owned toolchain.
        tools = DATA / "tools"
        previous = DATA / "tools.previous"
        if previous.exists():
            remove_tree(previous)
        if tools.exists():
            tools.rename(previous)
        try:
            tools.mkdir()
            for name in ("node_modules", "python", "js-debug", "package-lock.json"):
                shutil.move(str(stage / name), tools / name)
            receipt = {"downloads": lock, "npm_lock_sha256": hashlib.sha256((tools / "package-lock.json").read_bytes()).hexdigest()}
            (tools / "receipt.json").write_text(json.dumps(receipt, indent=2))
        except BaseException:
            if tools.exists():
                remove_tree(tools)
            if previous.exists():
                previous.rename(tools)
            raise
        if previous.exists():
            remove_tree(previous)
    return status()


def status():
    tools = DATA / "tools"
    downloads = json.loads((ROOT / "toolchain/downloads.json").read_text())
    lock_hash = hashlib.sha256((ROOT / "toolchain/package-lock.json").read_bytes()).hexdigest()
    expected = {"downloads": downloads, "npm_lock_sha256": lock_hash}
    try:
        installed = (json.loads((tools / "receipt.json").read_text()) == expected
                     and hashlib.sha256((tools / "package-lock.json").read_bytes()).hexdigest() == lock_hash
                     and all((tools / name).is_file() for name in REQUIRED_FILES))
    except (OSError, ValueError):
        installed = False
    return {"installed": installed, "location": str(tools),
            "versions": downloads,
            "npm": json.loads((ROOT / "toolchain/package.json").read_text())["dependencies"]}


if __name__ == "__main__":
    print(json.dumps(setup_tools(), indent=2))
