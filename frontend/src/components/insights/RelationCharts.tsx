/** Relationship and comparison charts for imported data: scatter (two numeric fields), signed association bars,
 * and a period comparison (one line per year, the latest in the series color, earlier years recessive gray). */
import { useState } from "react";
import { GRID, MUTED, SERIES, useNarrow, useTip } from "./Charts";

const nf = (v: number, d = 2) => v.toLocaleString(undefined, { maximumFractionDigits: d });

function ticks(lo: number, hi: number, n = 4) {
  const step = (hi - lo) / n;
  return Array.from({ length: n + 1 }, (_, i) => lo + i * step);
}

export function Scatter({ points, xLabel, yLabel }: { points: [number, number][]; xLabel: string; yLabel: string }) {
  const t = useTip();
  const nw = useNarrow();
  const W = 640, H = nw ? 400 : 300, L = nw ? 104 : 66, B = nw ? 76 : 44, T = nw ? 18 : 10, R = nw ? 24 : 10;
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (x0 === x1) { x0 -= 1; x1 += 1; }
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const px = (x1 - x0) * 0.04, py = (y1 - y0) * 0.06;
  x0 -= px; x1 += px; y0 -= py; y1 += py;
  const sx = (v: number) => L + ((v - x0) / (x1 - x0)) * (W - L - R);
  const sy = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  return (
    <div ref={t.box} className="relative" onMouseLeave={t.hide}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${yLabel} against ${xLabel}, ${points.length} points`} data-axes="">
        {ticks(y0, y1).map((v, i) => (
          <g key={`y${i}`}>
            <line x1={L} x2={W - R} y1={sy(v)} y2={sy(v)} stroke={GRID} />
            <text x={L - 6} y={sy(v) + 4} textAnchor="end" className="fill-ink-faint text-[11px]">{nf(v, Math.abs(y1 - y0) < 10 ? 2 : 0)}</text>
          </g>
        ))}
        {ticks(x0, x1).map((v, i) => (
          <text key={`x${i}`} x={sx(v)} y={H - B + (nw ? 26 : 16)} textAnchor="middle" className="fill-ink-faint text-[11px]" data-thin={i % 2 === 1 ? "" : undefined}>{nf(v, Math.abs(x1 - x0) < 10 ? 2 : 0)}</text>
        ))}
        <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke={GRID} />
        {points.map(([a, b], i) => (
          <circle key={i} cx={sx(a)} cy={sy(b)} r={4.5} fill={SERIES} fillOpacity={0.55} stroke="rgb(var(--c-white))" strokeWidth={1}
            onMouseMove={(e) => t.show(e, `${xLabel} ${nf(a, 3)}`, `${yLabel} ${nf(b, 3)}`)} />
        ))}
        <text x={L + (W - L - R) / 2} y={H - 6} textAnchor="middle" className="fill-ink-soft text-[12px] font-semibold">{xLabel}</text>
        <text transform={`translate(${nw ? 22 : 14} ${T + (H - T - B) / 2}) rotate(-90)`} textAnchor="middle" className="fill-ink-soft text-[12px] font-semibold">{yLabel}</text>
      </svg>
      {t.node}
    </div>
  );
}

/** Signed bars from a zero line: position carries the sign, the label carries the value. */
// label column shrinks (and truncates) before the bar track does, so bars stay readable on phones
const ROW = "grid grid-cols-[minmax(0,1.2fr)_minmax(5.5rem,1fr)_2.75rem] gap-2 sm:grid-cols-[minmax(0,13rem)_minmax(8rem,1fr)_3.5rem] sm:gap-3";

export function Associations({ items, target }: { items: { column: string; pearson: number; spearman: number | null; n: number }[]; target: string }) {
  return (
    <div role="img" aria-label={`Associations with ${target}`}>
      <div className={`mb-1 ${ROW} text-[11px] text-ink-faint`}>
        <span />
        <span className="flex justify-between"><span>−1<span className="hidden sm:inline"> opposite</span></span><span>0</span><span>+1<span className="hidden sm:inline"> together</span></span></span>
        <span className="text-right">r</span>
      </div>
      <ul className="space-y-1.5">
        {items.map((d) => {
          const w = Math.min(1, Math.abs(d.pearson)) * 50;
          return (
            <li key={d.column} className={`${ROW} items-center text-sm`}
              title={`${d.column}: Pearson r ${d.pearson.toFixed(2)}${d.spearman != null ? `, Spearman ρ ${d.spearman.toFixed(2)}` : ""}, n = ${d.n}`}>
              <span className="truncate text-ink-soft">{d.column}</span>
              <span className="relative h-3.5">
                <span className="absolute inset-y-[-3px] left-1/2 w-px" style={{ background: "rgb(var(--c-ink) / .25)" }} />
                <span className="absolute inset-y-0 rounded-[4px]" style={{ background: SERIES, width: `${w}%`, left: d.pearson >= 0 ? "50%" : `${50 - w}%` }} />
              </span>
              <span className="text-right tabular-nums text-ink-soft">{d.pearson >= 0 ? "+" : "−"}{Math.abs(d.pearson).toFixed(2)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

export function PeriodLines({ series, unit }: { series: { year: number; values: [number, number][] }[]; unit: string }) {
  const t = useTip();
  const [focus, setFocus] = useState<number | null>(null);
  const nw = useNarrow();
  const W = 640, H = nw ? 320 : 240, L = nw ? 92 : 58, B = nw ? 40 : 28, T = nw ? 18 : 10, R = nw ? 76 : 46;
  const vals = series.flatMap((s) => s.values.map((v) => v[1]));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const x = (m: number) => L + ((m - 1) / 11) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const latest = series[series.length - 1]?.year;
  return (
    <div ref={t.box} className="relative" onMouseLeave={() => { t.hide(); setFocus(null); }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${unit} by month, one line per year`} data-axes="">
        {ticks(lo, hi, 3).map((v, i) => (
          <g key={i}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={GRID} />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" className="fill-ink-faint text-[11px]">{nf(v)}</text>
          </g>
        ))}
        {MONTHS.map((m, i) => <text key={i} x={x(i + 1)} y={H - 8} textAnchor="middle" className="fill-ink-faint text-[11px]">{m}</text>)}
        {series.map((s) => {
          const isLatest = s.year === latest;
          const on = focus === null || focus === s.year;
          const d = s.values.map(([m, v], i) => `${i ? "L" : "M"}${x(m)},${y(v)}`).join(" ");
          const last = s.values[s.values.length - 1];
          return (
            <g key={s.year} onMouseEnter={() => setFocus(s.year)} opacity={on ? 1 : 0.35}>
              <path d={d} fill="none" stroke={isLatest ? SERIES : MUTED} strokeWidth={isLatest ? 2.5 : 2} strokeLinejoin="round" />
              {s.values.map(([m, v]) => <circle key={m} cx={x(m)} cy={y(v)} r={8} fill="transparent"
                onMouseMove={(e) => t.show(e, `${s.year}, month ${m}`, `${nf(v, 3)} ${unit}`)} />)}
              {last && <text x={x(last[0]) + 6} y={y(last[1]) + 4} className={`text-[11px] font-semibold ${isLatest ? "fill-ink" : "fill-ink-faint"}`}>{s.year}</text>}
            </g>
          );
        })}
      </svg>
      {t.node}
    </div>
  );
}
