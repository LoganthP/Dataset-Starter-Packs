# Data dictionary — `hour.csv`

**Grain:** one row per hour, 2011-01-01 00:00 → 2012-12-31 23:00 (Washington D.C., Capital Bikeshare).
**Primary key:** (`dteday`, `hr`). `instant` is a row counter, not a stable key.
**Target:** `cnt`. **Rows:** 17,379 — some hours are missing from the file (no row at all, not a zero).

| Column | Type | Units / values | Role | Notes |
|---|---|---|---|---|
| `instant` | int | 1…N | ID | Exclude from features. |
| `dteday` | date | YYYY-MM-DD | key | Combine with `hr` to make a timestamp. |
| `season` | int | 1 winter · 2 spring · 3 summer · 4 fall | calendar | Known in advance. |
| `yr` | int | 0 = 2011 · 1 = 2012 | calendar | Captures system growth. |
| `mnth` | int | 1–12 | calendar | |
| `hr` | int | 0–23 | calendar | Hour the rentals started. |
| `holiday` | int | 0/1 | calendar | From the D.C. holiday schedule. |
| `weekday` | int | 0 = Sunday … 6 = Saturday | calendar | The notebook recomputes `dow` (0 = Monday) from the timestamp. |
| `workingday` | int | 0/1 | calendar | 1 if neither weekend nor holiday. |
| `weathersit` | int | 1 clear · 2 mist · 3 light rain/snow · 4 heavy | weather | **Observed**, not forecast. |
| `temp` | float | Celsius / 41 (normalised 0–1) | weather | **Observed.** Multiply by 41 for °C. |
| `atemp` | float | Feels-like Celsius / 50 | weather | **Observed.** |
| `hum` | float | Relative humidity / 100 | weather | **Observed.** |
| `windspeed` | float | Wind speed / 67 | weather | **Observed.** |
| `casual` | int | rentals | **excluded** | Component of the target — leaks the answer. |
| `registered` | int | rentals | **excluded** | Component of the target — leaks the answer. |
| `cnt` | int | rentals | **target** | Always equals `casual + registered`. |

## Missing-value conventions
No `NaN` values appear inside rows. Missing information shows up as **missing rows** (absent hours). The loader validates that `(dteday, hr)` is unique; the analysis reindexes onto a complete hourly grid before computing lags so a gap never shifts the wrong hour into `cnt_lag1`.

## Derived features (built in `analysis.py`)
| Feature | Meaning |
|---|---|
| `dow` | Day of week from the timestamp, 0 = Monday |
| `cnt_lag1`, `cnt_lag2`, `cnt_lag24`, `cnt_lag168` | Demand 1 h, 2 h, 1 day and 1 week earlier (NaN if that hour is missing) |
| `temp_lag1`, `atemp_lag1`, `hum_lag1`, `windspeed_lag1`, `weathersit_lag1` | Weather observed in the previous hour |
