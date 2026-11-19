"""Regenerate the synthetic POWER-format fixtures (Bengaluru and Chennai, 2022-2023).

The files mimic the POWER Daily API JSON layout so the real parser is exercised.
Tricky cases: a handful of -999 fill markers (including a 4-day gap in precipitation).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
dates = pd.date_range("2022-01-01", "2023-12-31", freq="D")
doy = dates.dayofyear.to_numpy()

PROFILES = {
    # mean temp, seasonal amplitude, peak day, monsoon (start doy, end doy, mm/day), humidity base
    "bengaluru": dict(lat=12.9716, lon=77.5946, mean=24.0, amp=3.0, peak=110, rain=[(150, 290, 11.0)], rh=65),
    "chennai": dict(lat=13.0827, lon=80.2707, mean=28.8, amp=3.2, peak=150, rain=[(160, 260, 4.5), (285, 350, 16.0)], rh=72),
}


def make(city: str, seed: int) -> dict:
    p = PROFILES[city]
    rng = np.random.default_rng(seed)
    seasonal = p["amp"] * np.cos((doy - p["peak"]) / 365.25 * 2 * np.pi)
    noise = np.convolve(rng.normal(0, 0.9, len(dates)), np.ones(3) / 3, mode="same")
    t2m = p["mean"] + seasonal + noise
    rng_span = 9 + rng.normal(0, 1, len(dates))
    precip = np.zeros(len(dates))
    for start, end, intensity in p["rain"]:
        wet = (doy >= start) & (doy <= end)
        precip[wet] = rng.gamma(0.6, intensity / 0.6, wet.sum()) * (rng.random(wet.sum()) < 0.65)
    precip += rng.gamma(0.3, 0.8, len(dates)) * (rng.random(len(dates)) < 0.08)
    rh = np.clip(p["rh"] + 15 * (precip > 1) + rng.normal(0, 6, len(dates)), 20, 100)
    values = {
        "T2M": t2m - 0.15 * precip.clip(0, 20),
        "T2M_MAX": t2m + rng_span / 2,
        "T2M_MIN": t2m - rng_span / 2,
        "PRECTOTCORR": precip,
        "RH2M": rh,
    }
    keys = dates.strftime("%Y%m%d")
    out = {name: {k: round(float(v), 2) for k, v in zip(keys, arr)} for name, arr in values.items()}
    # Deliberate fill markers - the loader must turn these into NaN, never into -999 °C.
    for name, day in [("T2M", "20220315"), ("T2M_MAX", "20220315"), ("T2M_MIN", "20220315"), ("RH2M", "20230102")]:
        out[name][day] = -999.0
    for day in ["20230720", "20230721", "20230722", "20230723"]:
        out["PRECTOTCORR"][day] = -999.0
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"], 900.0]},
        "properties": {"parameter": out},
        "header": {
            "title": "SYNTHETIC FIXTURE in NASA/POWER daily format",
            "api": {"version": "fixture", "name": "POWER Daily API"},
            "sources": ["synthetic"],
            "fill_value": -999.0,
            "time_standard": "LST",
            "start": "20220101",
            "end": "20231231",
        },
        "messages": ["Synthetic data for offline testing - not real weather."],
        "parameters": {k: {"units": "C" if k.startswith("T2M") else ("mm/day" if k == "PRECTOTCORR" else "%"), "longname": k}
                       for k in values},
        "times": {"data": 0, "process": 0},
    }


for i, city in enumerate(PROFILES):
    path = HERE / f"power_{city}_sample.json"
    path.write_text(json.dumps(make(city, 7 + i)), encoding="utf-8")
    print("wrote", path)
