import { BarChart3, Check as CheckIcon, ExternalLink, FileUp, Loader2, RefreshCw, XCircle } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fmtBytes, useApi } from "../api";
import { fmtDate } from "../components/discover/bits";
import { ErrorBox, Spinner } from "../components/ui";
import { STAGES, failureLabel, rowsLabel, stageIndex } from "../lib/analysisText";
import InsightsView from "../components/insights/InsightsView";
import type { AnalysisColumn, AnalysisReport, AnalysisRun } from "../types";

const num = (v: unknown, digits = 2) =>
  v === null || v === undefined ? "—" : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: digits })) : String(v);

function Tile({ k, v, sub }: { k: string; v: ReactNode; sub?: ReactNode }) {
  return (
    <div className="glass rounded-3xl p-4">
      <p className="text-sm text-ink-soft">{k}</p>
      <p className="mt-1 font-display text-2xl font-extrabold tabular-nums leading-tight">{v}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-faint">{sub}</p>}
    </div>
  );
}

function summary(c: AnalysisColumn) {
  if (c.kind === "numeric") return `${num(c.min)} to ${num(c.max)} · mean ${num(c.mean)} · median ${num(c.median)}`;
  if (c.kind === "datetime") return `${String(c.min).slice(0, 10)} to ${String(c.max).slice(0, 10)}${c.parsed_as ? " (parsed from text)" : ""}`;
  if (c.top?.length) return c.top.slice(0, 3).map(([v, n]) => `${v} (${n.toLocaleString()})`).join(", ");
  return `${num(c.distinct)} distinct values (approx.)`;
}

export function ScopePill({ rep }: { rep: AnalysisReport }) {
  return (
    <span className={`rounded-full px-2.5 py-1 font-bold ${rep.coverage === "full" ? "bg-ok/12 text-ok" : "bg-sun/50 text-warn-ink"}`}
      title={rep.sample_method ?? undefined}>
      {rep.coverage === "full" ? `Full file · ${rep.rows_analyzed.toLocaleString()} rows` : `Sample · ${rep.rows_analyzed.toLocaleString()} real records`}
    </span>
  );
}

function Collapsible({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="glass group rounded-3xl p-5" open={open}>
      <summary className="flex cursor-pointer select-none items-center justify-between font-display text-lg font-bold">
        {title}<span className="text-ink-faint transition-transform group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

export function Stepper({ run }: { run: AnalysisRun }) {
  const failed = run.status === "failed";
  const current = stageIndex(run.stage);
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm" aria-label="Progress">
      {STAGES.map((s, i) => {
        const done = run.status === "succeeded" || i < current;
        const here = i === current && run.status !== "succeeded";
        const cls = here && failed ? "bg-bad/12 text-bad" : here ? "bg-peri/15 text-peri-ink" : done ? "text-ok" : "text-ink-faint";
        return (
          <li key={s.key} className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold ${cls}`} aria-current={here ? "step" : undefined}>
              {here && !failed ? <Loader2 size={13} className="animate-spin" /> : done ? <CheckIcon size={13} /> : here ? <XCircle size={13} /> : null}
              {s.key === "resolving" && run.mode === "sample" ? "Fetching sample" : s.label}
            </span>
            {i < STAGES.length - 1 && <span className="text-ink-faint" aria-hidden>→</span>}
          </li>
        );
      })}
    </ol>
  );
}

function Progress({ run }: { run: AnalysisRun }) {
  const lines = run.log.trim().split("\n").filter(Boolean);
  const p = run.progress;
  return (
    <div className="glass space-y-3 rounded-3xl p-6" role="status" aria-live="polite">
      <p className="font-display text-xl font-bold">{run.mode === "sample" ? "Analyzing a sample of" : "Analyzing"} {run.file_name}</p>
      <Stepper run={run} />
      {run.stage === "downloading" && p && (
        <p className="text-sm tabular-nums text-ink-soft">{fmtBytes(p.bytes ?? 0)}{p.total ? ` of ${fmtBytes(p.total)}` : ""} received</p>
      )}
      <p className="truncate text-xs text-ink-faint" title={lines.at(-1)}>{lines.at(-1) ?? "Queued"}</p>
      <p className="text-xs text-ink-faint">
        {run.mode === "sample" ? "Samples stop after a minute at most." : "Full analyses stop after the configured deadline."} You can leave this page; the run appears in Run history.
      </p>
    </div>
  );
}

function Failure({ run, onRetry, busy }: { run: AnalysisRun; onRetry: (mode?: "sample" | "full") => void; busy: boolean }) {
  const datasetHref = `/datasets/${encodeURIComponent(run.dataset_id)}?analyze=1`;
  const access = run.error_kind === "auth" || run.error_kind === "not_found";
  return (
    <div className="glass space-y-3 rounded-3xl border border-bad/30 p-6" role="alert">
      <p className="flex items-center gap-2 font-display text-xl font-bold text-bad"><XCircle size={20} /> {failureLabel(run.error_kind, run.stage)}</p>
      <Stepper run={run} />
      <p className="text-ink-soft">{run.error ?? "The analysis stopped without an error message."}</p>
      <div className="flex flex-wrap gap-2">
        {run.file_url && !access && (
          <button className="btn-clay bg-peri px-4 py-2 text-sm" disabled={busy} onClick={() => onRetry()}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Retry
          </button>
        )}
        {run.file_url && run.mode === "full" && !access && (
          <button className="btn-ghost" disabled={busy} onClick={() => onRetry("sample")}>Analyze a sample instead</button>
        )}
        <a className="btn-ghost" href={run.source.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open source</a>
        {run.dataset.exists && <Link className="btn-ghost" to={datasetHref}><FileUp size={15} /> Upload downloaded file</Link>}
      </div>
      {access && <p className="text-sm text-ink-soft">Open the source, download the file in your browser (sign in if asked), then upload it.</p>}
    </div>
  );
}

export function SchemaTable({ rep, bare = false }: { rep: AnalysisReport; bare?: boolean }) {
  if (bare) {
    return (
      <div className="overflow-x-auto rounded-2xl bg-white/80">
        <table className="w-full min-w-[720px] text-sm">
          <thead><tr className="text-left">{["Column", "Type", "Missing", "Distinct", "Values"].map((h) => <th key={h} className="border-b border-sky-deep px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>
            {rep.columns.map((c) => (
              <tr key={c.name} className="align-top odd:bg-sky-wash/50">
                <td className="px-3 py-2 font-semibold">{c.name}</td>
                <td className="px-3 py-2 text-ink-soft">{c.type}</td>
                <td className={`px-3 py-2 tabular-nums ${c.missing_pct > 20 ? "font-semibold text-warn" : "text-ink-soft"}`}>{c.missing_pct}%</td>
                <td className="px-3 py-2 tabular-nums text-ink-soft">{num(c.distinct)}</td>
                <td className="px-3 py-2 text-ink-soft">{summary(c)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
          <section className="glass rounded-3xl p-5" aria-labelledby="schema-h">
      <h2 id="schema-h" className="font-display text-xl font-bold">Schema</h2>
      <p className="mt-1 text-sm text-ink-soft">Types as DuckDB read them, measured on {rep.coverage === "full" ? "every row" : "the sampled rows"}.</p>
      <div className="mt-3 overflow-x-auto rounded-2xl bg-white/80">
        <table className="w-full min-w-[720px] text-sm">
          <thead><tr className="text-left">{["Column", "Type", "Missing", "Distinct", "Values"].map((h) => <th key={h} className="border-b border-sky-deep px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>
            {rep.columns.map((c) => (
              <tr key={c.name} className="align-top odd:bg-sky-wash/50">
                <td className="px-3 py-2 font-semibold">{c.name}{c.concepts.map((x) => <span key={x} className="ml-1.5 rounded-full bg-peri/15 px-1.5 py-0.5 text-[10px] font-bold text-peri-ink">{x}</span>)}</td>
                <td className="px-3 py-2 text-ink-soft">{c.type}</td>
                <td className={`px-3 py-2 tabular-nums ${c.missing_pct > 20 ? "font-semibold text-warn" : "text-ink-soft"}`}>{c.missing_pct}%</td>
                <td className="px-3 py-2 tabular-nums text-ink-soft">{num(c.distinct)}</td>
                <td className="px-3 py-2 text-ink-soft">{summary(c)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Load a run, poll while it's active, and retry it (onStarted receives the new run id). */
export function useAnalysisRun(id: string, onStarted: (runId: string) => void) {
  const res = useApi(() => api.analysis(id), [id]);
  const run = res.data;
  const active = run?.status === "queued" || run?.status === "running";
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const retry = async (mode?: "sample" | "full") => {
    setRetrying(true);
    setRetryError(null);
    try {
      onStarted((await api.retryAnalysis(id, mode)).runId);
    } catch (e) {
      setRetryError((e as Error).message);
    } finally {
      setRetrying(false);
    }
  };
  useEffect(() => {
    if (!active) return;
    const t = setInterval(res.reload, 800);
    return () => clearInterval(t);
  }, [active, res.reload]);
  return { res, run, retry, retrying, retryError };
}

/** Progress, failure, summary, insights, schema, rows, source and log for one run. Shared by the run page and the dataset Insights tab. */
export function AnalysisBody({ run, onRetry, retrying, retryError, embedded = false }: {
  run: AnalysisRun; onRetry: (mode?: "sample" | "full") => void; retrying: boolean; retryError: string | null; embedded?: boolean;
}) {
  const rep = run.report;
  const active = run.status === "queued" || run.status === "running";
  return (
    <div className="space-y-5">
      {active && <Progress run={run} />}
      {run.status === "failed" && <Failure run={run} onRetry={onRetry} busy={retrying} />}
      {retryError && <ErrorBox message={retryError} />}

      {rep && (
        <>
          {rep.coverage === "sample" && (
            <p className="flex flex-wrap items-center gap-2 rounded-2xl bg-sun/30 px-4 py-2.5 text-sm text-warn-ink">
              <b>Sample insights.</b> {rowsLabel(rep.rows_analyzed, rep.rows_total, rep.coverage)}: {rep.sample_method}. Missing values,
              duplicates and date ranges describe these rows only.
              {run.file_url && run.mode === "sample" && (
                <button className="font-semibold underline" disabled={retrying} onClick={() => onRetry("full")}>Run full analysis</button>
              )}
            </p>
          )}
          {run.isLatest && !embedded && (
            <p className="flex flex-wrap items-center gap-2 rounded-2xl bg-ok/10 px-4 py-2.5 text-sm">
              <BarChart3 size={15} className="text-ok" /> Saved. This dataset is in
              <Link className="font-semibold text-link underline" to="/packs?ready=analyzed">Curated Packs</Link> as Analyzed.
              <Link className="font-semibold text-link underline" to={`/datasets/${encodeURIComponent(run.dataset_id)}?tab=insights&run=${run.id}`}>Open the dataset page</Link>
            </p>
          )}
          {!!rep.rows_skipped && (
            <p className="rounded-2xl bg-bad/10 px-4 py-2.5 text-sm">
              <b>{rep.rows_skipped.toLocaleString()} rows couldn't be parsed and were skipped</b> ({rep.skip_reasons?.join(", ")}). Check the file's
              quoting or delimiter before relying on these numbers.
            </p>
          )}
          <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Tile k={rep.coverage === "full" ? "Rows" : "Rows analyzed"} v={rep.rows_analyzed.toLocaleString()}
              sub={rep.coverage === "full" ? "All rows" : rep.rows_total != null ? `of ${rep.rows_total.toLocaleString()} in the source` : "Source total unknown"} />
            <Tile k="Columns" v={rep.columns.length} sub={`${rep.columns.filter((c) => c.kind === "numeric").length} numeric, ${rep.columns.filter((c) => c.kind === "datetime").length} date`} />
            <Tile k="Missing cells" v={`${rep.missing_pct}%`} sub={(() => { const g = rep.columns.filter((c) => c.missing > 0).length; return g === 0 ? "No gaps" : `${g} column${g === 1 ? " has" : "s have"} gaps`; })()} />
            <Tile k="Duplicate rows" v={rep.duplicate_rows === null ? "n/a" : rep.duplicate_rows.toLocaleString()} sub={rep.duplicate_pct !== null ? `${rep.duplicate_pct}% of analyzed rows` : "Nested values can't be compared"} />
            <Tile k="Date coverage" v={rep.date_coverage ? `${rep.date_coverage.min.slice(0, 4)} to ${rep.date_coverage.max.slice(0, 4)}` : "None found"}
              sub={rep.date_coverage ? `${fmtDate(rep.date_coverage.min)} to ${fmtDate(rep.date_coverage.max)}, from ${rep.date_coverage.column}` : "No date or timestamp column"} />
          </section>

          <InsightsView report={rep} />
          <SchemaTable rep={rep} />

          <Collapsible title={`First ${rep.preview.length} rows`}>
            <div className="max-h-96 overflow-auto rounded-2xl bg-white/80">
              <table className="w-full text-sm">
                <thead><tr>{rep.columns.map((c) => <th key={c.name} className="sticky top-0 border-b border-sky-deep bg-white px-3 py-2 text-left font-semibold">{c.name}</th>)}</tr></thead>
                <tbody>{rep.preview.map((r, i) => <tr key={i} className="odd:bg-sky-wash/50">{r.map((v, j) => <td key={j} className="max-w-[320px] truncate px-3 py-1.5 text-ink-soft">{v === null ? "—" : String(v)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </Collapsible>
        </>
      )}

      <Collapsible title="Source and file">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div><dt className="text-ink-faint">Source</dt><dd><a className="break-all text-link underline" href={run.source.canonicalUrl} target="_blank" rel="noreferrer">{run.source.canonicalUrl}</a></dd></div>
          <div><dt className="text-ink-faint">License</dt><dd>{run.source.licenseUrl ? <a className="underline" href={run.source.licenseUrl} target="_blank" rel="noreferrer">{run.source.license}</a> : run.source.license ?? "Unknown"}</dd></div>
          <div><dt className="text-ink-faint">Source version (last updated)</dt><dd>{fmtDate(run.source.version)}</dd></div>
          {run.source.doi && <div><dt className="text-ink-faint">DOI</dt><dd>{run.source.doi}</dd></div>}
          <div><dt className="text-ink-faint">File analyzed</dt><dd className="break-all">{run.file_url ? <a className="underline" href={run.file_url} target="_blank" rel="noreferrer">{run.file_name}</a> : `${run.file_name} (uploaded)`}</dd></div>
          <div><dt className="text-ink-faint">SHA-256</dt><dd className="break-all font-mono text-xs">{run.file_sha256 ?? "—"}</dd></div>
        </dl>
      </Collapsible>
      <Collapsible title="Log">
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl bg-white/80 p-3 text-xs leading-5">{run.log || "No log yet."}</pre>
      </Collapsible>
    </div>
  );
}

/** /analyses/:id (Run history links) opens the dataset's Run view with that exact run selected. */
export default function AnalysisPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const res = useApi(() => api.analysis(id), [id]);
  useEffect(() => {
    if (res.data) nav(`/datasets/${encodeURIComponent(res.data.dataset_id)}/run?run=${id}`, { replace: true });
  }, [res.data, id, nav]);
  if (res.error) return <ErrorBox message={res.error} action={<Link className="btn-ghost" to="/runs">Run history</Link>} />;
  return <Spinner label="Opening run" />;
}
