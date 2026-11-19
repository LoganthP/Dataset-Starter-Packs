"""SINEX (Solution INdependent EXchange, IERS/IGS 2.x): station positions, velocities and their
uncertainties from geodetic solutions (GNSS, DORIS, SLR, VLBI). Plain .snx/.sinex, .gz, .Z, or inside a ZIP.

Blocks read: FILE/REFERENCE, SITE/ID, SOLUTION/EPOCHS, SOLUTION/ESTIMATE (and the %=SNX header).
Station locations are plotted only when they can be converted honestly:
  STAX/STAY/STAZ (metres, terrestrial frame such as ITRF/IGS/DPOD) -> geodetic lat/lon/h on GRS80;
  otherwise the approximate longitude/latitude in SITE/ID, labelled as approximate;
  otherwise no map.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import re
from pathlib import Path

from .registry import Handler, Job, register

POS = ("STAX", "STAY", "STAZ")
VEL = ("VELX", "VELY", "VELZ")
TERRESTRIAL = re.compile(r"ITRF|IGS|IGb|DPOD|ETRF|NAD|GRS80|WGS84|ITRS|TRF", re.I)


def epoch(s: str) -> str | None:
    """YY:DDD:SSSSS (or YYYY:DDD:SSSSS) -> ISO time; 00:000:00000 means 'not set'."""
    m = re.fullmatch(r"(\d{2,4}):(\d{3}):(\d{5})", s.strip())
    if not m:
        return None
    y, d, sec = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y == 0 and d == 0 and sec == 0:
        return None
    if y < 100:
        y += 1900 if y > 50 else 2000
    try:
        return (dt.datetime(y, 1, 1) + dt.timedelta(days=max(d, 1) - 1, seconds=sec)).isoformat(timespec="seconds")
    except ValueError:
        return None


def _dms(deg: str, mins: str, secs: str) -> float:
    d = float(deg)
    sign = -1 if deg.strip().startswith("-") else 1
    return sign * (abs(d) + float(mins) / 60 + float(secs) / 3600)


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """GRS80 (the ITRF ellipsoid); Bowring's method, sub-millimetre for Earth-surface points."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f)
    b = a * (1 - f)
    ep2 = (a * a - b * b) / (b * b)
    p = math.hypot(x, y)
    th = math.atan2(z * a, p * b)
    lat = math.atan2(z + ep2 * b * math.sin(th) ** 3, p - e2 * a * math.cos(th) ** 3)
    lon = math.atan2(y, x)
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    h = p / math.cos(lat) - n if abs(math.cos(lat)) > 1e-12 else abs(z) - b
    return math.degrees(lat), math.degrees(lon), h


def enu(vx: float, vy: float, vz: float, lat: float, lon: float) -> tuple[float, float, float]:
    la, lo = math.radians(lat), math.radians(lon)
    e = -math.sin(lo) * vx + math.cos(lo) * vy
    n = -math.sin(la) * math.cos(lo) * vx - math.sin(la) * math.sin(lo) * vy + math.cos(la) * vz
    u = math.cos(la) * math.cos(lo) * vx + math.cos(la) * math.sin(lo) * vy + math.sin(la) * vz
    return e, n, u


def parse(path: Path, *, max_estimates: int | None = None) -> dict:
    header, ref, sites, epochs, est = {}, {}, {}, {}, []
    block = None
    units: dict[str, int] = {}
    types: dict[str, int] = {}
    with open(path, encoding="latin-1") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("%=SNX"):
                parts = line.split()
                header = {"version": parts[1] if len(parts) > 1 else None, "agency": parts[2] if len(parts) > 2 else None,
                          "created": epoch(parts[3]) if len(parts) > 3 else None, "data_agency": parts[4] if len(parts) > 4 else None,
                          "start": epoch(parts[5]) if len(parts) > 5 else None, "end": epoch(parts[6]) if len(parts) > 6 else None,
                          "technique": parts[7] if len(parts) > 7 else None, "parameters": int(parts[8]) if len(parts) > 8 and parts[8].isdigit() else None,
                          "contents": " ".join(parts[10:]) if len(parts) > 10 else None}
                continue
            if line.startswith("+"):
                block = line[1:].strip()
                continue
            if line.startswith("-"):
                block = None
                continue
            if not line.strip() or line.startswith("*"):
                continue
            if block == "FILE/REFERENCE":
                key, val = line[1:19].strip(), line[19:].strip()
                if key:
                    ref[key] = val
            elif block == "SITE/ID":
                code, pt = line[1:5].strip(), line[6:8].strip()
                rest = line[21:].rstrip()
                desc = line[21:43].strip() if len(line) > 43 else rest.strip()
                coords = line[44:].split()
                site = {"code": code, "point": pt, "domes": line[9:18].strip() or None, "description": desc}
                if len(coords) >= 7:
                    try:
                        site["approx_lon"] = _dms(*coords[0:3]) % 360
                        site["approx_lon"] = site["approx_lon"] - 360 if site["approx_lon"] > 180 else site["approx_lon"]
                        site["approx_lat"] = _dms(*coords[3:6])
                        site["approx_h"] = float(coords[6])
                    except ValueError:
                        pass
                sites[(code, pt)] = site
            elif block == "SOLUTION/EPOCHS":
                p = line.split()
                if len(p) >= 7:
                    epochs.setdefault((p[0], p[1]), []).append({"soln": p[2], "start": epoch(p[4]), "end": epoch(p[5]), "mean": epoch(p[6])})
            elif block == "SOLUTION/ESTIMATE":
                p = line.split()
                if len(p) < 9:
                    continue
                try:
                    value = float(p[8].replace("D", "E"))
                    sd = float(p[9].replace("D", "E")) if len(p) > 9 else None
                except ValueError:
                    continue
                types[p[1]] = types.get(p[1], 0) + 1
                units[p[6]] = units.get(p[6], 0) + 1
                if max_estimates is None or len(est) < max_estimates:
                    est.append({"type": p[1], "code": p[2], "point": p[3], "soln": p[4], "epoch": epoch(p[5]), "unit": p[6], "value": value, "sd": sd})
    return {"header": header, "reference": ref, "sites": sites, "epochs": epochs, "estimates": est, "types": types, "units": units}


def stations(parsed: dict) -> tuple[list[dict], str]:
    frame_text = " ".join([parsed["reference"].get("DESCRIPTION", ""), parsed["header"].get("contents") or "",
                           parsed["reference"].get("INPUT", ""), parsed["reference"].get("OUTPUT", "")])
    terrestrial = bool(TERRESTRIAL.search(frame_text)) or bool(parsed["estimates"])  # SINEX STA* are Earth-fixed by definition
    by: dict[tuple, dict] = {}
    for e in parsed["estimates"]:
        key = (e["code"], e["point"], e["soln"])
        s = by.setdefault(key, {"code": e["code"], "point": e["point"], "soln": e["soln"]})
        if e["type"] in POS + VEL:
            s[e["type"]] = e["value"]
            s[e["type"] + "_sd"] = e["sd"]
            s[e["type"] + "_unit"] = e["unit"]
            if e["type"] in POS:
                s["ref_epoch"] = e["epoch"]
    rows = []
    for (code, pt, soln), s in by.items():
        site = parsed["sites"].get((code, pt)) or parsed["sites"].get((code, "A")) or {}
        row = {"station": code, "point": pt, "solution": soln, "domes": site.get("domes"), "description": site.get("description"),
               "ref_epoch": s.get("ref_epoch")}
        ep = next((x for x in parsed["epochs"].get((code, pt), []) if x["soln"] == soln), None)
        if ep:
            row.update({"data_start": ep["start"], "data_end": ep["end"]})
        has_xyz = all(k in s for k in POS) and all((s.get(k + "_unit") or "").lower() == "m" for k in POS)
        if has_xyz and terrestrial:
            lat, lon, h = ecef_to_geodetic(s["STAX"], s["STAY"], s["STAZ"])
            row.update({"latitude": round(lat, 7), "longitude": round(lon, 7), "height_m": round(h, 4), "position_source": "STAX/STAY/STAZ on GRS80"})
        elif "approx_lat" in site:
            row.update({"latitude": round(site["approx_lat"], 5), "longitude": round(site["approx_lon"], 5), "height_m": site.get("approx_h"),
                        "position_source": "SITE/ID approximate"})
        for k in POS:
            if k in s:
                row[f"{k.lower()}_m"] = s[k]
                row[f"sigma_{k[-1].lower()}_mm"] = None if s.get(k + "_sd") is None else round(s[k + "_sd"] * 1000, 3)
        if all(k in s for k in VEL) and "latitude" in row:
            scale = 1000 if all((s.get(k + "_unit") or "").lower() in ("m/y", "m/yr") for k in VEL) else None
            if scale:
                e, n, u = enu(s["VELX"], s["VELY"], s["VELZ"], row["latitude"], row["longitude"])
                row.update({"vel_east_mm_yr": round(e * scale, 3), "vel_north_mm_yr": round(n * scale, 3), "vel_up_mm_yr": round(u * scale, 3),
                            "horizontal_speed_mm_yr": round(math.hypot(e, n) * scale, 3)})
        rows.append(row)
    # Stations with only SITE/ID (no estimates) still count for coverage.
    seen = {(r["station"], r["point"]) for r in rows}
    for (code, pt), site in parsed["sites"].items():
        if (code, pt) not in seen:
            r = {"station": code, "point": pt, "solution": None, "domes": site.get("domes"), "description": site.get("description")}
            if "approx_lat" in site:
                r.update({"latitude": round(site["approx_lat"], 5), "longitude": round(site["approx_lon"], 5), "height_m": site.get("approx_h"),
                          "position_source": "SITE/ID approximate"})
            rows.append(r)
    return rows, ("terrestrial" if terrestrial else "unknown")


class Sinex(Handler):
    key = "sinex"
    label = "SINEX geodetic solution"
    types = ("sinex", "sinex-gz", "sinex-z")
    description = "Stations, solution epochs, coordinate and velocity estimates with uncertainties."

    def score(self, members: list[dict]) -> float:
        return 1.0 if any(m["type"] in self.types for m in members) else 0.0

    def select(self, members, *, sample, params):
        files = sorted([m for m in members if m["type"] in self.types], key=lambda m: m["name"])
        return files[:1] if sample else files[:20]

    def analyze(self, job: Job) -> dict:
        from ..analysis import analyze as profile
        from ..archive import decompress
        from .registry import sniff_path

        parsed_all, files = [], []
        for i, p in enumerate(job.paths):
            job.cancel()
            kind = sniff_path(p)
            if kind in ("gzip", "sinex-gz", "compress"):
                p = decompress(p, p.with_suffix(".snx"), kind="gzip" if kind != "compress" else "compress")
            job.progress("analyzing", i, len(job.paths), "files")
            parsed = parse(p)
            if not parsed["estimates"] and not parsed["sites"]:
                raise ValueError(f"{p.name} has no SITE/ID or SOLUTION/ESTIMATE block; it doesn't look like SINEX.")
            parsed_all.append(parsed)
            files.append(p.name)
            job.log(f"Parsed {p.name}: {len(parsed['sites'])} sites, {sum(parsed['types'].values()):,} estimates")
        rows, frame = [], "unknown"
        for parsed in parsed_all:
            r, frame = stations(parsed)
            rows.extend(r)
        table = job.root / "sinex_stations.csv"
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with open(table, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        report = profile(table, "csv", deadline=job.deadline, on_charts=job.on_charts)
        h = parsed_all[0]["header"]
        types: dict[str, int] = {}
        units: dict[str, int] = {}
        for p in parsed_all:
            for k, v in p["types"].items():
                types[k] = types.get(k, 0) + v
            for k, v in p["units"].items():
                units[k] = units.get(k, 0) + v
        sig = sorted(v for r in rows for k, v in r.items() if k.startswith("sigma_") and v is not None)
        located = [r for r in rows if r.get("latitude") is not None]
        report.update({
            "kind": "sinex",
            "coverage": "sample" if job.sample and len(job.paths) < len([m for m in job.members if m["type"] in self.types]) else "full",
            "sample_method": f"first SINEX file of {len([m for m in job.members if m['type'] in self.types])}" if job.sample and job.members else None,
            "sinex": {
                "files": files, "version": h.get("version"), "agency": h.get("agency"), "technique": h.get("technique"),
                "data_start": h.get("start"), "data_end": h.get("end"), "created": h.get("created"), "contents": h.get("contents"),
                "reference": {k: v for k, v in parsed_all[0]["reference"].items() if k in ("DESCRIPTION", "OUTPUT", "CONTACT", "SOFTWARE", "INPUT")},
                "frame": frame, "estimate_types": sorted(([k, v] for k, v in types.items()), key=lambda kv: -kv[1]),
                "units": sorted(([k, v] for k, v in units.items()), key=lambda kv: -kv[1]),
                "stations": len({(r["station"], r["point"]) for r in rows}), "solutions": len(rows),
                "with_position": sum(1 for r in rows if "stax_m" in r), "with_velocity": sum(1 for r in rows if "vel_east_mm_yr" in r),
                "located": len(located), "position_sources": sorted({r.get("position_source") for r in located if r.get("position_source")}),
                "sigma_mm": {"median": sig[len(sig) // 2], "p95": sig[int(len(sig) * 0.95) - 1] if len(sig) > 1 else sig[0], "max": sig[-1]} if sig else None,
                "table_file": table.name,
            },
        })
        return report


register(Sinex())
