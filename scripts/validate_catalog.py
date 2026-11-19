"""Validate every packs/*/pack.json and keep the README catalog in sync.

    python scripts/validate_catalog.py          # check only (CI)
    python scripts/validate_catalog.py --write  # regenerate the README catalog table
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
README = ROOT / "README.md"
START, END = "<!-- catalog:start -->", "<!-- catalog:end -->"

REQUIRED = {
    "slug": str, "title": str, "tagline": str, "provider": str, "difficulty": str, "task_type": str, "skills": list,
    "accent": str, "question": str, "audience": str, "prerequisites": list, "estimated_time": str, "expected_runtime": dict,
    "source": dict, "fixture": bool, "last_source_check": str, "lesson": dict, "outputs": list, "parameters": list,
    "challenges": list, "entrypoints": dict,
}
SOURCE_REQUIRED = ["name", "publisher", "url", "dataset_page", "access_method", "license", "license_url", "citation", "files"]
PACK_FILES = ["README.md", "data-dictionary.md", "requirements.txt", "starter.ipynb", "load_data.py", "analysis.py",
              "fixtures", "tests", "assets/preview.png"]
PROVIDERS = {"NASA", "UCI", "Kaggle"}
DIFFICULTY = {"beginner", "intermediate", "advanced"}
ACCESS = {"direct-download", "api", "kaggle"}


def validate_pack(path: Path) -> list[str]:
    errs: list[str] = []
    slug = path.name
    try:
        meta = json.loads((path / "pack.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{slug}: pack.json unreadable: {exc}"]
    for key, kind in REQUIRED.items():
        if key not in meta:
            errs.append(f"{slug}: missing '{key}'")
        elif not isinstance(meta[key], kind):
            errs.append(f"{slug}: '{key}' should be {kind.__name__}")
    if errs:
        return errs
    if meta["slug"] != slug:
        errs.append(f"{slug}: slug '{meta['slug']}' does not match folder name")
    if meta["provider"] not in PROVIDERS:
        errs.append(f"{slug}: provider must be one of {sorted(PROVIDERS)}")
    if meta["difficulty"] not in DIFFICULTY:
        errs.append(f"{slug}: difficulty must be one of {sorted(DIFFICULTY)}")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", meta["accent"]):
        errs.append(f"{slug}: accent must be a hex colour")
    for key in SOURCE_REQUIRED:
        if key not in meta["source"]:
            errs.append(f"{slug}: source.{key} missing")
    if meta["source"].get("access_method") not in ACCESS:
        errs.append(f"{slug}: source.access_method must be one of {sorted(ACCESS)}")
    for url_key in ("url", "dataset_page", "license_url"):
        if not str(meta["source"].get(url_key, "")).startswith("https://"):
            errs.append(f"{slug}: source.{url_key} must be an https URL")
    try:
        checked = dt.date.fromisoformat(meta["last_source_check"])
        if (dt.date.today() - checked).days > 180:
            errs.append(f"{slug}: last_source_check is older than 180 days - re-verify the source")
    except ValueError:
        errs.append(f"{slug}: last_source_check must be YYYY-MM-DD")
    if len(meta["challenges"]) < 2:
        errs.append(f"{slug}: add at least two extension challenges")
    for p in meta["parameters"]:
        if p.get("type") == "select" and p.get("default") not in p.get("options", []):
            errs.append(f"{slug}: parameter {p.get('name')} default not in options")
    for rel in PACK_FILES:
        if not (path / rel).exists():
            errs.append(f"{slug}: missing {rel}")
    for name in meta["entrypoints"].values():
        if not (path / name).exists():
            errs.append(f"{slug}: entrypoint {name} not found")
    # Relative links in the pack README must resolve inside the pack.
    for link in re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", (path / "README.md").read_text(encoding="utf-8")):
        if not (path / link).exists():
            errs.append(f"{slug}: README links to missing file {link}")
    # Packs must not import from outside their own folder.
    for py in list(path.glob("*.py")) + list((path / "tests").glob("*.py")):
        if re.search(r"^\s*(from|import)\s+(backend|scripts|packs)\b", py.read_text(encoding="utf-8"), re.M):
            errs.append(f"{slug}: {py.name} imports repo code; packs must be self-contained")
    return errs


def validate_records(pack_slugs: set[str]) -> list[str]:
    """catalog/records/*.json must match the DatasetRecord schema; every pack needs exactly one record."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.discovery.schema import CONCEPTS, normalize  # noqa: E402

    errs, linked = [], []
    for path in sorted((ROOT / "catalog" / "records").glob("*.json")):
        try:
            rec = normalize(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            errs.append(f"catalog/{path.name}: {exc}".splitlines()[0])
            continue
        name = f"catalog/{path.name}"
        if path.stem != rec["id"]:
            errs.append(f"{name}: file name must equal id")
        if rec["origin"] not in ("seed", "pack"):
            errs.append(f"{name}: committed records must have origin seed or pack")
        if rec["reviewStatus"] == "reviewed" and not rec.get("lastVerifiedAt"):
            errs.append(f"{name}: reviewed records need lastVerifiedAt")
        for f in rec["fields"]:
            for c in f["concepts"]:
                if c not in CONCEPTS:
                    errs.append(f"{name}: field {f['name']} has unknown concept {c}")
        for claim in ("formats", "access", "license"):
            if rec[claim]["status"] != "unknown" and not rec[claim].get("evidence"):
                errs.append(f"{name}: {claim} is {rec[claim]['status']} but has no evidence")
        if rec.get("packId"):
            linked.append(rec["packId"])
            if rec["packId"] not in pack_slugs:
                errs.append(f"{name}: packId {rec['packId']} does not exist")
    for slug in pack_slugs:
        if linked.count(slug) != 1:
            errs.append(f"pack {slug} must be linked from exactly one catalog record (found {linked.count(slug)})")
    return errs


def catalog_table(metas: list[dict]) -> str:
    order = {"uci-bike-demand": 0, "nasa-bengaluru-weather": 1, "nasa-exoplanets": 2, "uci-dry-bean": 3, "kaggle-olist-delivery": 4}
    rows = ["| Preview | Pack | What you'll build | Level | Links |", "|---|---|---|---|---|"]
    for m in sorted(metas, key=lambda m: order.get(m["slug"], 99)):
        s = m["slug"]
        rows.append(
            f"| <img src=\"packs/{s}/assets/preview.png\" width=\"220\" alt=\"{m['title']} preview\"> "
            f"| **{m['title']}**<br>{m['provider']} · {m['task_type']} "
            f"| {m['tagline']}<br>**Trap:** {m['lesson']['title']} "
            f"| {m['difficulty']}<br>{m['estimated_time']} "
            f"| [Open notebook](packs/{s}/starter.ipynb)<br>[Download starter](../../releases/latest/download/{s}-starter.zip)<br>"
            f"[View dataset]({m['source']['dataset_page']}) |"
        )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="rewrite the README catalog section")
    args = parser.parse_args()
    pack_dirs = sorted(p.parent for p in PACKS.glob("*/pack.json"))
    errors = [e for d in pack_dirs for e in validate_pack(d)]
    metas = [json.loads((d / "pack.json").read_text(encoding="utf-8")) for d in pack_dirs]
    slugs = [m.get("slug") for m in metas]
    if len(set(slugs)) != len(slugs):
        errors.append("duplicate slugs")
    errors += validate_records(set(slugs))

    readme = README.read_text(encoding="utf-8")
    if START in readme and END in readme:
        table = catalog_table(metas)
        current = readme.split(START, 1)[1].split(END, 1)[0].strip()
        if current != table:
            if args.write:
                README.write_text(readme.split(START)[0] + f"{START}\n{table}\n{END}" + readme.split(END, 1)[1], encoding="utf-8")
                print("README catalog updated.")
            else:
                errors.append("README catalog is out of date - run: python scripts/validate_catalog.py --write")
    else:
        errors.append(f"README.md must contain {START} and {END}")

    for e in errors:
        print(f"ERROR {e}")
    n_records = len(list((ROOT / "catalog" / "records").glob("*.json")))
    print(f"{len(pack_dirs)} packs and {n_records} catalog records checked, {len(errors)} problem(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
