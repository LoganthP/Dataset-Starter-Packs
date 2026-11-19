import { AlertTriangle, Info } from "lucide-react";
import type { AnalysisReport } from "../../types";
import { ChartCard, Columns, CoverageBar, PointMap, RankedBars } from "./Charts";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pretty = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function monthLabel(k: string) {
  const [y, m] = k.split("-");
  return m ? `${MONTHS[Number(m) - 1]} ${y.slice(2)}` : y;
}

/** Charts that switch on when the analyzed rows have the fields they need. Rendered above the schema. */
export default function InsightsView({ report }: { report: AnalysisReport }) {
  const ins = report.insights;
  if (!ins) return null;
  const n = report.rows_analyzed;
  const scope = report.coverage === "sample" ? `Sample · ${n.toLocaleString()} real records` : `All ${n.toLocaleString()} records`;
  const t = ins.time;
  const c = ins.coordinates;
  const findings = ins.findings ?? [];
  const nothing = !t && !c && !ins.categories?.length && !ins.numbers?.length;

  return (
    <section aria-labelledby="ins-h" className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 id="ins-h" className="font-display text-2xl font-bold">Insights</h2>
        <p className="text-sm text-ink-soft">Generated from the fields this table has. {report.coverage === "sample" ? "They describe the sampled rows only." : ""}</p>
      </div>

      {findings.length > 0 && (
        <ul className="glass space-y-2 rounded-3xl p-5" aria-label="Data-quality findings">
          {findings.map((f, i) => (
            <li key={i} className="flex gap-2.5 text-sm">
              {f.level === "warn" ? <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-label="Caution" /> : <Info size={16} className="mt-0.5 shrink-0 text-peri-ink" aria-label="Note" />}
              <span className="text-ink-soft">{f.text}</span>
            </li>
          ))}
        </ul>
      )}

      {nothing && <p className="glass rounded-3xl p-5 text-sm text-ink-soft">No date, category, numeric or coordinate fields suitable for charts were found. The schema below still describes every column.</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        {t && (
          <ChartCard title={`Records per ${t.grain}`} scope={scope}
            note={<>From <code>{t.column}</code>{t.missing ? `; ${t.missing.toLocaleString()} rows have no date and aren't shown` : ""}.</>}
            table={{ head: [t.grain === "month" ? "Month" : "Year", "Records"], rows: t.series.map(([k, v]) => [k, v.toLocaleString()]) }}>
            <Columns data={t.series.map(([k, v]) => [t.grain === "month" ? monthLabel(k) : k, v])} unit="records" />
          </ChartCard>
        )}
        {t?.by_month_of_year && (
          <ChartCard title="Records by month of year" scope={scope} note={<>All years combined, from <code>{t.column}</code>.</>}
            table={{ head: ["Month", "Records"], rows: t.by_month_of_year.map(([m, v]) => [MONTHS[m - 1], v.toLocaleString()]) }}>
            <Columns data={t.by_month_of_year.map(([m, v]) => [MONTHS[m - 1], v])} unit="records" labelEvery={1} />
          </ChartCard>
        )}
        {t?.by_hour && (
          <ChartCard title="Records by hour of day" scope={scope} note={<>From <code>{t.hour_column}</code>, local time as recorded.</>}
            table={{ head: ["Hour", "Records"], rows: t.by_hour.map(([h, v]) => [`${String(h).padStart(2, "0")}:00`, v.toLocaleString()]) }}>
            <Columns data={t.by_hour.map(([h, v]) => [String(h).padStart(2, "0"), v])} unit="records" labelEvery={3} />
          </ChartCard>
        )}
        {ins.categories?.map((cat) => {
          const rows = [
            ...cat.values.map(([k, v]) => ({ label: k, value: v })),
            ...(cat.other ? [{ label: `Other (${cat.distinct - cat.values.length} values)`, value: cat.other, muted: true }] : []),
            ...(cat.unknown ? [{ label: "Unknown (empty)", value: cat.unknown, muted: true }] : []),
          ];
          return (
            <ChartCard key={cat.column} title={`Records by ${pretty(cat.column).toLowerCase()}`} scope={scope}
              note={cat.unknown ? `${Math.round((100 * cat.unknown) / n)}% of rows have no ${cat.column}; they're shown as Unknown rather than dropped.` : undefined}
              table={{ head: [cat.column, "Records"], rows: rows.map((r) => [r.label, r.value.toLocaleString()]) }}>
              <RankedBars data={rows} total={n} />
            </ChartCard>
          );
        })}
        {c && (
          <ChartCard title="Coordinate coverage" scope={scope}
            note={<>A row counts when both <code>{c.lat}</code> and <code>{c.lon}</code> are present, in range and not 0,0. The map plots up to 2,000 valid points with no basemap.</>}
            table={{ head: ["Rows", "Count"], rows: [["Valid pair", String(c.valid)], ["Missing a coordinate", String(c.missing_either)], ["At 0,0", String(c.zero_pairs)], ["Out of range", String(c.out_of_range)]] }}>
            <p className="font-display text-3xl font-extrabold tabular-nums">{c.valid_pct}%<span className="ml-2 text-sm font-semibold text-ink-soft">of rows have a usable location</span></p>
            <div className="mt-3">
              <CoverageBar parts={[
                { label: "Valid pair", value: c.valid, tone: "ok" },
                { label: "Missing a coordinate", value: c.missing_either, tone: "muted" },
                { label: "At 0,0 or out of range", value: c.zero_pairs + c.out_of_range, tone: "bad" },
              ]} />
            </div>
            {c.bbox && c.points.length > 0 && <div className="mt-4"><PointMap points={c.points} bbox={c.bbox} /></div>}
          </ChartCard>
        )}
        {ins.numbers?.map((m) => (
          <ChartCard key={m.column} title={pretty(m.column)} scope={scope}
            note={m.missing ? `${m.missing.toLocaleString()} rows have no value.` : undefined}
            table={m.kind === "counts"
              ? { head: ["Value", "Records"], rows: m.values!.map(([k, v]) => [String(k), v.toLocaleString()]) }
              : { head: ["Range", "Records"], rows: m.bins!.map(([a, b, v]) => [`${a} to ${b}`, v.toLocaleString()]) }}>
            {m.kind === "counts"
              ? <Columns data={m.values!.map(([k, v]) => [String(k), v])} unit="records" labelEvery={1} />
              : <Columns data={m.bins!.map(([a, , v]) => [Number(a).toLocaleString(undefined, { maximumFractionDigits: 1 }), v])} unit="records" labelEvery={2} />}
          </ChartCard>
        ))}
      </div>
    </section>
  );
}
