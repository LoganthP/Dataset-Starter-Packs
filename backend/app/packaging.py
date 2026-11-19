"""Build a standalone starter ZIP for one pack (same rules as scripts/package_starters.py)."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {"data", "outputs", ".venv", "venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints", ".ruff_cache"}


def iter_pack_files(pack: Path):
    for path in sorted(pack.rglob("*")):
        rel = path.relative_to(pack)
        if path.is_file() and not (set(rel.parts[:-1]) & EXCLUDE_DIRS) and not path.name.endswith(".pyc"):
            yield path, rel


def build_zip(pack: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, rel in iter_pack_files(pack):
            z.write(path, f"{pack.name}/{rel.as_posix()}")
        z.writestr(f"{pack.name}/.gitignore", "data/\noutputs/\n.venv/\n__pycache__/\n.ipynb_checkpoints/\n")
    return buf.getvalue()
