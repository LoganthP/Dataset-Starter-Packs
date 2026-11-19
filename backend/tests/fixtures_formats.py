"""Builders for format fixtures: Ships-style image ZIPs, SatCen-style DOTA ZIPs, SINEX files, FraDra Parquet pairs,
plus a local HTTP server with Range support that stands in for Zenodo, Kaggle and the Hugging Face Hub."""
from __future__ import annotations

import base64
import http.server
import io
import json
import math
import re
import threading
import time
import zipfile
from urllib.parse import parse_qs, urlsplit


def png(w: int, h: int, color=(20, 60, 120)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def jpeg(w: int, h: int, color=(30, 90, 140)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


def ships_zip(ships: int = 30, no_ships: int = 90, json_bytes: int = 2_000_000) -> bytes:
    """Kaggle 'Ships in Satellite Imagery' layout: shipsnet/shipsnet/<label>__<scene>__<lon>_<lat>.png (80x80),
    scenes/scenes/*.png and a large shipsnet.json (pixel dump) that is not a label file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(ships + no_ships):
            label = 1 if i < ships else 0
            lon, lat = -122.5 + (i % 17) * 0.01, 37.7 + (i % 13) * 0.005
            z.writestr(f"shipsnet/shipsnet/{label}__20180708_{i:06d}_0f47__{lon:.6f}_{lat:.6f}.png", png(80, 80, (10, 40 + label * 100, 90)))
        z.writestr("scenes/scenes/sfbay_1.png", png(400, 300))
        z.writestr("scenes/scenes/sfbay_2.png", png(400, 300))
        z.writestr("shipsnet.json", '{"data": [' + ",".join(["0"] * (json_bytes // 2)) + '], "labels": []}')
    return buf.getvalue()


def dota_zip(images: int = 40, with_objects: int = 15) -> bytes:
    """SatCen-style skiff detection: images/*.jpg and labels/*.txt with 4-point polygons (x1 y1 ... x4 y4 class difficult)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("satcen_skiff/README.txt", "SatCen skiff detection fixture")
        for i in range(images):
            name = f"img_{i:04d}"
            z.writestr(f"satcen_skiff/images/{name}.jpg", jpeg(256, 256))
            lines = []
            if i < with_objects:
                for k in range(1 + i % 3):
                    x, y = 40 + 50 * k, 60 + 3 * i
                    lines.append(f"{x} {y} {x + 30} {y + 4} {x + 28} {y + 14} {x - 2} {y + 10} skiff 0")
            z.writestr(f"satcen_skiff/labels/{name}.txt", "\n".join(lines))
    return buf.getvalue()


def ceramics_xlsx(rows: int = 129) -> bytes:
    """The high-entropy ceramics training sheet: Systems, melt_lammps and descriptor means/stds (no units in the headers)."""
    import random

    from openpyxl import Workbook

    rnd = random.Random(7)
    wb = Workbook()
    ws = wb.active
    ws.title = "train"
    feats = ["N_Me_mean", "N_Me_std", "Z_Me_mean", "radius_Me_mean", "VEC_ele_mean", "eleNega_Pauling_ele_mean", "m_MeB2_mean", "density_MeB2_mean"]
    ws.append(["Systems", "melt_lammps", *feats])
    for i in range(rows):
        vec = rnd.choice([4, 4.2, 4.4, 4.6, 5, 5.4, 6])
        vals = [rnd.uniform(22, 74), rnd.uniform(0, 61), rnd.uniform(1.9, 2.9), rnd.uniform(1.28, 1.6), vec, rnd.uniform(1.3, 2.36),
                rnd.uniform(69, 205), rnd.uniform(4.5, 12.7)]
        ws.append([f"(Hf{i % 9}Ta{i % 5})B2", int(2400 + (vec - 4) * 600 - (vals[7] - 8) * 20 + rnd.gauss(0, 90)), *[round(v, 4) for v in vals]])
    ws2 = wb.create_sheet("test")
    ws2.append(["Systems", "melt_lammps"])
    ws2.append(["(HfTa)B2", 3000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ceramics_zip(noise_mb: int = 3) -> bytes:
    """Supplementary_Data_and_Code.zip shape: a small workbook next to large code/data files (stored, incompressible)."""
    import os as _os

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Supplementary/1_ML/train_dataset.xlsx", ceramics_xlsx())
        z.writestr("Supplementary/1_ML/feature_selection.py", "print('features')\n" * 50)
        for k in range(3):
            z.writestr(zipfile.ZipInfo(f"Supplementary/2_LAMMPS/dump_{k}.bin"), _os.urandom(noise_mb * 1_000_000), compress_type=zipfile.ZIP_STORED)
        z.writestr("Supplementary/README.md", "# Supplementary data")
    return buf.getvalue()


def ecef(lat: float, lon: float, h: float) -> tuple[float, float, float]:
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f)
    la, lo = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return (n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo), (n * (1 - e2) + h) * math.sin(la)


STATIONS = [("TLSA", "Toulouse, France", 43.5607, 1.4809, 207.3, (-0.012, 0.018, 0.010)),
            ("HBMB", "Hartebeesthoek, ZA", -25.8870, 27.7077, 1553.0, (-0.0004, 0.0198, 0.0164)),
            ("KRWB", "Kourou, French Guiana", 5.2512, -52.8058, 104.6, (0.0012, 0.0126, 0.0141))]


def sinex_text() -> str:
    """A SINEX 2.02 file in the DORIS DPOD shape: header, FILE/REFERENCE, SITE/ID, SOLUTION/EPOCHS, SOLUTION/ESTIMATE."""
    out = ["%=SNX 2.02 IDS 21:045:00000 IDS 93:003:00000 20:366:00000 D 00018 2 S V",
           "+FILE/REFERENCE",
           " DESCRIPTION       DPOD2020 DORIS extension of ITRF2020 for Precise Orbit Determination",
           " OUTPUT            Station positions and velocities, DPOD2020 v1.0",
           " CONTACT           ids.central.bureau@ign.fr",
           " SOFTWARE          CATREF",
           "-FILE/REFERENCE",
           "+SITE/ID",
           "*CODE PT __DOMES__ T _STATION DESCRIPTION__ APPROX_LON_ APPROX_LAT_ _APP_H_"]
    for code, desc, lat, lon, h, _ in STATIONS:
        lon360 = lon % 360

        def dms(v):
            s = "-" if v < 0 else " "
            v = abs(v)
            d = int(v)
            m = int((v - d) * 60)
            sec = (v - d - m / 60) * 3600
            return s, d, m, sec

        s1, d1, m1, c1 = dms(lon360)
        s2, d2, m2, c2 = dms(lat)
        out.append(f" {code:4s}  A 10003M009 D {desc:22s} {d1:3d} {m1:2d} {c1:4.1f} {s2.strip() + str(d2):>3s} {m2:2d} {c2:4.1f} {h:7.1f}")
    out += ["-SITE/ID", "+SOLUTION/EPOCHS", "*CODE PT SOLN T _DATA_START_ __DATA_END__ _MEAN_EPOCH_"]
    for code, *_ in STATIONS:
        out.append(f" {code:4s}  A    1 D 93:003:00000 20:366:00000 06:350:00000")
    out += ["-SOLUTION/EPOCHS", "+SOLUTION/ESTIMATE",
            "*INDEX TYPE__ CODE PT SOLN _REF_EPOCH__ UNIT S __ESTIMATED VALUE____ _STD_DEV___"]
    i = 0
    for code, _, lat, lon, h, vel in STATIONS:
        x, y, z = ecef(lat, lon, h)
        for typ, val, sd, unit in (("STAX", x, 0.0021, "m"), ("STAY", y, 0.0017, "m"), ("STAZ", z, 0.0025, "m"),
                                   ("VELX", vel[0], 0.0003, "m/y"), ("VELY", vel[1], 0.0003, "m/y"), ("VELZ", vel[2], 0.0004, "m/y")):
            i += 1
            out.append(f" {i:5d} {typ:6s} {code:4s}  A    1 15:001:00000 {unit:4s} 2 {val:21.14E} {sd:11.5E}")
    out += ["-SOLUTION/ESTIMATE", "%ENDSNX"]
    return "\n".join(out) + "\n"


def fradra_pair(n: int = 400) -> tuple[bytes, bytes]:
    import pandas as pd

    rows = []
    for i in range(n):
        t = 60800 + i / 96  # 15-minute steps (MJD)
        ang = 2 * math.pi * i / 96
        man = i in (120, 260)
        rows.append({"time_mjd": t, "x": 42164 * math.cos(ang), "y": 42164 * math.sin(ang), "z": 15 * math.sin(ang / 3),
                     "vx": -3.07 * math.sin(ang), "vy": 3.07 * math.cos(ang), "vz": 0.0, "semi_major_axis": 42164.2 + (0.4 if i > 120 else 0),
                     "eccentricity": 0.0002, "inclination": 0.0009, "raan": 1.1, "argument_of_perigee": 0.3, "true_anomaly": ang % (2 * math.pi),
                     "RA": 29.18, "DEC": 0.05, "maneuver": man, "maneuver_type": (1 if i == 120 else 2) if man else 0})
    meta = pd.DataFrame([{"satellite_mass": 3500.0, "satellite_area": 40.0, "sattellite_epsilon": 1.2, "ew_maneuver_strategy": "deadband",
                          "e_mag_0": 0.0002, "RA_0": 29.18, "t_step": 60.0}])
    return _parquet(pd.DataFrame(rows)), _parquet(meta)


def _parquet(df) -> bytes:
    import tempfile
    from pathlib import Path

    import duckdb

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "t.parquet"
        con = duckdb.connect()
        con.register("df", df)
        con.execute(f"copy df to '{out.as_posix()}' (format parquet)")
        con.close()
        return out.read_bytes()


class Server:
    """Files by path with Range support, JSON routes, and optional auth/consent rules."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.json: dict[str, object] = {}
        self.headers: dict[str, dict] = {}
        self.require_auth: dict[str, str] = {}  # path prefix -> expected Authorization header
        self.consent: set[str] = set()
        self.requests: list[tuple[str, str]] = []
        self.ranges: list[tuple[str, str]] = []
        self.flaky: dict[str, int] = {}  # path -> how many full responses to cut off halfway
        self.no_ranges: set[str] = set()  # paths served whole even when a Range is asked for (like some providers)
        self.etags: dict[str, str] = {}
        self.slow: dict[str, float] = {}  # path -> seconds between 64 KB chunks
        self.rate: float | None = None  # bytes per second for every body (network emulation for timing runs)
        self.latency: float = 0.0  # seconds before each response (round trip)
        self.bytes_sent: dict[str, int] = {}
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="application/octet-stream", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                path = urlsplit(self.path).path
                if path not in srv.no_ranges:
                    self.send_header("Accept-Ranges", "bytes")
                if path in srv.etags:
                    self.send_header("ETag", srv.etags[path])
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    if srv.latency:
                        time.sleep(srv.latency)
                    if srv.rate:
                        try:
                            for k in range(0, len(body), 65536):
                                t0 = time.monotonic()
                                self.wfile.write(body[k: k + 65536])
                                srv.bytes_sent[path] = srv.bytes_sent.get(path, 0) + len(body[k: k + 65536])
                                time.sleep(max(0.0, len(body[k: k + 65536]) / srv.rate - (time.monotonic() - t0)))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    else:
                        self.wfile.write(body)
                        srv.bytes_sent[path] = srv.bytes_sent.get(path, 0) + len(body)

            def do_GET(self):  # noqa: N802
                u = urlsplit(self.path)
                srv.requests.append((u.path, self.headers.get("Authorization") or ""))
                for prefix, expected in srv.require_auth.items():
                    if u.path.startswith(prefix) and self.headers.get("Authorization") != expected:
                        return self._send(401, b'{"message":"Unauthenticated"}', "application/json")
                if any(u.path.startswith(p) for p in srv.consent):
                    return self._send(403, b'{"code":403,"message":"You must accept this dataset\'s rules before downloading"}', "application/json")
                key = u.path + ("?" + u.query if u.query and (u.path + "?" + u.query) in srv.json else "")
                if key in srv.json or u.path in srv.json:
                    body = srv.json.get(key, srv.json.get(u.path))
                    body = body(parse_qs(u.query)) if callable(body) else body
                    extra = srv.headers.get(key) or srv.headers.get(u.path)
                    extra = extra(parse_qs(u.query)) if callable(extra) else extra
                    return self._send(200, json.dumps(body).encode(), "application/json", extra)
                data = srv.files.get(u.path)
                if data is None:
                    return self._send(404, b"not found", "text/plain")
                rng = self.headers.get("Range")
                srv.ranges.append((u.path, rng or ""))
                if u.path in srv.no_ranges:
                    rng = None
                if not rng and srv.flaky.get(u.path):
                    srv.flaky[u.path] -= 1
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    self.wfile.write(data[: len(data) // 2])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
                    a = int(m.group(1)) if m.group(1) else len(data) - int(m.group(2))
                    b = int(m.group(2)) if m.group(1) and m.group(2) else len(data) - 1
                    b = min(b, len(data) - 1)
                    if a >= len(data):
                        return self._send(416, b"", extra={"Content-Range": f"bytes */{len(data)}"})
                    return self._send(206, data[a: b + 1], extra={"Content-Range": f"bytes {a}-{b}/{len(data)}"})
                if u.path in srv.slow:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    try:
                        for k in range(0, len(data), 65536):
                            self.wfile.write(data[k: k + 65536])
                            self.wfile.flush()
                            time.sleep(srv.slow[u.path])
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                return self._send(200, data)

            do_HEAD = do_GET

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def basic(user: str, key: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode()


def record(rid: str, title: str, provider: str, url: str, **extra) -> dict:
    return {"id": rid, "title": title, "description": f"{title} fixture", "publisher": provider, "provider": provider, "providerId": extra.pop("providerId", rid),
            "canonicalUrl": url, "sourceLinks": [{"label": "Source", "url": url}], "tags": [], "purposes": [], "characteristics": [],
            "formats": {"values": extra.pop("formats", []), "status": "provider-reported"}, "access": {"method": "download", "signInRequired": False},
            "license": {"name": "CC BY 4.0", "url": url, "commercialUse": "allowed", "status": "provider-reported"},
            "coverage": {"temporal": {"status": "unknown"}, "spatial": {"scope": "unknown", "status": "unknown"}}, "schemaStatus": "unknown",
            "fields": [], "size": {"rows": None, "bytes": None}, "limitations": [], "origin": "live", **extra}
