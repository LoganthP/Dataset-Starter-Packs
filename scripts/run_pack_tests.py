"""Run each pack's tests in its own pytest process (packs share module names on purpose).

    python scripts/run_pack_tests.py                 # all packs, in place
    python scripts/run_pack_tests.py --isolated      # copy each pack to a temp dir first (proves independence)
    python scripts/run_pack_tests.py --notebooks     # also execute every starter.ipynb in sample mode
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns("data", "outputs", ".venv", "__pycache__", ".pytest_cache", ".ipynb_checkpoints")


def run(cmd: list[str], cwd: Path) -> bool:
    print(f"\n$ {' '.join(cmd)}   (in {cwd})", flush=True)
    return subprocess.run(cmd, cwd=cwd).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--notebooks", action="store_true")
    parser.add_argument("packs", nargs="*")
    args = parser.parse_args()
    packs = sorted(p.parent for p in (ROOT / "packs").glob("*/pack.json") if not args.packs or p.parent.name in args.packs)
    failed = []
    for pack in packs:
        with tempfile.TemporaryDirectory() as tmp:
            where = pack
            if args.isolated:
                where = Path(tmp) / pack.name
                shutil.copytree(pack, where, ignore=IGNORE)
            ok = run([sys.executable, "-m", "pytest", "-q", "tests"], where)
            if ok and args.notebooks:
                ok = run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "starter.ipynb",
                          "--output", str(Path(tmp) / "executed.ipynb"), "--ExecutePreprocessor.timeout=600"], where)
            if not ok:
                failed.append(pack.name)
    print("\n" + ("All packs passed." if not failed else f"FAILED: {', '.join(failed)}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
