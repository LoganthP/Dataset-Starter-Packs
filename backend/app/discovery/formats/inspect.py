"""Inspection only: for formats no handler analyzes yet. Reports the detected type of every file, sizes,
any metadata that can be read cheaply, and the next useful action. Labelled as inspection, not analysis."""
from __future__ import annotations

from .registry import Handler, Job, describe, register, sniff_path

NEXT = {
    "netcdf": "This NetCDF file couldn't be turned into a table (no variables with a shared length or grid). Export a variable to CSV "
              "or Parquet to analyze it here.",
    "hdf5": "This HDF5 file couldn't be turned into a table. Export the dataset you need to CSV or Parquet.",
    "7z": "7-Zip archives can't be opened on this deployment. Extract it and upload the data files (or a ZIP).",
    "rar": "RAR archives can't be opened here. Extract it and upload the data files (or a ZIP).",
    "pdf": "This is documentation, not data. Open the source for the data files.",
    "html": "The source returned a web page instead of a file. It probably needs sign-in: open the source and download the file.",
}


class Inspect(Handler):
    key = "inspect"
    label = "Inspection only"
    types = ()
    description = "Detected type, files and metadata, with the next useful action. No analysis."

    def score(self, members):
        return 0.01

    def select(self, members, *, sample, params):
        return []

    def analyze(self, job: Job) -> dict:
        members = job.members or [{"name": p.name, "size": p.stat().st_size, "type": sniff_path(p)} for p in job.paths]
        kinds = describe(members)["types"]
        main = kinds[0]["type"] if kinds else "unknown"
        files = sorted(members, key=lambda m: -(m.get("size") or 0))[:200]
        reason = job.extra.get("fallback_reason")
        hint = NEXT.get(main) or ("Choose the files to analyze from the list, or pick an analysis type." if len(members) > 1 else
                                  "No analyzer for this type yet. Open the source for another format.")
        if reason:
            hint = f"{reason} {hint}"
        return {"kind": "inspection", "coverage": "inspection", "sample_method": None, "rows_total": None, "rows_analyzed": 0,
                "columns": [], "rows_skipped": 0, "skip_reasons": [], "duplicate_rows": None, "duplicate_pct": None, "missing_pct": 0.0,
                "date_coverage": None, "preview": [], "insights": None,
                "inspection": {"detected": main, "types": kinds, "files": files, "file_count": len(members),
                               "bytes": sum(m.get("size") or 0 for m in members), "next": hint}}


register(Inspect())
