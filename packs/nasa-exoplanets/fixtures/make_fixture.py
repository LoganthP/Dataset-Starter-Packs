"""Regenerate pscomppars_sample.csv - an invented catalog with the real column names.

Built-in tricky cases: most radial-velocity planets lack a radius, microlensing planets often
lack a period, and imaging planets sit at very long periods - so filtering to "complete"
rows silently changes the method mix.
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(3)
spec = {
    # method: (count, log10 period mean/sd, log10 radius mean/sd, p(radius missing), p(period missing), year range, facilities)
    "Transit": (260, 1.0, 0.45, 0.35, 0.3, 0.02, 0.0, (2002, 2025), ["Kepler", "K2", "TESS", "WASP", "HATNet"]),
    "Radial Velocity": (110, 2.3, 0.8, 1.0, 0.35, 0.85, 0.0, (1995, 2025), ["La Silla Observatory", "Keck Observatory", "HARPS"]),
    "Microlensing": (25, 3.3, 0.4, 0.9, 0.3, 0.9, 0.7, (2004, 2024), ["OGLE", "KMTNet", "MOA"]),
    "Imaging": (14, 4.8, 0.6, 1.15, 0.12, 0.3, 0.6, (2004, 2024), ["Gemini Observatory", "Very Large Telescope"]),
    "Transit Timing Variations": (8, 1.3, 0.3, 0.4, 0.2, 0.25, 0.0, (2011, 2023), ["Kepler"]),
    "Astrometry": (3, 2.9, 0.4, 1.1, 0.1, 1.0, 0.0, (2013, 2024), ["Gaia"]),
}
rows = []
n = 0
for method, (count, pm, ps, rm, rs, p_rmiss, p_pmiss, (y0, y1), facilities) in spec.items():
    for _ in range(count):
        n += 1
        period = 10 ** rng.normal(pm, ps)
        radius = 10 ** rng.normal(rm, rs)
        year = int(rng.integers(y0, y1 + 1)) if method != "Transit" else int(np.clip(rng.normal(2016, 4), y0, y1))
        mass = radius ** 2.06 * rng.lognormal(0, 0.3) if rng.random() > 0.4 else np.nan
        rows.append({
            "pl_name": f"SYN-{n:04d} b",
            "hostname": f"SYN-{n:04d}",
            "discoverymethod": method,
            "disc_year": year,
            "disc_facility": rng.choice(facilities),
            "pl_rade": round(radius, 3) if rng.random() > p_rmiss else np.nan,
            "pl_orbper": round(period, 4) if rng.random() > p_pmiss else np.nan,
            "pl_bmasse": round(mass, 3) if np.isfinite(mass) else np.nan,
            "sy_dist": round(10 ** rng.normal(2.3, 0.4), 2),
        })
out = Path(__file__).with_name("pscomppars_sample.csv")
pd.DataFrame(rows).to_csv(out, index=False)
print(f"wrote {out} ({len(rows)} rows)")
