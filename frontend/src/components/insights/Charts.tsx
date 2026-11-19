/**
 * Small single-series SVG charts for analysis insights. One hue (periwinkle, validated for contrast on the
 * light and dark surfaces); "Unknown" uses a recessive gray with a text label, never color alone.
 * Every chart has a hover/focus tooltip and a table view, so no value is gated behind hover.
 */
import { type ReactNode, useId, useRef, useState, useSyncExternalStore } from "react";

const NARROW = "(max-width: 640px)";
/** Phones scale a 640-unit chart to about half, so charts reserve wider margins there for 20-unit (~11px) axis text. */
export function useNarrow() {
  return useSyncExternalStore(
    (cb) => { const m = window.matchMedia(NARROW); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); },
    () => window.matchMedia(NARROW).matches, () => false);
}

export const SERIES = "var(--analysis-series, rgb(var(--c-peri)))";
export const MUTED = "rgb(var(--c-ink-faint) / .55)";
export const GRID = "rgb(var(--c-ink) / .08)";

const fmt = (v: number) => (Math.abs(v) >= 10_000 ? `${(v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}K` : v.toLocaleString());

export function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v)!;
}

type Tip = { x: number; y: number; title: string; value: string } | null;

export function useTip() {
  const box = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip>(null);
  const show = (e: { clientX: number; clientY: number } | null, title: string, value: string, el?: Element) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    let x: number, y: number;
    if (e) {
      x = e.clientX - r.left;
      y = e.clientY - r.top;
    } else {
      const b = (el as Element).getBoundingClientRect();
      x = b.left + b.width / 2 - r.left;
      y = b.top - r.top;
    }
    setTip({ x, y, title, value });
  };
  const node = tip && (
    <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+10px)] whitespace-nowrap rounded-xl bg-ink px-2.5 py-1.5 text-xs text-on-accent shadow-lift"
      style={{ left: tip.x, top: tip.y }}>
      <b className="block text-sm">{tip.value}</b>
      <span className="opacity-80">{tip.title}</span>
    </div>
  );
  return { box, show, hide: () => setTip(null), node };
}

/** Frame: title, scope note, chart, and a table view. */
export function ChartCard({ title, scope, note, table, children }: {
  title: string;
  scope: string;
  note?: ReactNode;
  table: { head: [string, string]; rows: [string, string][] };
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  return (
    <figure className="glass flex min-w-0 flex-col rounded-3xl p-5" aria-labelledby={id}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 id={id} className="font-display text-lg font-bold">{title}</h3>
        <span className="rounded-full bg-sun/40 px-2 py-0.5 text-[11px] font-bold text-warn-ink">{scope}</span>
        <button className="ml-auto text-xs font-semibold text-ink-soft underline-offset-2 hover:underline" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>
      <div className="mt-3 min-w-0">
        {asTable ? (
          <div className="max-h-72 overflow-auto rounded-2xl bg-white/80">
            <table className="w-full text-sm">
              <thead><tr>{table.head.map((h) => <th key={h} className="sticky top-0 border-b border-sky-deep bg-white px-3 py-1.5 text-left font-semibold">{h}</th>)}</tr></thead>
              <tbody>{table.rows.map(([a, b], i) => <tr key={i} className="odd:bg-sky-wash/50"><td className="px-3 py-1">{a}</td><td className="px-3 py-1 tabular-nums">{b}</td></tr>)}</tbody>
            </table>
          </div>
        ) : children}
      </div>
      {note && <figcaption className="mt-2 text-xs text-ink-faint">{note}</figcaption>}
    </figure>
  );
}

/** Vertical columns along an ordered axis (months, years, hours). */
export function Columns({ data, unit, labelEvery, xLabel, yLabel }: { data: [string, number][]; unit: string; labelEvery?: number; xLabel?: string; yLabel?: string }) {
  const t = useTip();
  const nw = useNarrow();
  const W = 640, H = nw ? (xLabel ? 320 : 280) : xLabel ? 222 : 200, L = nw ? (yLabel ? 96 : 72) : yLabel ? 58 : 40, B = nw ? (xLabel ? 74 : 40) : xLabel ? 44 : 24, T = nw ? 16 : 8;
  const max = niceMax(Math.max(...data.map((d) => d[1]), 1));
  const slot = (W - L) / Math.max(data.length, 1);
  const bw = Math.min(24, Math.max(2, slot - 2));
  const every = labelEvery ?? Math.max(1, Math.ceil(data.length / 8));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return (
    <div ref={t.box} className="relative" onMouseLeave={t.hide}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${data.length} columns of ${unit}`} data-axes="">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W} y1={y(max * f)} y2={y(max * f)} stroke={GRID} strokeWidth={1} />
            <text x={L - 6} y={y(max * f) + 4} textAnchor="end" className="fill-ink-faint text-[11px]">{fmt(max * f)}</text>
          </g>
        ))}
        {data.map(([k, v], i) => {
          const x = L + i * slot + (slot - bw) / 2;
          const h = H - B - y(v);
          return (
            <g key={k}>
              <rect x={L + i * slot} y={T} width={slot} height={H - T - B} fill="transparent"
                onMouseMove={(e) => t.show(e, k, `${v.toLocaleString()} ${unit}`)} tabIndex={-1} />
              {v > 0 && <path d={`M${x},${H - B} v${-Math.max(h - 4, 0)} q0,-4 4,-4 h${bw - 8 > 0 ? bw - 8 : 0} q4,0 4,4 v${Math.max(h - 4, 0)} z`}
                fill={SERIES} pointerEvents="none" />}
              {i % every === 0 && <text x={L + i * slot + slot / 2} y={H - B + (nw ? 26 : 16)} textAnchor="middle" className="fill-ink-faint text-[11px]" data-thin={(i / every) % 2 === 1 ? "" : undefined}>{k}</text>}
            </g>
          );
        })}
        <line x1={L} x2={W} y1={H - B} y2={H - B} stroke={GRID} strokeWidth={1} />
        {xLabel && <text x={L + (W - L) / 2} y={H - 4} textAnchor="middle" className="fill-ink-soft text-[12px] font-semibold">{xLabel}</text>}
        {yLabel && <text transform={`translate(${nw ? 22 : 14} ${T + (H - T - B) / 2}) rotate(-90)`} textAnchor="middle" className="fill-ink-soft text-[12px] font-semibold">{yLabel}</text>}
      </svg>
      {t.node}
    </div>
  );
}

/** Ranked horizontal bars with labels and values; Unknown/Other shown in gray, labelled. */
export function RankedBars({ data, total, percentages = false }: { data: { label: string; value: number; muted?: boolean; tone?: "bad" | "warn" }[]; total?: number; percentages?: boolean }) {
  const max = percentages ? 100 : Math.max(...data.map((d) => d.value), 1);
  return (
    <ul className="space-y-1.5" role="list">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[minmax(6rem,11rem)_1fr_4.5rem] items-center gap-3 text-sm" title={`${d.label}: ${d.value.toLocaleString()}`}>
          <span className={`truncate ${d.muted ? "italic text-ink-faint" : "text-ink-soft"}`}>{d.label}</span>
          <span className="h-3.5 rounded-r bg-transparent">
            <span className="block h-full rounded-r-[4px]" style={{ width: `${(100 * d.value) / max}%`, background: d.muted ? MUTED : d.tone ? `rgb(var(--c-${d.tone}))` : SERIES, minWidth: d.value ? 2 : 0 }} />
          </span>
          <span className="text-right tabular-nums text-ink-soft">{d.value.toLocaleString()}{percentages ? "%" : ""} <span className="text-xs text-ink-faint">{total ? `${Math.round((100 * d.value) / total)}%` : ""}</span></span>
        </li>
      ))}
    </ul>
  );
}

/** Points on an equirectangular projection (cos-latitude corrected). No basemap: shape and coverage only. */
export function PointMap({ points, bbox }: { points: [number, number][]; bbox: { min_lat: number; max_lat: number; min_lon: number; max_lon: number } }) {
  const t = useTip();
  const k = Math.cos(((bbox.min_lat + bbox.max_lat) / 2) * (Math.PI / 180));
  const spanX = Math.max((bbox.max_lon - bbox.min_lon) * k, 1e-4);
  const spanY = Math.max(bbox.max_lat - bbox.min_lat, 1e-4);
  const W = 640, pad = 12;
  const H = Math.min(420, Math.max(220, (W * spanY) / spanX));
  const sx = (W - 2 * pad) / spanX, sy = (H - 2 * pad) / spanY;
  const s = Math.min(sx, sy);
  const ox = pad + (W - 2 * pad - spanX * s) / 2, oy = pad + (H - 2 * pad - spanY * s) / 2;
  const px = (lon: number) => ox + (lon - bbox.min_lon) * k * s;
  const py = (lat: number) => oy + (bbox.max_lat - lat) * s;
  return (
    <div ref={t.box} className="relative" onMouseLeave={t.hide}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full rounded-2xl bg-sky-wash/70" role="img" aria-label={`${points.length} sampled locations`}>
        {points.map(([lat, lon], i) => (
          <circle key={i} cx={px(lon)} cy={py(lat)} r={2.6} fill={SERIES} fillOpacity={0.55}
            onMouseMove={(e) => t.show(e, "latitude, longitude", `${lat.toFixed(4)}, ${lon.toFixed(4)}`)} />
        ))}
        <text x={W - 8} y={H - 8} textAnchor="end" className="fill-ink-faint text-[10px]">
          {bbox.min_lat.toFixed(2)} to {bbox.max_lat.toFixed(2)} lat · {bbox.min_lon.toFixed(2)} to {bbox.max_lon.toFixed(2)} lon
        </text>
      </svg>
      {t.node}
    </div>
  );
}

/** Coverage meter: one whole split into valid / missing / invalid, with labels (not color alone). */
export function CoverageBar({ parts }: { parts: { label: string; value: number; tone: "ok" | "muted" | "bad" }[] }) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const color = { ok: SERIES, muted: MUTED, bad: "rgb(var(--c-bad) / .7)" };
  return (
    <div>
      <div className="flex h-4 overflow-hidden rounded-[4px]" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
        {parts.filter((p) => p.value).map((p, i) => (
          <span key={p.label} style={{ width: `${(100 * p.value) / total}%`, background: color[p.tone], marginLeft: i ? 2 : 0 }} title={`${p.label}: ${p.value}`} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color[p.tone] }} aria-hidden />
            {p.label}: <b className="tabular-nums text-ink">{p.value.toLocaleString()}</b> ({Math.round((100 * p.value) / total)}%)
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A measure over time (one series, 2px line, crosshair tooltip). Points are [ISO time, value]. */
export function LineChart({ points, unit, yLabel }: { points: [string, number][]; unit: string; yLabel?: string }) {
  const t = useTip();
  const nw = useNarrow();
  const W = 640, H = nw ? 300 : 220, L = nw ? (yLabel ? 104 : 84) : yLabel ? 66 : 48, B = nw ? 36 : 24, T = nw ? 16 : 8;
  const vals = points.map((p) => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const x = (i: number) => L + ((W - L - 6) * i) / Math.max(points.length - 1, 1);
  const y = (v: number) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const label = (iso: string) => {
    const dt = new Date(iso.replace(" ", "T"));
    if (Number.isNaN(dt.getTime())) return iso.slice(0, 10);
    const span = new Date(points[points.length - 1][0].replace(" ", "T")).getTime() - new Date(points[0][0].replace(" ", "T")).getTime();
    return span < 3 * 86400_000 ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : span < 400 * 86400_000 ? dt.toLocaleDateString([], { month: "short", day: "numeric" }) : String(dt.getFullYear());
  };
  const ticks = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  const [hover, setHover] = useState<number | null>(null);
  return (
    <div ref={t.box} className="relative" onMouseLeave={() => { t.hide(); setHover(null); }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${unit} over time, ${points.length} points`} data-axes=""
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          const i = Math.max(0, Math.min(points.length - 1, Math.round(((px - L) / (W - L - 6)) * (points.length - 1))));
          setHover(i);
          t.show(e, points[i][0].replace("T", " ").slice(0, 16), `${points[i][1].toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`);
        }}>
        {[0, 0.5, 1].map((f) => {
          const v = lo + (hi - lo) * f;
          return (
            <g key={f}>
              <line x1={L} x2={W} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth={1} />
              <text x={L - 6} y={y(v) + 4} textAnchor="end" className="fill-ink-faint text-[11px]">{v.toLocaleString(undefined, { maximumFractionDigits: 2 })}</text>
            </g>
          );
        })}
        <path d={`${d} L${x(points.length - 1)},${H - B} L${x(0)},${H - B} Z`} fill={SERIES} fillOpacity={0.1} />
        <path d={d} fill="none" stroke={SERIES} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="rgb(var(--c-ink) / .25)" strokeWidth={1} />
            <circle cx={x(hover)} cy={y(points[hover][1])} r={4.5} fill={SERIES} stroke="rgb(var(--c-white))" strokeWidth={2} />
          </g>
        )}
        {ticks.map((i) => <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} className="fill-ink-faint text-[11px]">{label(points[i][0])}</text>)}
        {yLabel && <text transform={`translate(${nw ? 22 : 14} ${T + (H - T - B) / 2}) rotate(-90)`} textAnchor="middle" className="fill-ink-soft text-[12px] font-semibold">{yLabel}</text>}
      </svg>
      {t.node}
    </div>
  );
}

/** Card preview (decorative; the card's text carries the numbers). */
export function Spark({ values, label, kind = "bars" }: { values: number[]; label: string; kind?: "bars" | "line" }) {
  if (kind === "line") {
    const W = 300, H = 90;
    let lo = Math.min(...values), hi = Math.max(...values);
    if (hi === lo) { hi += 1; lo -= 1; }
    const d = values.map((v, i) => `${i ? "L" : "M"}${((W * i) / Math.max(values.length - 1, 1)).toFixed(1)},${(4 + (H - 8) * (1 - (v - lo) / (hi - lo))).toFixed(1)}`).join(" ");
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label={label} preserveAspectRatio="none">
        <path d={d} fill="none" stroke={SERIES} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
    );
  }
  const max = Math.max(...values, 1);
  const W = 300, H = 90;
  const slot = W / Math.max(values.length, 1);
  const bw = Math.min(14, Math.max(2, slot - 2));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label={label} preserveAspectRatio="none">
      {values.map((v, i) => {
        const h = Math.max(1, ((H - 6) * v) / max);
        return <rect key={i} x={i * slot + (slot - bw) / 2} y={H - h} width={bw} height={h} rx={2} fill={SERIES} />;
      })}
    </svg>
  );
}

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Hour-by-weekday counts; the associated chart card also exposes the values as a table. */
export function WeekdayHeatmap({ counts }: { counts: [number, number, number][] }) {
  const tip = useTip();
  const cells = new Map(counts.map(([day, hour, value]) => [day * 24 + hour, value]));
  const max = Math.max(1, ...counts.map(([, , value]) => value));
  return (
    <div ref={tip.box} className="relative" onMouseLeave={tip.hide}>
      <svg viewBox="0 0 640 218" className="w-full" role="img" aria-label="Record counts by weekday and hour">
        {WEEKDAYS.map((day, d) => (
          <g key={day}>
            <text x={5} y={23 + d * 26} className="fill-ink-soft text-[12px]">{day}</text>
            {Array.from({ length: 24 }, (_, h) => {
              const value = cells.get((d + 1) * 24 + h) ?? 0;
              return <rect key={h} x={43 + h * 24.5} y={7 + d * 26} width={22} height={23} rx={3}
                fill={value ? SERIES : GRID} fillOpacity={value ? 0.18 + 0.82 * value / max : 1}
                onMouseMove={(e) => tip.show(e, `${day} ${String(h).padStart(2, "0")}:00`, `${value.toLocaleString()} records`)} />;
            })}
          </g>
        ))}
        {[0, 4, 8, 12, 16, 20, 23].map((h) => <text key={h} x={54 + h * 24.5} y={207} textAnchor="middle"
          className="fill-ink-soft text-[11px]">{String(h).padStart(2, "0")}:00</text>)}
      </svg>
      <p className="text-right text-xs text-ink-soft">Light to dark: fewer to more records · max {max.toLocaleString()} per cell</p>
      {tip.node}
    </div>
  );
}
