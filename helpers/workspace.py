from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXCLUDED = {".git", "node_modules", ".venv", "venv", "__pycache__", ".runtime", ".tox", ".mypy_cache"}
SUFFIXES = {".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc", ".yaml", ".yml"}
MAX_FILE = 2 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def project_file(root: Path, value: str, exists=True):
    if value.startswith("file:"):
        parsed = urlsplit(value)
        if parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
            raise ValueError("Only local file URIs are supported")
        value = unquote(parsed.path)
    elif "://" in value:
        raise ValueError("Only workspace files are supported")
    candidate = Path(value)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("File is outside the active workspace")
    if any(part in EXCLUDED for part in path.relative_to(root).parts):
        raise ValueError("File is inside an excluded directory")
    if exists and not path.is_file():
        raise ValueError("Workspace file does not exist")
    return path


def read_text(path: Path):
    if path.stat().st_size > MAX_FILE:
        raise ValueError("File exceeds the 2 MiB limit")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE or b"\0" in raw:
        raise ValueError("File is oversized or binary")
    return raw.decode("utf-8")


def snapshot(root: Path, extra_suffixes=()):
    result = {}
    size = 0
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not Path(base, d).is_symlink())
        for name in sorted(names):
            path = Path(base, name)
            if path.suffix not in SUFFIXES | set(extra_suffixes) or path.is_symlink():
                continue
            text = read_text(path)
            size += len(text.encode())
            if len(result) >= 5000 or size > 64 * 1024 * 1024:
                raise ValueError("Workspace exceeds semantic-edit snapshot limit (5000 files / 64 MiB)")
            result[str(path)] = text
    return result


def offset(text: str, position: dict, encoding="utf-16"):
    line, column = position.get("line"), position.get("character")
    if type(line) is not int or type(column) is not int or min(line, column) < 0:
        raise ValueError("Invalid LSP position")
    lines = text.splitlines(keepends=True)
    if not lines or text.endswith(("\n", "\r")):
        lines.append("")
    if line >= len(lines):
        raise ValueError("Position is past the end of the file")
    content = lines[line].rstrip("\r\n")
    units = 0
    for index, char in enumerate(content):
        if units == column:
            return sum(len(s) for s in lines[:line]) + index
        units += len(char.encode("utf-16-le")) // 2 if encoding == "utf-16" else len(char.encode("utf-8"))
        if units > column:
            raise ValueError("Position splits an encoded character")
    if units != column:
        raise ValueError("Column is past the end of the line")
    return sum(len(s) for s in lines[:line]) + len(content)


def apply_text_edits(text, edits, encoding):
    converted = []
    for i, edit in enumerate(edits):
        if edit.get("insertTextFormat", 1) != 1 or not isinstance(edit.get("newText"), str):
            raise ValueError("Only plain text edits are supported")
        start = offset(text, edit["range"]["start"], encoding)
        end = offset(text, edit["range"]["end"], encoding)
        if end < start:
            raise ValueError("Reversed edit range")
        converted.append((start, end, i, edit["newText"]))
    ordered = sorted(converted)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("Overlapping text edits")
    for start, end, _, replacement in reversed(ordered):
        text = text[:start] + replacement + text[end:]
    return text
