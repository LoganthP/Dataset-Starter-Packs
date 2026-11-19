"""Tables: CSV, TSV, JSON, Parquet, Excel. Profiled with DuckDB (analysis.analyze), plus a trajectory
section when the table holds positions over time (x/y/z + a time column), e.g. orbit state vectors."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .registry import TABULAR, Handler, Job, register

MANEUVER_LABELS = {0: "No maneuver", 1: "East-West", 2: "North-South", 3: "Longitude shift start", 4: "Longitude shift end", 5: "Graveyard"}


class Tabular(Handler):
    key = "tabular"
    label = "Table"
    types = TABULAR
    description = "Rows and columns: schema, missing values, distributions and charts."

    def score(self, members: list[dict]) -> float:
        tab = [m for m in members if m["type"] in TABULAR]
        if not tab:
            return 0.0
        # A folder of images with one labels.csv is an image dataset, not a table.
        return max(0.35, sum(m["size"] for m in tab) / max(1, sum(m["size"] for m in members)))

    def select(self, members: list[dict], *, sample: bool, params: dict) -> list[dict]:
        tab = [m for m in members if m["type"] in TABULAR]
        if params.get("members"):
            return tab
        if not tab:
            return []
        main = max(tab, key=lambda m: m["size"])
        meta = [m for m in tab if m is not main and _pair_prefix(m["name"]) and _pair_prefix(m["name"]) == _pair_prefix(main["name"])]
        return [main, *meta[:1]]

    def analyze(self, job: Job) -> dict:
        from ..analysis import analyze as profile
        from ..dataimport import _ext_format, xlsx_sheets, xlsx_to_csv

        paths = sorted(job.paths, key=lambda p: ("metadata" in p.name.lower(), -p.stat().st_size))
        main, meta = paths[0], (paths[1] if len(paths) > 1 else job.extra.get("pair_path"))
        fmt = _ext_format(main.name) or ("parquet" if main.read_bytes()[:4] == b"PAR1" else "csv")
        worksheet = None
        if fmt == "xlsx":
            sheets = xlsx_sheets(main)
            sheet = job.params.get("sheet") if job.params.get("sheet") in sheets else sheets[0]
            job.log(f"Reading worksheet '{sheet}' of {main.name} ({len(sheets)} sheet{'s' if len(sheets) != 1 else ''})")
            worksheet = {"file": _rel(main, job.root), "sheet": sheet, "sheets": sheets}
            main, fmt = xlsx_to_csv(main, sheet), "csv"
        job.log(f"Profiling {fmt.upper()} with DuckDB: {main.name}")
        report = profile(main, fmt, row_limit=job.extra.get("row_limit"), known_total=job.known_total, partial=job.partial,
                         method=job.method, deadline=job.deadline, on_charts=job.on_charts)
        report["kind"] = "table"
        report["analyzed_file"] = (worksheet or {}).get("file") or _rel(main, job.root)
        if worksheet:
            report["worksheet"] = worksheet
        report["file_format"] = fmt
        traj = trajectory(main, fmt, report)
        if traj:
            report["kind"] = "trajectory"
            report["trajectory"] = traj
            job.log(f"Trajectory: {traj['points_total']:,} epochs, {len(traj['maneuvers'])} maneuver markers")
        if meta is not None and Path(meta).exists():
            report["pair"] = pair_metadata(Path(meta), main.name)
            job.log(f"Paired metadata: {Path(meta).name}")
        return report


def _rel(p: Path, root: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.name


def _pair_prefix(name: str) -> str | None:
    """<timestamp>_<pid> from state_vectors/<p>_state_vectors.parquet and metadata/<p>_metadata.parquet."""
    m = re.match(r"(.+?)_(state_vectors|metadata)\.parquet$", name.rsplit("/", 1)[-1])
    return m.group(1) if m else None


def _col(cols: list[str], *names: str) -> str | None:
    low = {c.lower(): c for c in cols}
    return next((low[n] for n in names if n in low), None)


def trajectory(path: Path, fmt: str, report: dict) -> dict | None:
    cols = [c["name"] for c in report["columns"]]
    x, y, z = _col(cols, "x", "pos_x", "r_x", "position_x"), _col(cols, "y", "pos_y", "r_y", "position_y"), _col(cols, "z", "pos_z", "r_z", "position_z")
    t = _col(cols, "time_mjd", "mjd", "epoch", "time", "t", "timestamp", "datetime", "utc")
    if not (x and y and z and t):
        return None
    import duckdb

    from ..dataimport import _reader

    q = lambda c: '"' + c.replace('"', '""') + '"'  # noqa: E731
    con = duckdb.connect()
    try:
        con.execute(f"create view s as select * from {_reader(path, fmt)}")
        n = con.execute(f"select count(*) from s where {q(x)} is not null and {q(t)} is not null").fetchone()[0]
        if not n:
            return None
        step = max(1, n // 1200)
        extra = [c for c in ("semi_major_axis", "eccentricity", "inclination", "RA", "DEC") if c in cols][:3]
        sel = ", ".join(q(c) for c in [t, x, y, z, *extra])
        rows = con.execute(f"select {sel} from (select *, row_number() over (order by {q(t)}) rn from s where {q(x)} is not null) "
                           f"where (rn - 1) % {step} = 0 order by {q(t)}").fetchall()
        is_mjd = "mjd" in t.lower()

        def label(v):
            if is_mjd and isinstance(v, (int, float)):
                return (dt.datetime(1858, 11, 17) + dt.timedelta(days=float(v))).isoformat(timespec="minutes")
            return str(v)

        points = [[round(float(r[1]), 3), round(float(r[2]), 3), round(float(r[3]), 3)] for r in rows]
        times = [label(r[0]) for r in rows]
        series = [{"column": c, "points": [[times[i], round(float(r[1 + j]), 6)] for i, r in enumerate(rows) if r[1 + j] is not None]}
                  for j, c in enumerate([x, y, z, *extra])]
        mcol, tcol = _col(cols, "maneuver"), _col(cols, "maneuver_type")
        maneuvers = []
        if mcol or tcol:
            cond = " or ".join(filter(None, [f"{q(mcol)}" if mcol else None, f"{q(tcol)} > 0" if tcol else None]))
            known = bool(tcol) and {"semi_major_axis", "RA"} <= set(cols)
            for tv, typ in con.execute(f"select {q(t)}, {q(tcol) if tcol else 'null'} from s where {cond} order by {q(t)} limit 500").fetchall():
                maneuvers.append({"t": label(tv), "type": typ, "label": MANEUVER_LABELS.get(typ, f"type {typ}") if known and typ is not None
                                  else (f"type {typ}" if typ is not None else "maneuver")})
        return {"time": t, "time_kind": "mjd" if is_mjd else "value", "position": [x, y, z], "points": points, "times": times,
                "points_total": n, "step": step, "series": series, "maneuvers": maneuvers,
                "maneuver_labels_source": "dataset card (maneuver_type codes 0-5)" if maneuvers and {"semi_major_axis", "RA"} <= set(cols) else None,
                "units_note": "Units as stored in the file; the FraDra card gives km and km/s in GCRS." if {"semi_major_axis", "RA"} <= set(cols) else
                "Units as stored in the file."}
    finally:
        con.close()


def pair_metadata(path: Path, partner: str) -> dict:
    import duckdb

    from ..dataimport import _reader

    con = duckdb.connect()
    try:
        cur = con.execute(f"select * from {_reader(path, 'parquet')} limit 5")
        names = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()
    first = rows[0] if rows else ()
    return {"file": path.name, "partner": partner, "rows": len(rows),
            "values": [[k, None if v is None else (v if isinstance(v, (int, float, bool)) else str(v)[:120])] for k, v in zip(names, first)]}


register(Tabular())
