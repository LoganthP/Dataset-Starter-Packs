/** Report sections that depend on what was analyzed: image datasets, SINEX solutions, orbit trajectories,
 * and inspection-only results. Each returns charts in the same Figure format as table reports. */
import { Fragment, type ReactNode } from "react";
import { sizeLabel } from "../../api";
import type { AnalysisReport, AnalysisRun, ImagePreview, TrajectorySection } from "../../types";
import { Columns, PointMap, RankedBars } from "../insights/Charts";

export type Chart = { key: string; title: string; caption: ReactNode; node: ReactNode; table: [string, string][]; head: [string, string]; wide?: boolean;
  /** Fields the chart uses and which rows it includes: both are printed in the caption. */
  fields?: string[]; rows?: string };
type Tile = { label: string; value: ReactNode; hint?: string };
type Check = { name: string; state: "pass" | "fail" | "caution"; detail: string };

const n = (v: number) => v.toLocaleString();

export function kindCharts(rep: AnalysisReport): Chart[] {
  if (rep.kind === "images" && rep.images) return imageCharts(rep);
  if (rep.kind === "sinex" && rep.sinex) return sinexCharts(rep);
  if (rep.trajectory) return trajectoryCharts(rep.trajectory);
  return [];
}

/** Generic table charts that still add something next to the kind-specific ones. */
export function keepGeneric(rep: AnalysisReport, key: string): boolean {
  if (rep.kind === "images") return key === "coords";
  if (rep.kind === "sinex") return key === "missingness";
  if (rep.trajectory) return key !== `num-${rep.trajectory.time}` && !rep.trajectory.position.some((c) => key === `num-${c}`);
  return true;
}

export function kindTiles(rep: AnalysisReport): Tile[] | null {
  if (rep.kind === "images" && rep.images) {
    const im = rep.images;
    const classes = im.class_images.length || im.objects_by_class.length;
    return [
      { label: rep.coverage === "full" ? "Images" : "Images analyzed", value: n(im.analyzed), hint: rep.coverage === "full" ? "Every image in the archive" : `of ${n(im.total)} in the archive` },
      { label: "Classes", value: classes ? n(classes) : "None", hint: im.label_source ?? "No labels found" },
      { label: "Annotated", value: `${im.annotated_pct}%`, hint: `${n(im.annotated)} of ${n(im.analyzed)} images have a label or annotation file` },
      { label: im.objects ? "Objects" : "Typical size", value: im.objects ? n(im.objects) : (im.width ? `${im.width.median}×${im.height?.median}` : "—"),
        hint: im.objects ? `${n(im.with_objects)} images contain at least one` : "Median width × height in pixels" },
      { label: "Archive", value: sizeLabel(rep.transferred_bytes), hint: rep.archive ? `${sizeLabel(rep.archive.expanded_bytes)} expanded, ${n(rep.archive.extracted_files)} files read` : undefined },
    ];
  }
  if (rep.kind === "sinex" && rep.sinex) {
    const sx = rep.sinex;
    return [
      { label: "Stations", value: n(sx.stations), hint: `${n(sx.solutions)} station solutions` },
      { label: "Solution span", value: sx.data_start && sx.data_end ? `${sx.data_start.slice(0, 4)}–${sx.data_end.slice(0, 4)}` : "—", hint: `${sx.data_start?.slice(0, 10) ?? "?"} to ${sx.data_end?.slice(0, 10) ?? "?"}` },
      { label: "With coordinates", value: n(sx.with_position), hint: "STAX/STAY/STAZ estimates" },
      { label: "With velocities", value: n(sx.with_velocity), hint: "VELX/VELY/VELZ, rotated to east/north/up" },
      { label: "Median σ", value: sx.sigma_mm ? `${sx.sigma_mm.median} mm` : "—", hint: sx.sigma_mm ? `95th percentile ${sx.sigma_mm.p95} mm` : "No standard deviations" },
    ];
  }
  if (rep.kind === "inspection") return null;
  return null;
}

export function kindChecks(rep: AnalysisReport): Check[] {
  const out: Check[] = [];
  if (rep.archive?.skipped?.length) out.push({ name: "Archive paths safe", state: "caution", detail: `${rep.archive.skipped.length} entries skipped (${rep.archive.skipped[0].reason})` });
  else if (rep.archive) out.push({ name: "Archive paths safe", state: "pass", detail: `${n(rep.archive.members_total)} entries checked` });
  if (rep.images) {
    out.push({ name: "Images readable", state: rep.images.unreadable ? "fail" : "pass", detail: rep.images.unreadable ? `${rep.images.unreadable} could not be opened` : "Every analyzed image opened" });
    out.push({ name: "Annotations parsed", state: rep.images.unparsed_annotations.length ? "caution" : rep.images.annotated ? "pass" : "caution",
      detail: rep.images.unparsed_annotations[0] ?? (rep.images.annotated ? rep.images.label_source ?? "Labels found" : "No labels or annotation files found") });
  }
  if (rep.sinex) {
    out.push({ name: "Locations convertible", state: rep.sinex.located === rep.sinex.solutions ? "pass" : "caution",
      detail: rep.sinex.position_sources.length ? `From ${rep.sinex.position_sources.join(" and ")}` : "No coordinates to convert; no map" });
  }
  return out;
}

// ---------------------------------------------------------------- images
function imageCharts(rep: AnalysisReport): Chart[] {
  const im = rep.images!;
  const out: Chart[] = [];
  const imgRows = `${n(im.analyzed)} images analyzed` + (im.total > im.analyzed ? ` of ${n(im.total)} in the archive` : "");
  const labelField = im.label_source ?? (im.annotation_format_label ? `${im.annotation_format_label} files` : "folder names");
  if (im.class_images.length) out.push({
    key: "classes", title: "Class balance", caption: <>Images per class{im.label_source ? <>, from the {im.label_source}</> : null}. The rarest class sets how well a model can learn it.</>,
    fields: [labelField], rows: imgRows,
    node: <RankedBars data={im.class_images.map(([label, value]) => ({ label, value }))} total={im.analyzed} />,
    head: ["Class", "Images"], table: im.class_images.map(([k, v]) => [k, n(v)]),
  });
  if (im.objects_by_class.length) out.push({
    key: "objects", title: "Annotated objects by class", caption: <>{n(im.objects)} objects in {n(im.with_objects)} images ({im.annotation_format_label}). Images without objects are negatives, not missing labels.</>,
    fields: [labelField], rows: imgRows,
    node: <RankedBars data={im.objects_by_class.map(([label, value]) => ({ label, value }))} total={im.objects} />,
    head: ["Class", "Objects"], table: im.objects_by_class.map(([k, v]) => [k, n(v)]),
  });
  out.push({
    key: "coverage", title: "Annotation coverage", caption: "Images with a label (classification) or an annotation file (detection), against images without one.",
    fields: [labelField, "image files"], rows: imgRows,
    node: <RankedBars data={[{ label: "Annotated", value: im.annotated }, { label: "No annotation", value: im.analyzed - im.annotated, muted: true },
      ...(im.objects_by_class.length ? [{ label: "With objects", value: im.with_objects }] : [])]} total={im.analyzed} />,
    head: ["Images", "Count"], table: [["Annotated", n(im.annotated)], ["No annotation", n(im.analyzed - im.annotated)], ["With objects", n(im.with_objects)]],
  });
  if (im.dimensions.length) out.push({
    key: "dims", title: "Image dimensions", caption: im.width ? `Width ${im.width.min}–${im.width.max} px (median ${im.width.median}); height ${im.height?.min}–${im.height?.max} px.` : "Width × height in pixels.",
    fields: ["image width", "image height"], rows: imgRows,
    node: <Columns data={im.dimensions} unit="images" labelEvery={1} />, head: ["Width × height", "Images"], table: im.dimensions.map(([k, v]) => [k, n(v)]),
  });
  const parts = im.splits.length ? im.splits : im.folders;
  if (parts.length > 1) out.push({
    key: "folders", title: im.splits.length ? "Images by split" : "Images by folder", caption: "Where the images sit in the archive.",
    fields: ["archive paths"], rows: imgRows,
    node: <RankedBars data={parts.map(([label, value]) => ({ label, value }))} total={im.analyzed} />, head: ["Folder", "Images"], table: parts.map(([k, v]) => [k, n(v)]),
  });
  return out;
}

export function ImagePreviews({ previews, note }: { previews: ImagePreview[]; note?: string }) {
  if (!previews.length) return null;
  return (
    <div className="space-y-3">
      <h3 className="font-display text-xl font-bold">Preview overlays</h3>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {previews.map((p) => (
          <li key={p.file} className="glass rounded-3xl p-3">
            <div className="relative overflow-hidden rounded-2xl bg-ink/5">
              <img src={p.src} alt={`${p.file}${p.class ? `, class ${p.class}` : ""}${p.shapes.length ? `, ${p.shapes.length} annotated objects` : ""}`} className="block h-auto w-full" />
              {p.shapes.length > 0 && (
                <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
                  {p.shapes.map((s, i) => (
                    <polygon key={i} points={s.points.map(([x, y]) => `${x},${y}`).join(" ")} fill="rgb(var(--c-chart-green) / 0.18)"
                      stroke="rgb(255 255 255)" strokeWidth={0.006} vectorEffect="non-scaling-stroke" style={{ strokeWidth: 2 }} />
                  ))}
                </svg>
              )}
            </div>
            <p className="mt-2 truncate text-xs text-ink-soft" title={p.file}>{p.file}</p>
            <p className="text-xs text-ink-faint">{p.width}×{p.height}{p.class ? ` · class ${p.class}` : ""}{p.shapes.length ? ` · ${p.shapes.length} objects` : ""}</p>
          </li>
        ))}
      </ul>
      {note && <p className="text-sm text-ink-soft">{note}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- SINEX
function sinexCharts(rep: AnalysisReport): Chart[] {
  const sx = rep.sinex!;
  const out: Chart[] = [];
  const c = rep.insights?.coordinates;
  if (c?.bbox && c.points.length) out.push({
    key: "stations", wide: true, title: "Station locations", caption: <>{n(sx.located)} of {n(sx.solutions)} station solutions placed {sx.position_sources.join(" or ")}. No basemap: geodetic latitude and longitude only.</>,
    fields: ["SITE/ID", "SOLUTION/ESTIMATE STAX/STAY/STAZ"], rows: `${n(sx.located)} of ${n(sx.solutions)} station solutions`,
      node: <PointMap points={c.points} bbox={c.bbox} />, head: ["Rows", "Count"], table: [["Located", n(sx.located)], ["Without coordinates", n(sx.solutions - sx.located)]],
  });
  out.push({
    key: "types", title: "Estimated parameters", caption: <>Counts of SOLUTION/ESTIMATE entries by type. Units: {sx.units.map(([u, k]) => `${u} (${n(k)})`).join(", ")}.</>,
    fields: ["SOLUTION/ESTIMATE TYPE"], rows: `${n(sx.estimate_types.reduce((a, [, v]) => a + v, 0))} estimates`,
      node: <RankedBars data={sx.estimate_types.map(([label, value]) => ({ label, value }))} />, head: ["Type", "Estimates"], table: sx.estimate_types.map(([k, v]) => [k, n(v)]),
  });
  const speed = rep.columns.find((col) => col.name === "horizontal_speed_mm_yr");
  if (speed?.kind === "numeric") {
    const num = rep.insights?.numbers?.find((m) => m.column === "horizontal_speed_mm_yr");
    if (num?.bins) out.push({
      key: "speed", title: "Horizontal station velocity", caption: "mm per year from VELX/VELY/VELZ rotated into the local east-north frame.",
      fields: ["VELX", "VELY", "VELZ"], rows: `${n(num.bins.reduce((a, [, , v]) => a + v, 0))} stations with velocities`,
      node: <Columns data={num.bins.map(([a, , v]) => [Number(a).toFixed(1), v])} unit="stations" labelEvery={2} />,
      head: ["mm/yr from", "Stations"], table: num.bins.map(([a, b, v]) => [`${a} to ${b}`, n(v)]),
    });
  }
  return out;
}

// ---------------------------------------------------------------- trajectories
function trajectoryCharts(tr: TrajectorySection): Chart[] {
  const [xc, yc, zc] = tr.position;
  const markers = tr.maneuvers.slice(0, 40);
  return [
    {
      key: "orbit", wide: true, title: `Trajectory (${xc}–${yc} projection)`,
      caption: <>{n(tr.points_total)} epochs{tr.step > 1 ? `, every ${tr.step}th plotted` : ""}. Dots mark {markers.length ? `${markers.length} maneuvers` : "no maneuvers"}. {tr.units_note}</>,
      fields: [xc, yc], rows: `${n(tr.points_total)} epochs${tr.step > 1 ? `; every ${tr.step}th plotted` : ""}`,
      node: <OrbitPlot tr={tr} />, head: ["Time", `${xc}, ${yc}, ${zc}`],
      table: tr.points.slice(0, 400).map((p, i) => [tr.times[i], p.map((v) => v.toLocaleString(undefined, { maximumFractionDigits: 3 })).join(", ")]),
    },
    {
      key: "components", wide: true, title: "State components over time",
      caption: <>From <code>{tr.time}</code>{tr.time_kind === "mjd" ? " (Modified Julian Date, shown as UTC)" : ""}. Dashed lines are maneuvers{tr.maneuver_labels_source ? `; labels from the ${tr.maneuver_labels_source}` : ""}.</>,
      fields: [tr.time, xc, yc, zc], rows: `${n(tr.points_total)} epochs${tr.step > 1 ? `; every ${tr.step}th plotted` : ""}`,
      node: <Components tr={tr} />, head: ["Maneuver time", "Type"], table: tr.maneuvers.map((m) => [m.t, m.label]),
    },
  ];
}

function OrbitPlot({ tr }: { tr: TrajectorySection }) {
  const W = 640, H = 360, P = 24;
  const xs = tr.points.map((p) => p[0]), ys = tr.points.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY) || 1;
  const sx = (v: number) => P + ((v - minX) / span) * (H - 2 * P) + (W - H) / 2;
  const sy = (v: number) => H - P - ((v - minY) / span) * (H - 2 * P);
  const idx = (t: string) => Math.max(0, tr.times.findIndex((x) => x >= t));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Trajectory projected on ${tr.position[0]} and ${tr.position[1]}`}>
      <polyline points={tr.points.map((p) => `${sx(p[0])},${sy(p[1])}`).join(" ")} fill="none" stroke="var(--analysis-series)" strokeWidth={2} strokeLinejoin="round" />
      {tr.maneuvers.slice(0, 40).map((m, i) => {
        const p = tr.points[idx(m.t)];
        return p ? (
          <g key={i}>
            <circle cx={sx(p[0])} cy={sy(p[1])} r={6} className="fill-ink" stroke="white" strokeWidth={2}><title>{`${m.label} · ${m.t}`}</title></circle>
          </g>
        ) : null;
      })}
      <text x={W - 8} y={H - 8} textAnchor="end" className="fill-ink-faint text-[11px]">{`${tr.position[0]} →, ${tr.position[1]} ↑ (equal scale)`}</text>
    </svg>
  );
}

function Components({ tr }: { tr: TrajectorySection }) {
  const series = tr.series.slice(0, 4);
  const W = 640, H = 90, L = 64;
  return (
    <div className="space-y-2">
      {series.map((s) => {
        const vals = s.points.map((p) => p[1]);
        const mn = Math.min(...vals), mx = Math.max(...vals);
        const y = (v: number) => 8 + (H - 16) * (1 - (mx === mn ? 0.5 : (v - mn) / (mx - mn)));
        const x = (i: number) => L + (i / Math.max(1, s.points.length - 1)) * (W - L - 4);
        const at = (t: string) => Math.max(0, s.points.findIndex((p) => p[0] >= t));
        return (
          <svg key={s.column} viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`${s.column} over time`}>
            <text x={0} y={H / 2 + 4} className="fill-ink-soft text-[12px] font-semibold">{s.column}</text>
            <text x={L - 6} y={14} textAnchor="end" className="fill-ink-faint text-[10px]">{mx.toLocaleString(undefined, { maximumFractionDigits: 3 })}</text>
            <text x={L - 6} y={H - 6} textAnchor="end" className="fill-ink-faint text-[10px]">{mn.toLocaleString(undefined, { maximumFractionDigits: 3 })}</text>
            {tr.maneuvers.slice(0, 40).map((m, i) => (
              <line key={i} x1={x(at(m.t))} x2={x(at(m.t))} y1={4} y2={H - 4} className="stroke-ink-faint" strokeDasharray="3 3" strokeWidth={1}><title>{`${m.label} · ${m.t}`}</title></line>
            ))}
            <polyline points={s.points.map((p, i) => `${x(i)},${y(p[1])}`).join(" ")} fill="none" stroke="var(--analysis-series)" strokeWidth={2} />
          </svg>
        );
      })}
      <p className="flex justify-between pl-16 text-[11px] text-ink-faint"><span>{series[0]?.points[0]?.[0]}</span><span>{series[0]?.points.at(-1)?.[0]}</span></p>
    </div>
  );
}

// ---------------------------------------------------------------- inspection only
export function InspectionResults({ run, sourceUrl }: { run: AnalysisRun; sourceUrl: string }) {
  const rep = run.report!;
  const ins = rep.inspection!;
  return (
    <section className="space-y-5" aria-label="Inspection">
      <div className="glass-strong rounded-3xl p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-white px-2.5 py-1 text-xs font-bold text-ink-soft ring-1 ring-ink/10">Inspection only</span>
          <span className="text-xs text-ink-faint">Generated {new Date(run.finished_at ?? run.created_at).toLocaleString()} · run {run.id}</span>
        </div>
        <p className="mt-3 font-display text-xl font-semibold sm:text-2xl">Detected {ins.detected.toUpperCase()}: {n(ins.file_count)} file{ins.file_count === 1 ? "" : "s"}, {sizeLabel(ins.bytes)}. No analysis was run.</p>
        <p className="mt-2 text-sm text-ink-soft">{ins.next}</p>
        <a className="btn-ghost mt-3" href={sourceUrl} target="_blank" rel="noreferrer">Open source</a>
      </div>
      <div className="grid gap-4 md:grid-cols-[1fr_2fr]">
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Detected types</h3>
          <ul className="mt-2 space-y-1 text-sm">{ins.types.map((t) => <li key={t.type} className="flex justify-between"><span>{t.type}</span><span className="tabular-nums text-ink-soft">{n(t.files)} · {sizeLabel(t.bytes)}</span></li>)}</ul>
        </div>
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Files</h3>
          <div className="mt-2 max-h-80 overflow-auto">
            <table className="w-full text-sm">
              <thead><tr><th className="text-left font-semibold">Name</th><th className="text-left font-semibold">Type</th><th className="text-right font-semibold">Size</th></tr></thead>
              <tbody>{ins.files.map((f) => <tr key={f.name} className="odd:bg-sky-wash/50"><td className="max-w-[360px] truncate px-1 py-1" title={f.name}>{f.name}</td><td className="px-1">{f.type}</td><td className="px-1 text-right tabular-nums">{sizeLabel(f.size)}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      </div>
      <details className="glass rounded-3xl p-4"><summary className="cursor-pointer font-display text-lg font-bold">Run log</summary>
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl bg-white/80 p-3 text-xs leading-5">{run.log}</pre></details>
    </section>
  );
}

export function PairTable({ rep }: { rep: AnalysisReport }) {
  if (!rep.pair) return null;
  return (
    <div className="glass rounded-3xl p-5">
      <h3 className="text-lg font-bold">Simulation settings <span className="text-sm font-semibold text-ink-soft">{rep.pair.file}</span></h3>
      <dl className="mt-2 grid grid-cols-[minmax(10rem,auto)_1fr] gap-x-4 gap-y-1 text-sm">
        {rep.pair.values.map(([k, v]) => <Fragment key={k}><dt className="text-ink-soft">{k}</dt><dd className="tabular-nums">{v === null ? "—" : String(v)}</dd></Fragment>)}
      </dl>
    </div>
  );
}

export function ArchiveDetails({ rep }: { rep: AnalysisReport }) {
  const a = rep.archive;
  if (!a) return null;
  return (
    <div className="text-sm">
      <p className="text-ink-soft">{a.name}: {sizeLabel(a.transferred_bytes)} transferred, {n(a.members_total)} entries, {sizeLabel(a.expanded_bytes)} if fully expanded.
        This run extracted {n(a.extracted_files)} files ({sizeLabel(a.extracted_bytes)}) for the {rep.handler_label?.toLowerCase()} analysis.</p>
      {a.skipped.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-warn-ink">{a.skipped.map((s) => <li key={s.name}>{s.name}: {s.reason}</li>)}</ul>}
    </div>
  );
}
