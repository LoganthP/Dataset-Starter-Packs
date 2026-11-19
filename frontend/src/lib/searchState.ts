/** URL is the single source of truth for search state, so any shortlist or search can be shared. */
import type { SearchCriteria } from "../types";

export const CRITERIA_KEYS = ["fields", "min_years", "formats", "region", "granularity", "commercial", "period_from", "period_to", "soft", "topic"];
export const FILTER_KEYS = ["provider", "purpose", "kind", "access", "license", "difficulty", "ready", "max_minutes", "max_mb"];
export const LIST_KEYS = new Set(["fields", "formats", "soft", "provider", "purpose", "kind", "access", "license", "difficulty", "ready"]);

export const list = (sp: URLSearchParams, key: string) => (sp.get(key) ?? "").split(",").filter(Boolean);

export function withParam(sp: URLSearchParams, key: string, value: string | null | undefined) {
  const next = new URLSearchParams(sp);
  if (value === null || value === undefined || value === "") next.delete(key);
  else next.set(key, value);
  next.delete("page");
  return next;
}

export function toggleInList(sp: URLSearchParams, key: string, value: string) {
  const cur = list(sp, key);
  const nextList = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
  return withParam(sp, key, nextList.join(","));
}

/** Criteria returned by /api/criteria/parse -> explicit URL params. */
export function paramsFromParsed(q: string, c: Partial<SearchCriteria>, keep: URLSearchParams) {
  const next = new URLSearchParams();
  for (const k of ["scope", "sort"]) {
    const v = keep.get(k);
    if (v) next.set(k, v);
  }
  if (q) next.set("q", q);
  if (c.fields?.length) next.set("fields", c.fields.join(","));
  if (c.min_years) next.set("min_years", String(c.min_years));
  if (c.formats?.length) next.set("formats", c.formats.join(","));
  if (c.region) next.set("region", c.region);
  if (c.granularity) next.set("granularity", c.granularity);
  if (c.commercial) next.set("commercial", "1");
  if (c.purposes?.length) next.set("purpose", c.purposes.join(","));
  if (c.difficulty?.length) next.set("difficulty", c.difficulty.join(","));
  const ready = [c.offline ? "offline-sample" : "", c.notebook ? "notebook" : ""].filter(Boolean);
  if (ready.length) next.set("ready", ready.join(","));
  return next;
}

/** Only the criteria part of the URL - carried into detail and compare pages. */
export function criteriaQuery(sp: URLSearchParams) {
  const out = new URLSearchParams();
  for (const k of [...CRITERIA_KEYS, "q"]) {
    const v = sp.get(k);
    if (v) out.set(k, v);
  }
  return out;
}

export const LABELS: Record<string, Record<string, string>> = {
  purpose: { forecasting: "Forecasting", classification: "Classification", regression: "Regression", geospatial: "Geospatial analysis", "sql-analytics": "SQL analytics", exploratory: "Exploratory analysis" },
  kind: { tabular: "Tabular", "time-series": "Time series", geospatial: "Geospatial", relational: "Multi-table", gridded: "Gridded", image: "Image", text: "Text" },
  access: { "direct-download": "Direct download", api: "API", "sign-in": "Sign-in required", unknown: "Access unknown" },
  license: { "commercial-ok": "Commercial reuse allowed", conditional: "Conditional reuse", "non-commercial": "Non-commercial only", unknown: "Unknown license" },
  difficulty: { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced" },
  ready: { "starter-pack": "Starter pack", analyzed: "Analyzed", notebook: "Notebook available", "offline-sample": "Offline sample" },
  formats: { csv: "CSV", json: "JSON", parquet: "Parquet", xlsx: "Excel", netcdf: "NetCDF" },
  granularity: { minute: "Minute", hourly: "Hourly", daily: "Daily", monthly: "Monthly" },
  fit: { meets: "Meets requirements", "needs-verification": "Needs verification", "does-not-meet": "Doesn't meet" },
};

export const label = (group: string, value: string) => LABELS[group]?.[value] ?? value;

export function criterionLabel(key: string, c: SearchCriteria, concepts: Record<string, string>, regions: Record<string, string>) {
  if (key.startsWith("field:")) return concepts[key.slice(6)] ?? key.slice(6);
  if (key === "min_years") return `At least ${c.min_years} year${c.min_years === 1 ? "" : "s"}`;
  if (key === "formats") return c.formats.map((f) => label("formats", f)).join(" or ");
  if (key === "region") return c.region ? regions[c.region] ?? c.region : "Region";
  if (key === "granularity") return c.granularity ? `${label("granularity", c.granularity)} values` : "Resolution";
  if (key === "commercial") return "Commercial reuse";
  if (key === "period") return `Covers ${c.period_from ?? "…"} to ${c.period_to ?? "…"}`;
  return key;
}
