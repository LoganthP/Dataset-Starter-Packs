"""Build one standalone ZIP per pack into dist/ (attached to GitHub releases).

    python scripts/package_starters.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EXCLUDE_DIRS = {"data", "outputs", ".venv", "venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints", ".ruff_cache"}
GITIGNORE = "data/\noutputs/\n.venv/\n__pycache__/\n.ipynb_checkpoints/\n"


def package(pack: Path) -> Path:
    DIST.mkdir(exist_ok=True)
    target = DIST / f"{pack.name}-starter.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(pack.rglob("*")):
            rel = path.relative_to(pack)
            if path.is_file() and not (set(rel.parts[:-1]) & EXCLUDE_DIRS) and path.suffix != ".pyc":
                z.write(path, f"{pack.name}/{rel.as_posix()}")
        z.writestr(f"{pack.name}/.gitignore", GITIGNORE)
    return target


if __name__ == "__main__":
    packs = sorted(p.parent for p in (ROOT / "packs").glob("*/pack.json"))
    for pack in packs:
        out = package(pack)
        print(f"{out.relative_to(ROOT)}  {out.stat().st_size / 1024:.0f} KB")
    sys.exit(0 if packs else 1)
