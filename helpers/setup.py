"""Explicit, pinned setup. Importing or enabling the plugin never installs tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".runtime"


def setup_tools():
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
        # All downloads validated before replacing the plugin-owned toolchain.
        tools = DATA / "tools"
        previous = DATA / "tools.previous"
        if previous.exists():
            shutil.rmtree(previous)
        if tools.exists():
            tools.rename(previous)
        tools.mkdir()
        try:
            for name in ("node_modules", "python", "js-debug", "package-lock.json"):
                shutil.move(str(stage / name), tools / name)
            receipt = {"downloads": lock, "npm_lock_sha256": hashlib.sha256((tools / "package-lock.json").read_bytes()).hexdigest()}
            (tools / "receipt.json").write_text(json.dumps(receipt, indent=2))
        except BaseException:
            shutil.rmtree(tools)
            if previous.exists():
                previous.rename(tools)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    return status()


def status():
    tools = DATA / "tools"
    return {"installed": (tools / "receipt.json").is_file(), "location": str(tools),
            "versions": json.loads((ROOT / "toolchain/downloads.json").read_text()),
            "npm": json.loads((ROOT / "toolchain/package.json").read_text())["dependencies"]}


if __name__ == "__main__":
    print(json.dumps(setup_tools(), indent=2))
