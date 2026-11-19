/**
 * Results of an analysis run, laid out like a starter pack's ResultsView (Bengaluru's Run screen):
 * headline card, summary tiles, checks, a captioned chart grid, then expandable details.
 * Which charts appear depends on the fields the data has.
 */
import { AlertTriangle, CheckCircle2, Download, XCircle } from "lucide-react";
import { Fragment, type ReactNode, useEffect, useState } from "react";
import { api, sizeLabel } from "../../api";
import { SchemaTable } from "../../pages/AnalysisPage";
import type { AnalysisReport, AnalysisRun } from "../../types";
import { fmtDate } from "../discover/bits";
import { Columns, CoverageBar, LineChart, PointMap, RankedBars, WeekdayHeatmap, WEEKDAYS } from "../insights/Charts";
import { Associations, PeriodLines, Scatter } from "../insights/RelationCharts";
import { ArchiveDetails, ImagePreviews, InspectionResults, kindCharts, kindChecks, kindTiles, keepGeneric, PairTable } from "./KindSections";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pretty = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const n0 = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 });

/** "Sample", "Full dataset" or "Full selected date range": the same words on cards, badges and tiles. */
export function scopeLabel(rep: Pick<AnalysisReport, "coverage" | "params" | "scope"> & { kind?: string }): string {
  if (rep.scope?.label) return rep.scope.label;
  if (rep.kind === "inspection" || rep.coverage === "inspection") return "Inspection only";
  if (rep.coverage !== "full") return "Sample";
  return rep.params?.dateFrom || rep.params?.dateTo ? "Full selected date range" : "Full dataset";
}

export function unitOf(rep: AnalysisReport): string {
  return rep.kind === "images" ? "images" : rep.kind === "sinex" ? "station solutions" : "rows";
}

export function ScopeBadge({ rep }: { rep: AnalysisReport }) {
  return rep.coverage === "full"
    ? <span className="rounded-full bg-ok/12 px-2.5 py-1 text-xs font-bold text-ok">{scopeLabel(rep)} · {rep.rows_analyzed.toLocaleString()} {unitOf(rep)}</span>
    : <span className="rounded-full bg-sun/50 px-2.5 py-1 text-xs font-bold text-warn-ink" title={rep.sample_method ?? undefined}>Sample · {rep.rows_analyzed.toLocaleString()} {unitOf(rep)}</span>;
}

type Chart = import("./KindSections").Chart;

/** Which rows a chart used, in words: "all 129 rows of worksheet “train” in train_dataset.xlsx", "1,000 sampled rows". */
export function rowsClause(rep: AnalysisReport, n?: number): string {
  const count = (n ?? rep.rows_analyzed).toLocaleString();
  const ws = rep.scope?.kind === "worksheet" ? ` of worksheet “${rep.scope.sheet}” in ${rep.scope.file?.split("/").pop()}` : "";
  if (rep.coverage === "sample") return `${count} sampled ${unitOf(rep)}${n != null && n < rep.rows_analyzed ? ` (of ${rep.rows_analyzed.toLocaleString()} analyzed)` : ""}`;
  if (n != null && n < rep.rows_analyzed) return `${count} of the ${rep.rows_analyzed.toLocaleString()} ${unitOf(rep)}${ws} that have both values`;
  return `all ${count} ${unitOf(rep)}${ws}`;
}

const withUnit = (name: string, unit?: string | null) => (unit ? `${name} (${unit})` : name);

/** Lay charts out two per row without stranding one in half a row: an odd run of half-width charts ends with a wide one. */
export function pack(charts: Chart[]): Chart[] {
  const out = charts.map((c) => ({ ...c }));
  let run: Chart[] = [];
  const flush = () => {
    if (run.length % 2 === 1) run[run.length - 1].wide = true;
    run = [];
  };
  for (const c of out) {
    if (c.wide) flush();
    else run.push(c);
  }
  flush();
  return out;
}

function buildCharts(rep: AnalysisReport): Chart[] {
  const ins = rep.insights;
  const out: Chart[] = [];
  const target = ins?.target;
  const rel = ins?.relationships;
  if (ins?.scatter) {
    const sc = ins.scatter;
    const r = rel?.items.find((d) => d.column === sc.x);
    out.push({
      key: "scatter", title: `${sc.y} against ${sc.x}`,
      caption: <>Each point is one row. {sc.x} has the strongest measured association with {sc.y}{r ? ` (Pearson r = ${r.pearson >= 0 ? "+" : "−"}${Math.abs(r.pearson).toFixed(2)}${r.spearman != null ? `, Spearman ρ = ${r.spearman.toFixed(2)}` : ""})` : ""}. An association, not a cause.</>,
      fields: [sc.x, sc.y], rows: rowsClause(rep, sc.total) + (sc.shown < sc.total ? `; ${sc.shown.toLocaleString()} plotted` : ""),
      node: <Scatter points={sc.points} xLabel={withUnit(sc.x, sc.x_unit)} yLabel={withUnit(sc.y, sc.y_unit)} />,
      head: [sc.x, sc.y], table: sc.points.slice(0, 500).map(([a, b]) => [n0(a), n0(b)]),
    });
  }
  if (rel?.enough && rel.items.length >= 2) out.push({
    key: "assoc", title: `Strongest associations with ${rel.target}`,
    caption: <>Pearson correlation between {rel.target} and each numeric field ({rel.tested} tested, top {Math.min(10, rel.items.length)} shown). Bars to the right rise with {rel.target}; to the left, they fall as it rises. Associations, not causes.</>,
    fields: [rel.target, ...rel.items.slice(0, 3).map((d) => d.column)].concat(rel.items.length > 3 ? [`+${Math.min(rel.items.length, 10) - 3} more shown`] : []),
    rows: rowsClause(rep, Math.max(...rel.items.map((d) => d.n))),
    node: <Associations items={rel.items.slice(0, 10)} target={rel.target} />,
    head: ["Field", "Pearson r · Spearman ρ · n"], table: rel.items.map((d) => [d.column, `${d.pearson.toFixed(3)} · ${d.spearman?.toFixed(3) ?? "—"} · ${d.n}`]),
  });
  if (ins?.seasonal) {
    const se = ins.seasonal;
    out.push({
      key: "seasonal", title: `${pretty(se.column)} by month, year against year`,
      caption: <>Monthly average of {se.column} for {se.years.join(", ")}. The latest year is highlighted; earlier years are gray for comparison.</>,
      fields: [se.column, rep.insights?.trends?.time ?? "date"], rows: rowsClause(rep),
      node: <PeriodLines series={se.series} unit={se.column} />,
      head: ["Year, month", `Average ${se.column}`], table: se.series.flatMap((s) => s.values.map(([m, v]) => [`${s.year}-${String(m).padStart(2, "0")}`, n0(v)] as [string, string])),
    });
  }
  const quality = rep.columns.filter((c) => c.missing_pct > 0).sort((a, b) => b.missing_pct - a.missing_pct).slice(0, 8);
  const tr = ins?.trends;
  tr?.series.slice(0, 2).forEach((s, i) => out.push({
    key: `trend-${s.column}`, wide: i === 0,
    title: `${pretty(s.column)} over time`,
    caption: <>Average of {s.column} per {tr.bucket}.</>, fields: [s.column, tr.time], rows: rowsClause(rep),
    node: <LineChart points={s.points} unit={s.column} yLabel={`${s.column} (avg per ${tr.bucket})`} />,
    head: ["Time", `Average ${s.column}`], table: s.points.map(([k, v]) => [k, n0(v)]),
  }));
  if (tr?.by_hour) {
    const vals = tr.by_hour.values.filter(([, v]) => v !== null) as [number, number][];
    out.push({
      key: "hourly-measure", title: `Average ${pretty(tr.by_hour.column).toLowerCase()} by hour of day`,
      caption: "Each bar averages every analyzed reading in that hour.", fields: [tr.by_hour.column, tr.time], rows: rowsClause(rep),
      node: <Columns data={vals.map(([h, v]) => [String(h).padStart(2, "0"), v])} unit={tr.by_hour.column} labelEvery={3} />,
      head: ["Hour", "Average"], table: vals.map(([h, v]) => [`${String(h).padStart(2, "0")}:00`, n0(v)]),
    });
  }
  const t = ins?.time;
  if (t?.weekday_hour?.length) out.push({
    key: "weekday-hour", wide: true, title: "When records happen: weekday by hour",
    caption: <>Record counts by weekday and hour.</>, fields: [t.column, t.hour_column].filter(Boolean) as string[], rows: rowsClause(rep, rep.rows_analyzed - (t.missing ?? 0)),
    node: <WeekdayHeatmap counts={t.weekday_hour} />,
    head: ["Weekday and hour", "Records"],
    table: t.weekday_hour.map(([d, h, count]) => [`${WEEKDAYS[d - 1]} ${String(h).padStart(2, "0")}:00`, count.toLocaleString()]),
  });
  if (ins?.injury_outcomes) {
    const o = ins.injury_outcomes;
    const unknown = rep.rows_analyzed - o.counts.reduce((a, [, count]) => a + count, 0);
    const rows = [...o.counts, ["Unknown", unknown] as [string, number]];
    out.push({
      key: "injury-outcomes", title: "Crash outcomes",
      caption: <>Crash counts by outcome. Unknown covers rows without a clear outcome.</>, fields: [o.injured_field, o.killed_field], rows: rowsClause(rep),
      node: <RankedBars data={rows.map(([label, value], i) => ({ label, value, muted: i === 3, tone: i === 0 ? "bad" : i === 1 ? "warn" : undefined }))} total={rep.rows_analyzed} />,
      head: ["Outcome", "Crashes"], table: rows.map(([label, value]) => [label, value.toLocaleString()]),
    });
  }
  if (t?.by_hour && !tr?.by_hour && !t.weekday_hour?.length) out.push({
    key: "by-hour", title: "Records by hour of day", caption: <>Local time as recorded.</>, fields: [t.hour_column!], rows: rowsClause(rep, rep.rows_analyzed - (t.missing ?? 0)),
    node: <Columns data={t.by_hour.map(([h, v]) => [String(h).padStart(2, "0"), v])} unit="records" labelEvery={3} />,
    head: ["Hour", "Records"], table: t.by_hour.map(([h, v]) => [`${String(h).padStart(2, "0")}:00`, v.toLocaleString()]),
  });
  ins?.categories?.filter((cc) => !labelLike(cc, rep.rows_analyzed)).slice(0, 2).forEach((cat) => {
    const rows = [
      ...cat.values.map(([k, v]) => ({ label: k, value: v })),
      ...(cat.other ? [{ label: `Other (${cat.distinct - cat.values.length} values)`, value: cat.other, muted: true }] : []),
      ...(cat.unknown ? [{ label: "Unknown (empty)", value: cat.unknown, muted: true }] : []),
    ];
    out.push({
      key: `cat-${cat.column}`, title: `Records by ${pretty(cat.column).toLowerCase()}`,
      caption: cat.unknown ? `${Math.round((100 * cat.unknown) / rep.rows_analyzed)}% of rows have no ${cat.column}; they're shown as Unknown, not dropped.` : "Ranked by count.",
      fields: [cat.column], rows: rowsClause(rep),
      node: <RankedBars data={rows} total={rep.rows_analyzed} />, head: [cat.column, "Records"], table: rows.map((r) => [r.label, r.value.toLocaleString()]),
    });
  });
  const c = ins?.coordinates;
  if (c) out.push({
    key: "coords", title: "Coordinate coverage",
    caption: <>A row counts when both coordinates are present, in range and not 0,0. Points are plotted without a basemap.</>,
    fields: [c.lat, c.lon], rows: rowsClause(rep) + (c.points.length ? `; ${c.points.length.toLocaleString()} points plotted` : ""),
    node: (
      <div>
        <p className="font-display text-3xl font-extrabold tabular-nums">{c.valid_pct}%<span className="ml-2 text-sm font-semibold text-ink-soft">of rows have a usable location</span></p>
        <div className="mt-3"><CoverageBar parts={[
          { label: "Valid pair", value: c.valid, tone: "ok" },
          { label: "Missing a coordinate", value: c.missing_either, tone: "muted" },
          { label: "At 0,0 or out of range", value: c.zero_pairs + c.out_of_range, tone: "bad" },
        ]} /></div>
        {c.bbox && c.points.length > 0 && <div className="mt-3"><PointMap points={c.points} bbox={c.bbox} /></div>}
      </div>
    ),
    head: ["Rows", "Count"], table: [["Valid pair", String(c.valid)], ["Missing a coordinate", String(c.missing_either)], ["At 0,0", String(c.zero_pairs)], ["Out of range", String(c.out_of_range)]],
  });
  if (t && t.series.length >= 2) out.push({
    key: "per-period", title: `Records per ${t.grain}`, caption: <>{t.missing ? `${t.missing.toLocaleString()} rows have no date and are left out.` : "Every analyzed row has a date."}</>,
    fields: [t.column], rows: rowsClause(rep, rep.rows_analyzed - (t.missing ?? 0)),
    node: <Columns data={t.series.map(([k, v]) => [t.grain === "month" ? `${MONTHS[Number(k.slice(5, 7)) - 1]} ${k.slice(2, 4)}` : k, v])} unit="records" />,
    head: [t.grain === "month" ? "Month" : "Year", "Records"], table: t.series.map(([k, v]) => [k, v.toLocaleString()]),
  });
  if (t?.by_month_of_year && t.by_month_of_year.filter(([, v]) => v).length >= 3) out.push({
    key: "moy", title: "Records by month of year", caption: "All years combined.", fields: [t.column], rows: rowsClause(rep, rep.rows_analyzed - (t.missing ?? 0)),
    node: <Columns data={t.by_month_of_year.map(([m, v]) => [MONTHS[m - 1], v])} unit="records" labelEvery={1} />,
    head: ["Month", "Records"], table: t.by_month_of_year.map(([m, v]) => [MONTHS[m - 1], v.toLocaleString()]),
  });
  const trended = new Set(tr?.series.map((s) => s.column));
  const relRank = new Map((ins?.relationships?.items ?? []).map((d, i) => [d.column, i]));
  const numbers = [...(ins?.numbers ?? [])].filter((m) => !trended.has(m.column))
    .sort((a, b) => (a.column === target?.column ? -1 : b.column === target?.column ? 1 : (relRank.get(a.column) ?? 99) - (relRank.get(b.column) ?? 99)));
  numbers.slice(0, 2).forEach((m) => out.push({
    key: m.column === target?.column ? "num-target" : `num-${m.column}`,
    title: m.column === target?.column ? `Distribution of ${m.column}` : `Distribution of ${m.column}`,
    caption: m.kind === "counts" ? <>Rows per value of {m.column}.</>
      : <>How {m.column} is spread across 12 equal-width bins{m.column === target?.column ? `; it's the field this table appears to describe (${target.reason})` : ""}.{m.missing ? ` ${m.missing.toLocaleString()} rows have no value.` : ""}{" "}
        {target?.column === m.column && !target.unit ? "No unit is stated in the file, so none is shown." : ""}</>,
    fields: [m.column], rows: rowsClause(rep, rep.rows_analyzed - m.missing),
    node: m.kind === "counts"
      ? <Columns data={m.values!.map(([k, v]) => [String(k), v])} unit="rows" labelEvery={1} xLabel={m.column} yLabel="Rows" />
      : <Columns data={m.bins!.map(([a, , v]) => [Number(a).toLocaleString(undefined, { maximumFractionDigits: 1 }), v])} unit="rows" labelEvery={2}
          xLabel={withUnit(`${m.column} (bin start)`, m.column === target?.column ? target.unit : null)} yLabel="Rows" />,
    head: m.kind === "counts" ? ["Value", "Records"] : ["Range", "Records"],
    table: m.kind === "counts" ? m.values!.map(([k, v]) => [String(k), v.toLocaleString()]) : m.bins!.map(([a, b, v]) => [`${a} to ${b}`, v.toLocaleString()]),
  }));
  if (quality.length) out.push({
    key: "missingness", title: "Fields with the most missing data", caption: `The ${quality.length} columns with the most empty values, as a share of analyzed rows.`,
    fields: quality.slice(0, 3).map((c) => c.name).concat(quality.length > 3 ? [`+${quality.length - 3} more shown`] : []), rows: rowsClause(rep),
    node: <RankedBars data={quality.map((c) => ({ label: c.name, value: c.missing_pct, tone: c.missing_pct >= 50 ? "warn" : undefined }))} percentages />,
    head: ["Field", "Missing rows"],
    table: quality.map((c) => [c.name, `${n0(c.missing_pct)}% (${c.missing.toLocaleString()})`]),
  });
  const events = !!t?.weekday_hour?.length;
  const order = target && !tr
    ? ["num-target", "scatter", "assoc", "num", "cat-0", "coords", "per-period", "moy", "cat-1", "missingness"]
    : events
    ? ["weekday-hour", "per-period", "cat-0", "injury-outcomes", "coords", "missingness", "moy", "cat-1", "trend-0", "trend-1", "hourly-measure", "num"]
    : ["trend-0", "seasonal", "hourly-measure", "trend-1", "per-period", "num-target", "scatter", "assoc", "cat-0", "coords", "by-hour", "moy", "cat-1", "num", "missingness"];
  const cats = (ins?.categories ?? []).map((cc) => `cat-${cc.column}`);
  const trends = (tr?.series ?? []).map((s) => `trend-${s.column}`);
  const slot = (k: string) => {
    const name = cats.includes(k) ? `cat-${cats.indexOf(k)}` : trends.includes(k) ? `trend-${trends.indexOf(k)}` : k === "num-target" ? k : k.startsWith("num-") ? "num" : k;
    const i = order.indexOf(name);
    return i < 0 ? order.length : i;
  };
  const sorted = out.map((c, i) => ({ c, i })).sort((a, b) => slot(a.c.key) - slot(b.c.key) || a.i - b.i).map(({ c }) => c);
  // The first chart leads full width; the rest pair up, with a wide chart only where it needs the space.
  // A table with a target opens on a pair (its distribution beside its strongest relationship), like the pack reports.
  const leadWide = !(target && !tr && sorted[1]?.key === "scatter");
  return sorted.map((c, i) => ({ ...c, wide: (i === 0 && leadWide) || c.key === "weekday-hour" || c.key === "seasonal" }));
}

/** Free-text labels (compositions, names, IDs): many distinct values, none common. Ranking them says nothing. */
function labelLike(cat: { distinct: number; values: [string, number][] }, rows: number) {
  return cat.distinct > Math.max(20, rows * 0.25) && (cat.values[0]?.[1] ?? 0) < rows * 0.05;
}

function targetTiles(rep: AnalysisReport): { label: string; value: ReactNode; hint?: string }[] {
  const tg = rep.insights?.target;
  const col = tg && rep.columns.find((c) => c.name === tg.column);
  if (!tg || !col || typeof col.median !== "number") return [];
  const out: { label: string; value: ReactNode; hint?: string }[] = [
    { label: `Median ${tg.column}`, value: <>{n0(col.median as number)}{tg.unit ? <span className="ml-1 text-base text-ink-faint">{tg.unit}</span> : null}</>,
      hint: `${n0(col.min as number)} to ${n0(col.max as number)}${tg.unit ? "" : "; no unit stated in the file"}` },
  ];
  const top = rep.insights?.relationships?.enough ? rep.insights.relationships.items[0] : undefined;
  if (top) out.push({ label: "Strongest association", value: `${top.pearson >= 0 ? "+" : "−"}${Math.abs(top.pearson).toFixed(2)}`, hint: `Pearson r with ${top.column} (n = ${top.n})` });
  return out;
}

function headline(rep: AnalysisReport, title: string): string {
  const ins = rep.insights;
  const parts: string[] = [];
  const total = rep.rows_total != null && rep.coverage === "sample" ? ` of ${rep.rows_total.toLocaleString()}` : "";
  if (rep.kind === "images" && rep.images) {
    const im = rep.images;
    const cls = im.class_images.length ? `${im.class_images.length} classes (${im.class_images.map(([k, v]) => `${k}: ${v}`).slice(0, 3).join(", ")})` : null;
    return `${title}: ${[`${rep.rows_analyzed.toLocaleString()}${total} images`, cls, im.objects ? `${im.objects.toLocaleString()} annotated objects` : null,
      `${im.annotated_pct}% annotated`].filter(Boolean).join("; ")}`;
  }
  if (rep.kind === "sinex" && rep.sinex) {
    const sx = rep.sinex;
    return `${title}: ${sx.stations} stations, ${sx.with_position} with coordinates and ${sx.with_velocity} with velocities; ${sx.data_start?.slice(0, 10)} to ${sx.data_end?.slice(0, 10)}${sx.agency ? ` (${sx.agency})` : ""}`;
  }
  if (rep.trajectory) {
    const tr = rep.trajectory;
    return `${title}: ${tr.points_total.toLocaleString()} epochs from ${tr.times[0]} to ${tr.times.at(-1)}; ${tr.maneuvers.length} maneuvers${tr.maneuvers.length ? ` (${[...new Set(tr.maneuvers.map((m) => m.label))].join(", ")})` : ""}`;
  }
  parts.push(`${rep.rows_analyzed.toLocaleString()}${total} rows`);
  const tg = ins?.target && rep.columns.find((c) => c.name === ins.target!.column);
  const top = ins?.relationships?.enough ? ins.relationships.items[0] : undefined;
  if (tg && typeof tg.min === "number") parts.push(`${tg.name} ${n0(tg.min as number)} to ${n0(tg.max as number)} (median ${n0(tg.median as number)})`);
  if (top) parts.push(`most associated with ${top.column} (r = ${top.pearson >= 0 ? "+" : "−"}${Math.abs(top.pearson).toFixed(2)})`);
  if (rep.date_coverage) parts.push(`${rep.date_coverage.min.slice(0, 10)} to ${rep.date_coverage.max.slice(0, 10)}`);
  const s = ins?.trends?.series[0];
  const mean = rep.columns.find((c) => c.name === s?.column)?.mean;
  if (s && typeof mean === "number") parts.push(`average ${s.column} ${n0(mean)}`);
  const cat = ins?.categories?.find((cc) => !labelLike(cc, rep.rows_analyzed));
  if (cat?.values[0]) parts.push(`top ${cat.column}: ${cat.values[0][0]} (${Math.round((100 * cat.values[0][1]) / rep.rows_analyzed)}%)`);
  if (ins?.coordinates) parts.push(`${ins.coordinates.valid_pct}% with usable coordinates`);
  return `${title}: ${parts.join("; ")}`;
}

type Check = { name: string; state: "pass" | "fail" | "caution"; detail: string };

function checks(rep: AnalysisReport): Check[] {
  const out: Check[] = [];
  const skipped = rep.rows_skipped ?? 0;
  out.push({ name: "Every row parsed", state: skipped ? "fail" : "pass", detail: skipped ? `${skipped.toLocaleString()} rows skipped (${rep.skip_reasons?.join(", ")})` : "No malformed rows" });
  if (rep.duplicate_rows !== null) out.push({ name: "No exact duplicates", state: rep.duplicate_rows ? "fail" : "pass", detail: `${rep.duplicate_rows.toLocaleString()} duplicate rows` });
  const sparse = rep.columns.filter((c) => c.missing_pct >= 50);
  out.push({ name: "Columns mostly filled", state: sparse.length ? "caution" : "pass", detail: sparse.length ? `${sparse.length} of ${rep.columns.length} columns are at least half empty` : "Every column is at least half filled" });
  const c = rep.insights?.coordinates;
  if (c) out.push({ name: "Locations usable", state: c.valid_pct >= 90 ? "pass" : "caution", detail: `${c.valid_pct}% of rows have a valid latitude-longitude pair` });
  if (rep.coverage === "sample") {
    const ordered = (rep.sample_method ?? "").includes("first");
    out.push({ name: "Sample represents the table", state: ordered ? "caution" : "pass",
      detail: ordered ? "First rows in source order, not a random draw" : (rep.sample_method ?? "Sampled rows") });
  }
  return out;
}

/** One chart card in the Bengaluru Run view style: the chart on white with its title inside, then a caption that
 * starts with the title in bold and says what the chart shows, which fields it uses and which rows it includes. */
function Figure({ chart, lead = false }: { chart: Chart; lead?: boolean }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className={`glass flex min-w-0 flex-col rounded-3xl p-3 ${chart.wide ? "lg:col-span-2" : ""}`} data-chart={chart.key}>
      <div className="relative rounded-2xl bg-white px-3 pb-2 pt-3 dark:bg-white/90">
        <div className="mb-1 flex items-start justify-between gap-3">
          <p className={`flex-1 text-center font-semibold text-ink ${lead ? "text-[15px]" : "text-sm"}`}>{chart.title}</p>
          <button className="shrink-0 rounded-lg px-2 py-0.5 text-xs font-semibold text-ink-soft ring-1 ring-ink/10 hover:bg-sky-wash" aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}>
            {asTable ? "Chart" : "Table"}
          </button>
        </div>
        {asTable ? (
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead><tr>{chart.head.map((h) => <th key={h} className="sticky top-0 border-b border-sky-deep bg-white px-3 py-1.5 text-left font-semibold">{h}</th>)}</tr></thead>
              <tbody>{chart.table.map(([a, b], i) => <tr key={i} className="odd:bg-sky-wash/50"><td className="px-3 py-1">{a}</td><td className="px-3 py-1 tabular-nums">{b}</td></tr>)}</tbody>
            </table>
          </div>
        ) : chart.node}
      </div>
      <figcaption className="px-2 pb-1 pt-3 leading-relaxed">
        <span className="font-semibold">{chart.title}.</span>{" "}
        <span className="text-sm text-ink-soft">
          {chart.caption}
          {chart.fields?.length ? <> Fields: {chart.fields.map((f, i) => <Fragment key={f}>{i ? ", " : ""}{f.startsWith("+") ? f.slice(1) : <code className="text-[12.5px] [overflow-wrap:anywhere]">{f}</code>}</Fragment>)}.</> : null}
          {chart.rows ? <> Rows: {chart.rows}.</> : null}
        </span>
      </figcaption>
    </figure>
  );
}

/** Expandable table that mounts its content only when opened (saved reports open fast; big tables load on demand). */
function Lazy({ title, children, open = false, onOpen }: { title: string; children: () => ReactNode; open?: boolean; onOpen?: () => void }) {
  const [shown, setShown] = useState(open);
  return (
    <details className="glass group rounded-3xl p-4" open={open} onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) { setShown(true); onOpen?.(); } }}>
      <summary className="cursor-pointer select-none font-display text-lg font-bold">{title}</summary>
      {shown && <div className="mt-3">{children()}</div>}
    </details>
  );
}

function FirstRows({ run }: { run: AnalysisRun }) {
  const rep = run.report!;
  const [rows, setRows] = useState<unknown[][] | null>(rep.preview ?? null);
  useEffect(() => {
    if (!rows) api.analysisDetails(run.id).then((d) => setRows(d.preview)).catch(() => setRows([]));
  }, [run.id, rows]);
  if (!rows) return <p className="text-sm text-ink-soft">Loading rows…</p>;
  return (
    <div className="max-h-96 overflow-auto rounded-2xl bg-white/80">
      <table className="w-full text-sm">
        <thead><tr>{rep.columns.map((c) => <th key={c.name} className="sticky top-0 border-b border-sky-deep bg-white px-3 py-2 text-left font-semibold">{c.name}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="odd:bg-sky-wash/50">{r.map((v, j) => <td key={j} className="max-w-[320px] truncate px-3 py-1.5 text-ink-soft">{v === null ? "—" : String(v)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

const TIMING_LABEL: Record<string, string> = { discovery_ms: "File discovery", preflight_ms: "File check", probe_ms: "Probe", list_ms: "Archive directory",
  range_fetch_ms: "Ranged member reads", download_ms: "Download", extract_ms: "Extraction", profile_ms: "Profiling", charts_ms: "Chart data", save_ms: "Saving" };

function Timings({ rep }: { rep: AnalysisReport }) {
  const t = rep.timings ?? {};
  const f = rep.fetch;
  return (
    <div className="space-y-2 text-sm">
      {f && (
        <p className="text-ink-soft">
          {f.cache === "hit" ? "Reused the cached download: nothing transferred." : f.cache === "range"
            ? `Read only the needed files with HTTP byte ranges: ${sizeLabel(f.transferred_bytes)} of a ${sizeLabel(f.source_bytes)} archive (${f.requests ?? "?"} requests).`
            : `Transferred ${sizeLabel(f.transferred_bytes)}${f.source_bytes ? ` of ${sizeLabel(f.source_bytes)}` : ""}.`}
        </p>
      )}
      <dl className="grid grid-cols-[11rem_1fr] gap-x-3 gap-y-1">
        {Object.entries(t).filter(([k]) => TIMING_LABEL[k]).map(([k, v]) => (
          <Fragment key={k}><dt className="text-ink-faint">{TIMING_LABEL[k]}</dt><dd className="tabular-nums">{(v / 1000).toFixed(2)} s</dd></Fragment>
        ))}
      </dl>
    </div>
  );
}

function Details({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="glass group rounded-3xl p-4" open={open}>
      <summary className="cursor-pointer select-none font-display text-lg font-bold">{title}</summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

export default function AnalysisResults({ run, title }: { run: AnalysisRun; title: string }) {
  const rep = run.report!;
  if (rep.kind === "inspection") return <InspectionResults run={run} sourceUrl={run.source.canonicalUrl} />;
  const special = kindCharts(rep);
  const charts = pack(special.length
    ? [...special, ...buildCharts(rep).filter((c) => keepGeneric(rep, c.key))].map((c, i) => ({ ...c, wide: i === 0 || c.wide }))
    : buildCharts(rep));
  // Summary and lead charts paint first; the rest of the grid mounts on the next frame.
  const [all, setAll] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setAll(true)));
    return () => cancelAnimationFrame(id);
  }, [run.id]);
  const visible = all ? charts : charts.slice(0, 2);
  useEffect(() => { // browser-side instrumentation: when the summary and lead charts are on screen, since navigation start
    const id = requestAnimationFrame(() => {
      const ms = Math.round(performance.now());
      document.documentElement.dataset.reportPaintMs = String(ms);
      performance.mark?.("report-painted");
      console.info(`[report] run ${run.id}: summary and lead charts painted ${ms} ms after navigation start`);
    });
    return () => cancelAnimationFrame(id);
  }, [run.id]);
  const cs = [...checks(rep).filter((c) => !(rep.kind === "images" && c.name === "Columns mostly filled")), ...kindChecks(rep)];
  const tiles: { label: string; value: ReactNode; hint?: string }[] = kindTiles(rep) ?? [
    { label: rep.coverage === "full" ? "Rows" : "Rows analyzed", value: rep.rows_analyzed.toLocaleString(),
      hint: rep.coverage === "full" ? (rep.paged_source ? `${scopeLabel(rep)}: every fetched row, matched to the source count`
        : rep.scope?.kind === "worksheet" ? `Every row of worksheet “${rep.scope.sheet}”` : `${scopeLabel(rep)}: every row of the file`) : rep.rows_total != null ? `of ${rep.rows_total.toLocaleString()} in the source` : "Source total unknown" },
    ...(rep.date_coverage || !rep.insights?.target ? [{ label: "Date range", value: rep.date_coverage ? `${rep.date_coverage.min.slice(0, 4)}–${rep.date_coverage.max.slice(0, 4)}` : "None",
      hint: rep.date_coverage ? `${fmtDate(rep.date_coverage.min)} to ${fmtDate(rep.date_coverage.max)}` : "No date or timestamp column" }] : []),
    ...targetTiles(rep),
    { label: "Missing cells", value: `${rep.missing_pct}%`, hint: `${rep.columns.filter((c) => c.missing > 0).length} of ${rep.columns.length} columns have gaps` },
  ];
  const ins = rep.insights;
  if (!kindTiles(rep)) {
  if (ins?.coordinates) tiles.push({ label: "With coordinates", value: `${ins.coordinates.valid_pct}%`, hint: `${ins.coordinates.valid.toLocaleString()} rows with a valid pair` });
  const measure = rep.columns.find((c) => c.name === ins?.trends?.series[0]?.column);
  if (measure && typeof measure.mean === "number") {
    tiles.push({ label: `Average ${pretty(measure.name).toLowerCase()}`, value: n0(measure.mean), hint: "Average across non-missing readings" });
  }
  const tileCat = ins?.categories?.find((cc) => !labelLike(cc, rep.rows_analyzed));
  if (tileCat && tiles.length < 5) {
    const cat = tileCat;
    tiles.push({ label: `Top ${cat.column}`, value: cat.values[0]?.[0] ?? "—", hint: cat.values[0] ? `${Math.round((100 * cat.values[0][1]) / rep.rows_analyzed)}% of rows` : undefined });
  }
  if (tiles.length < 5) tiles.push({ label: "Duplicate rows", value: rep.duplicate_rows === null ? "n/a" : rep.duplicate_rows.toLocaleString(), hint: "Exact copies of another row" });
  }
  const passed = cs.filter((c) => c.state === "pass").length;

  return (
    <section className="space-y-5 [--analysis-series:rgb(var(--c-chart-green))]" aria-label="Results">
      <div className="glass-strong rounded-3xl p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <ScopeBadge rep={rep} />
          <span className="text-xs text-ink-faint">Generated {new Date(run.finished_at ?? run.created_at).toLocaleString()} · run {run.id}</span>
          <a className="btn-ghost ml-auto" href={api.url(`/api/analyses/${run.id}/notebook`)} title="Generated from this run: loads the same rows and repeats the checks">
            <Download size={15} /> Profiling notebook (generated)
          </a>
        </div>
        <p className="mt-3 font-display text-xl font-semibold leading-snug sm:text-2xl">{headline(rep, title)}</p>
        {rep.coverage === "sample" && (
          <p className="mt-2 text-sm text-ink-soft">These are real records, {rep.sample_method}. They describe these {unitOf(rep)} only, not the whole dataset.</p>
        )}
        {rep.scope?.kind === "worksheet" && (
          <p className="mt-1 text-sm text-ink-soft">Worksheet <strong className="text-ink">{rep.scope.sheet}</strong> of <code className="break-all">{rep.scope.file}</code>
            {rep.scope.sheets && rep.scope.sheets.length > 1 ? ` (${rep.scope.sheets.length} sheets: ${rep.scope.sheets.join(", ")}; choose another in Settings)` : ""}.</p>
        )}
        {rep.scope?.kind === "file" && rep.scope.file && <p className="mt-1 text-sm text-ink-soft">Every row of <code className="break-all">{rep.scope.file}</code>, one file of this dataset.</p>}
        {rep.handler_label && rep.kind !== "table" && <p className="mt-1 text-sm text-ink-soft">Analyzed as {rep.handler_label.toLowerCase()} (detected {rep.detected_type}{rep.analyzed_file ? `, ${rep.analyzed_file}` : ""}).</p>}
        {rep.params?.dateFrom || rep.params?.dateTo ? <p className="mt-1 text-sm text-ink-soft">Date range: {rep.params.dateFrom ?? "start"} to {rep.params.dateTo ?? "end"} on <code>{rep.params.dateField}</code>.</p> : null}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {tiles.slice(0, 5).map((m) => (
          <div key={m.label} className="glass rounded-3xl p-4" title={m.hint}>
            <p className="text-sm text-ink-soft">{m.label}</p>
            <p className="mt-1 truncate font-display text-3xl font-bold leading-none">{m.value}</p>
            {m.hint && <p className="mt-2 text-xs leading-snug text-ink-faint">{m.hint}</p>}
          </div>
        ))}
      </div>

      <div className="glass rounded-3xl p-5">
        <h3 className="text-lg font-bold">Data-quality checks <span className="font-body text-sm font-semibold text-ink-soft">{passed} of {cs.length} passed</span></h3>
        <ul className="mt-3 grid gap-2 md:grid-cols-3">
          {cs.map((c) => (
            <li key={c.name} className="flex gap-3 rounded-2xl bg-white/75 p-3">
              {c.state === "pass" ? <CheckCircle2 className="shrink-0 text-ok" size={20} aria-label="Passed" />
                : c.state === "fail" ? <XCircle className="shrink-0 text-bad" size={20} aria-label="Failed" />
                  : <AlertTriangle className="shrink-0 text-warn" size={20} aria-label="Caution" />}
              <div>
                <p className="text-sm font-semibold">{c.name}</p>
                <p className="text-xs text-ink-soft">{c.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {ins?.error && <p className="glass rounded-3xl p-5 text-sm text-ink-soft">Some visual insights could not be generated for this run. The saved profile and schema are available below.</p>}
      {charts.length > 0 ? (
        <div className="space-y-3">
          <h3 className="font-display text-xl font-bold">Visual insights</h3>
          <div className="grid gap-4 lg:grid-cols-2">{visible.map((c, i) => <Figure key={c.key} chart={c} lead={i === 0} />)}</div>
        </div>
      ) : !ins?.error && (
        <p className="glass rounded-3xl p-5 text-sm text-ink-soft">This run has no saved charts. Run again to generate visual insights from supported fields.</p>
      )}

      {rep.images && <ImagePreviews previews={rep.images.previews} note={rep.images.previews.some((p) => p.shapes.length) ? "Annotation shapes drawn over the image, scaled to its size." : undefined} />}
      <PairTable rep={rep} />

      <div className="space-y-3">
        {rep.archive && <Details title="Archive contents"><ArchiveDetails rep={rep} /></Details>}
        {rep.sinex && (
          <Details title="SINEX header and reference">
            <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-ink-faint">files</dt><dd>{rep.sinex.files.join(", ")}</dd>
              <dt className="text-ink-faint">version / agency</dt><dd>{rep.sinex.version} · {rep.sinex.agency} · technique {rep.sinex.technique}</dd>
              <dt className="text-ink-faint">frame</dt><dd>{rep.sinex.frame === "terrestrial" ? "Earth-fixed (positions converted on GRS80)" : "unknown: positions not converted"}</dd>
              {Object.entries(rep.sinex.reference).map(([k, v]) => <Fragment key={k}><dt className="text-ink-faint">{k.toLowerCase()}</dt><dd>{v}</dd></Fragment>)}
            </dl>
          </Details>
        )}
        <Lazy title={rep.kind === "images" ? "Image index schema" : rep.kind === "sinex" ? "Station table schema" : "Schema"}>{() => <SchemaTable rep={rep} bare />}</Lazy>
        <Lazy title={`First ${rep.preview?.length ?? rep.preview_deferred ?? 20} rows`}>{() => <FirstRows run={run} />}</Lazy>
        <Lazy title="Run log and timings">{() => (
          <div className="space-y-3">
            <Timings rep={rep} />
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl bg-white/80 p-3 text-xs leading-5 [overflow-wrap:anywhere]">{run.log || "No log."}</pre>
          </div>
        )}</Lazy>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Notes</h3>
          <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-ink-soft">
            {(ins?.findings ?? []).map((f, i) => <li key={i}>{f.text}</li>)}
            {!ins?.findings?.length && <li>No notes for this run.</li>}
          </ul>
        </div>
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Where this data came from</h3>
          <dl className="mt-2 grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-ink-faint">source</dt><dd><a className="break-all text-link underline" href={run.source.canonicalUrl} target="_blank" rel="noreferrer">{run.source.provider}</a></dd>
            <dt className="text-ink-faint">read from</dt><dd className="break-all">{rep.source_url ?? run.file_url ?? `${run.file_name} (uploaded)`}</dd>
            <dt className="text-ink-faint">license</dt><dd>{run.source.license ?? "Unknown"}</dd>
            <dt className="text-ink-faint">version</dt><dd>{fmtDate(run.source.version)}</dd>
            <dt className="text-ink-faint">sha-256</dt><dd className="break-all font-mono text-xs">{run.file_sha256 ?? "—"}</dd>
          </dl>
        </div>
      </div>
    </section>
  );
}
