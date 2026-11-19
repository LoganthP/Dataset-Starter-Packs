# Data dictionary — Dry Bean Dataset

**Grain:** one row per bean, measured from a high-resolution image (13,611 beans, 7 registered varieties).
**Key:** none — rows are independent observations (no ID column).
**Target:** `Class`. **Features:** 16 numeric shape descriptors (12 dimensions + 4 shape factors).
**Units:** pixel-based. Areas in pixels², lengths in pixels, ratios unitless.

| Column | Type | Units | Description |
|---|---|---|---|
| `Area` | int | px² | Pixels inside the bean boundary |
| `Perimeter` | float | px | Length of the boundary |
| `MajorAxisLength` | float | px | Longest line through the bean |
| `MinorAxisLength` | float | px | Longest line perpendicular to the major axis |
| `AspectRation` | float | — | Major / minor axis (the UCI header is spelled this way) |
| `Eccentricity` | float | — | Eccentricity of the fitted ellipse |
| `ConvexArea` | int | px² | Area of the smallest convex polygon containing the bean |
| `EquivDiameter` | float | px | Diameter of a circle with the same area |
| `Extent` | float | — | Area / bounding-box area |
| `Solidity` | float | — | Area / convex area (convexity) |
| `roundness` | float | — | 4π·Area / Perimeter² |
| `Compactness` | float | — | EquivDiameter / MajorAxisLength |
| `ShapeFactor1` – `ShapeFactor4` | float | — | Derived shape factors from the source paper |
| `Class` | str | — | **Target:** SEKER, BARBUNYA, BOMBAY, CALI, DERMASON, HOROZ, SIRA |

## Missing values
None in the official file. The loader rejects any missing or non-numeric feature, and any class label outside the seven above.

## Things to know
- **Imbalance:** DERMASON is the largest class (~26 %), BOMBAY the smallest (~4 %).
- **Correlated features:** many features are functions of each other (e.g. `Area`, `ConvexArea`, `EquivDiameter`). Fine for prediction, but be careful when you interpret coefficients or importances.
- **Scale:** features range from ~0.001 to ~250,000, so scale them — inside a pipeline, fit on training data only.
- **Header variants:** the loader accepts `AspectRatio`/`Roundness` and renames them to the UCI spellings.
