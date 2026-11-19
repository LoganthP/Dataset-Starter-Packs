# Data dictionary — NASA POWER daily point

**Grain:** one row per calendar day for one requested point (latitude, longitude).
**Key:** `date` (from the `YYYYMMDD` keys of `properties.parameter.<NAME>`).
**Time standard:** `LST` (Local Solar Time) — requested explicitly with `time-standard=LST`.
**Spatial meaning:** values are **gridded estimates** for the cell containing the point (MERRA-2 meteorology ≈ 0.5° × 0.625°), not readings from a weather station in the city.

| Column | Type | Units | Description | Role |
|---|---|---|---|---|
| `date` | date | — | Day the values describe | index |
| `T2M` | float | °C | Mean air temperature at 2 m | target for the next-day baseline |
| `T2M_MAX` | float | °C | Daily maximum temperature at 2 m | explore |
| `T2M_MIN` | float | °C | Daily minimum temperature at 2 m | explore |
| `PRECTOTCORR` | float | mm/day | Bias-corrected total precipitation | explore |
| `RH2M` | float | % | Relative humidity at 2 m | explore |

## Missing-value convention
POWER returns **`-999`** (stated in `header.fill_value`) when a value is unavailable. The loader converts every fill value to `NaN` before any aggregation. Monthly rainfall totals are left blank when *any* day of that month is missing, so a gap is never mistaken for a dry spell.

## Request metadata saved with each download
`data/raw/power_<city>_<start>_<end>.source.json` stores: full query URL, parameters, community (`AG`), requested coordinates, time standard, fill value, API version, and retrieval timestamp (UTC). Keep it with any chart you publish.

## Cities available
| key | latitude | longitude |
|---|---|---|
| bengaluru | 12.9716 | 77.5946 |
| chennai | 13.0827 | 80.2707 |
| mysuru | 12.2958 | 76.6394 |
| hyderabad | 17.3850 | 78.4867 |
| mumbai | 19.0760 | 72.8777 |
| delhi | 28.6139 | 77.2090 |

Add more in `load_data.CITIES`.
