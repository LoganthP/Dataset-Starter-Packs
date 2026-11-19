"""Data loader for the NASA POWER daily weather pack.

* ``sample`` mode reads fixtures shaped exactly like the POWER API JSON response.
* ``real`` mode calls the POWER Daily API (no key needed), caches the raw JSON in
  ``data/raw/`` and writes the query URL + retrieval date next to it.

POWER values are gridded estimates (~0.5° x 0.625° MERRA-2 / ~1° CERES cells) for the
requested coordinates - not station observations. Missing values arrive as -999.

    python load_data.py --fetch --city bengaluru --start 2015-01-01 --end 2024-12-31
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

PACK_DIR = Path(__file__).resolve().parent
RAW_DIR = PACK_DIR / "data" / "raw"
FIXTURE_DIR = PACK_DIR / "fixtures"

API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
DOCS_URL = "https://power.larc.nasa.gov/docs/services/api/temporal/daily/"
CITATION = ("Data obtained from the NASA Langley Research Center (LaRC) POWER Project funded through "
            "the NASA Earth Science/Applied Science Program.")
TIMEOUT_SECONDS = 90
FILL_VALUE_DEFAULT = -999.0

CITIES: dict[str, tuple[float, float]] = {
    "bengaluru": (12.9716, 77.5946),
    "chennai": (13.0827, 80.2707),
    "mysuru": (12.2958, 76.6394),
    "hyderabad": (17.3850, 78.4867),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.6139, 77.2090),
}
SAMPLE_CITIES = ("bengaluru", "chennai")
SAMPLE_RANGE = ("2022-01-01", "2023-12-31")

PARAMETERS = {
    "T2M": ("Mean air temperature at 2 m", "°C"),
    "T2M_MAX": ("Maximum air temperature at 2 m", "°C"),
    "T2M_MIN": ("Minimum air temperature at 2 m", "°C"),
    "PRECTOTCORR": ("Bias-corrected precipitation", "mm/day"),
    "RH2M": ("Relative humidity at 2 m", "%"),
}
COMMUNITY = "AG"
TIME_STANDARD = "LST"  # daily values aggregated in Local Solar Time


class DataError(RuntimeError):
    """Raised with a human-readable recovery hint when data is missing or malformed."""


def build_query(lat: float, lon: float, start: str, end: str) -> dict:
    return {
        "parameters": ",".join(PARAMETERS),
        "community": COMMUNITY,
        "longitude": f"{lon:.4f}",
        "latitude": f"{lat:.4f}",
        "start": start.replace("-", ""),
        "end": end.replace("-", ""),
        "format": "JSON",
        "time-standard": TIME_STANDARD,
    }


def build_url(lat: float, lon: float, start: str, end: str) -> str:
    return f"{API_URL}?{urllib.parse.urlencode(build_query(lat, lon, start, end))}"


def _check_dates(start: str, end: str) -> None:
    try:
        s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except ValueError as exc:
        raise DataError("Dates must be YYYY-MM-DD.") from exc
    if s > e:
        raise DataError("start must be on or before end.")
    if s < dt.date(1981, 1, 1):
        raise DataError("POWER daily meteorology starts on 1981-01-01.")


def _cache_path(city: str, start: str, end: str) -> Path:
    return RAW_DIR / f"power_{city}_{start}_{end}.json"


def fetch(city: str = "bengaluru", start: str = "2015-01-01", end: str = "2024-12-31", force: bool = False) -> Path:
    """Call the POWER API for one city and cache the raw JSON + query metadata."""
    if city not in CITIES:
        raise DataError(f"Unknown city {city!r}. Choose one of: {', '.join(CITIES)}")
    _check_dates(start, end)
    path = _cache_path(city, start, end)
    if path.exists() and not force:
        return path
    lat, lon = CITIES[city]
    url = build_url(lat, lon, start, end)
    print(f"Requesting NASA POWER for {city} ({lat}, {lon}) {start} -> {end}", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "dataset-starter-packs/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise DataError(f"POWER API returned HTTP {exc.code}: {detail}\nCheck the query at {DOCS_URL}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DataError(
            f"Could not reach the POWER API ({exc}).\nRecovery: check your connection or try again later; "
            f"the service status is at https://power.larc.nasa.gov/. Sample mode still works offline."
        ) from exc
    data = json.loads(payload)
    if "properties" not in data:
        raise DataError(f"Unexpected POWER response (no 'properties'): {str(data)[:300]}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    meta = {
        "source_url": url,
        "api": API_URL,
        "query": build_query(lat, lon, start, end),
        "city": city,
        "requested_coordinates": {"latitude": lat, "longitude": lon},
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "time_standard": TIME_STANDARD,
        "fill_value": data.get("header", {}).get("fill_value", FILL_VALUE_DEFAULT),
        "api_version": data.get("header", {}).get("api", {}).get("version"),
        "citation": CITATION,
    }
    path.with_suffix(".source.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved {path.name} ({path.stat().st_size:,} bytes)", flush=True)
    return path


def parse_power_json(data: dict) -> pd.DataFrame:
    """Turn a POWER point response into a daily DataFrame. Fill values become NaN."""
    try:
        params = data["properties"]["parameter"]
    except KeyError as exc:
        raise DataError("Response is missing properties.parameter.") from exc
    missing = [p for p in PARAMETERS if p not in params]
    if missing:
        raise DataError(f"Required parameter(s) missing from response: {', '.join(missing)}")
    fill = float(data.get("header", {}).get("fill_value", FILL_VALUE_DEFAULT))
    frame = pd.DataFrame({p: pd.Series(params[p], dtype="float64") for p in PARAMETERS})
    frame.index = pd.to_datetime(frame.index, format="%Y%m%d")
    frame.index.name = "date"
    frame = frame.sort_index()
    # The trap: -999 is a marker, not a temperature. Compare with a tolerance in case of float formatting.
    frame = frame.mask(np.isclose(frame, fill))
    return frame


def validate(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise DataError("No rows returned for the requested range.")
    expected = pd.date_range(frame.index.min(), frame.index.max(), freq="D")
    if len(expected) != len(frame):
        raise DataError(f"Expected {len(expected)} consecutive days, got {len(frame)}.")
    if (frame.min(numeric_only=True) < -100).any():
        raise DataError("Found values below -100 - a fill marker was not converted to missing.")
    return frame


def load(mode: str = "sample", city: str = "bengaluru", start: str | None = None, end: str | None = None,
         fetch_if_missing: bool = True) -> pd.DataFrame:
    if mode == "sample":
        if city not in SAMPLE_CITIES:
            raise DataError(f"Sample mode includes {', '.join(SAMPLE_CITIES)} only. Switch to real mode for {city}.")
        path = FIXTURE_DIR / f"power_{city}_sample.json"
        if not path.exists():
            raise DataError(f"Expected fixture {path}. Run fixtures/make_fixture.py.")
    elif mode == "real":
        start, end = start or "2015-01-01", end or "2024-12-31"
        path = _cache_path(city, start, end)
        if not path.exists():
            if not fetch_if_missing:
                raise DataError(f"Expected {path.name} in {RAW_DIR}. Run `python load_data.py --fetch` first.")
            path = fetch(city, start, end)
    else:
        raise DataError(f"Unknown mode {mode!r}. Use 'sample' or 'real'.")
    frame = validate(parse_power_json(json.loads(path.read_text(encoding="utf-8"))))
    frame.attrs.update({"city": city, "path": str(path)})
    return frame


def provenance(mode: str, city: str, start: str | None = None, end: str | None = None) -> dict:
    if mode == "sample":
        return {"kind": "synthetic fixture", "file": f"fixtures/power_{city}_sample.json",
                "note": "Invented values in the POWER JSON format. Not real weather."}
    meta = _cache_path(city, start or "2015-01-01", end or "2024-12-31").with_suffix(".source.json")
    return json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {"kind": "real", "city": city}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mode", default="sample", choices=["sample", "real"])
    parser.add_argument("--city", default="bengaluru", choices=list(CITIES))
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2024-12-31")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.city, args.start, args.end, force=args.force)
        args.mode = "real"
    df = load(args.mode, args.city, args.start, args.end)
    print(df.describe().round(2))
    print("Missing values per column:\n", df.isna().sum())
