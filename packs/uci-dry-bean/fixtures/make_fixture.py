"""Regenerate dry_bean_sample.csv - invented bean shapes with the UCI column names.

Tricky case: BOMBAY has only 12 rows, so a non-stratified split can leave it out of the
test set entirely, and accuracy barely notices if the model gets it wrong.
SIRA and DERMASON overlap heavily on purpose (they are also confused in the real data).
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(11)
# class: (count, mean area, area sd, aspect ratio mean, aspect sd)
CLASSES = {
    "DERMASON": (120, 32000, 3500, 1.47, 0.07),
    "SIRA": (90, 38000, 3500, 1.55, 0.07),
    "SEKER": (70, 39500, 4000, 1.18, 0.05),
    "HOROZ": (60, 53000, 6000, 2.00, 0.12),
    "CALI": (55, 75000, 7000, 1.72, 0.08),
    "BARBUNYA": (45, 69000, 7000, 1.55, 0.08),
    "BOMBAY": (12, 172000, 20000, 1.58, 0.09),
}
rows = []
for label, (n, area_mu, area_sd, ar_mu, ar_sd) in CLASSES.items():
    area = np.clip(rng.normal(area_mu, area_sd, n), 15000, None)
    ar = np.clip(rng.normal(ar_mu, ar_sd, n), 1.02, None)
    major = np.sqrt(4 * area * ar / np.pi)
    minor = major / ar
    ecc = np.sqrt(1 - (minor / major) ** 2)
    convex = area * rng.uniform(1.005, 1.02, n)
    perim = np.pi * (3 * (major + minor) / 2 - np.sqrt((3 * major / 2 + minor / 2) * (major / 2 + 3 * minor / 2)))
    perim *= rng.uniform(1.0, 1.03, n)
    eqd = np.sqrt(4 * area / np.pi)
    rows.append(pd.DataFrame({
        "Area": area.round().astype(int), "Perimeter": perim.round(3), "MajorAxisLength": major.round(3),
        "MinorAxisLength": minor.round(3), "AspectRation": ar.round(4), "Eccentricity": ecc.round(4),
        "ConvexArea": convex.round().astype(int), "EquivDiameter": eqd.round(3),
        "Extent": rng.uniform(0.7, 0.8, n).round(4), "Solidity": (area / convex).round(4),
        "roundness": (4 * np.pi * area / perim ** 2).round(4), "Compactness": (eqd / major).round(4),
        "ShapeFactor1": (major / area).round(6), "ShapeFactor2": (minor / area).round(6),
        "ShapeFactor3": ((eqd / major) ** 2).round(4), "ShapeFactor4": rng.uniform(0.99, 0.999, n).round(4),
        "Class": label,
    }))
df = pd.concat(rows).sample(frac=1, random_state=0).reset_index(drop=True)
out = Path(__file__).with_name("dry_bean_sample.csv")
df.to_csv(out, index=False)
print(f"wrote {out} ({len(df)} rows)")
