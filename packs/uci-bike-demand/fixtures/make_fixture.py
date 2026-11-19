"""Regenerate hour_sample.csv - invented data with the exact UCI hour.csv schema.

Tricky cases built in on purpose:
* ~30 hours are missing (the real file also skips hours), including a 5-hour gap.
* casual + registered always equals cnt, so the leakage trap is present.
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
hours = pd.date_range("2011-01-01", "2011-04-30 23:00", freq="h")
df = pd.DataFrame({"timestamp": hours})
df["dteday"] = df["timestamp"].dt.strftime("%Y-%m-%d")
df["hr"] = df["timestamp"].dt.hour
df["mnth"] = df["timestamp"].dt.month
df["yr"] = 0
df["season"] = np.where(df["mnth"] <= 3, 1, 2)
df["weekday"] = (df["timestamp"].dt.dayofweek + 1) % 7  # UCI: 0 = Sunday
holidays = {"2011-01-17", "2011-02-21", "2011-04-15"}
df["holiday"] = df["dteday"].isin(holidays).astype(int)
df["workingday"] = ((df["weekday"].between(1, 5)) & (df["holiday"] == 0)).astype(int)

day_index = (df["timestamp"] - hours[0]).dt.days.to_numpy()
daily_temp = 0.22 + 0.25 * day_index / day_index.max() + rng.normal(0, 0.05, len(df))
df["temp"] = np.clip(daily_temp + 0.06 * np.sin((df["hr"] - 9) / 24 * 2 * np.pi), 0.02, 0.98).round(2)
df["atemp"] = np.clip(df["temp"] - 0.02 + rng.normal(0, 0.02, len(df)), 0, 1).round(4)
df["hum"] = np.clip(0.6 + rng.normal(0, 0.15, len(df)), 0.1, 1).round(2)
df["windspeed"] = np.clip(np.abs(rng.normal(0.18, 0.1, len(df))), 0, 0.85).round(4)
df["weathersit"] = rng.choice([1, 2, 3, 4], p=[0.64, 0.26, 0.095, 0.005], size=len(df))

h = df["hr"].to_numpy()
commute = 220 * np.exp(-((h - 8) ** 2) / 2) + 300 * np.exp(-((h - 17.5) ** 2) / 3) + 60 * np.exp(-((h - 12.5) ** 2) / 6)
leisure = 180 * np.exp(-((h - 14) ** 2) / 10)
base = np.where(df["workingday"] == 1, commute, leisure) + 6
trend = 0.55 + 0.9 * day_index / day_index.max()
weather = 1.25 - 0.18 * df["weathersit"] + 0.6 * (df["temp"] - 0.35)
expected = np.clip(base * trend * weather, 1, None)
cnt = rng.poisson(expected)
share_casual = np.where(df["workingday"] == 1, 0.12, 0.38)
df["casual"] = rng.binomial(cnt, share_casual)
df["registered"] = cnt - df["casual"]
df["cnt"] = cnt

drop = set(rng.choice(len(df), size=25, replace=False)) | set(range(1500, 1505))
df = df.drop(index=sorted(drop)).reset_index(drop=True)
df.insert(0, "instant", range(1, len(df) + 1))
cols = ["instant", "dteday", "season", "yr", "mnth", "hr", "holiday", "weekday", "workingday", "weathersit",
        "temp", "atemp", "hum", "windspeed", "casual", "registered", "cnt"]
out = Path(__file__).with_name("hour_sample.csv")
df[cols].to_csv(out, index=False)
print(f"wrote {out} ({len(df)} rows)")
