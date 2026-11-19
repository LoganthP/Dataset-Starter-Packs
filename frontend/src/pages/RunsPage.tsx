import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { failureLabel } from "../lib/analysisText";
import { api, timeAgo, useApi } from "../api";
import ResultsView from "../components/ResultsView";
import { ErrorBox, Spinner, StatusPill } from "../components/ui";
import { useRunWatcher } from "../components/useRunWatcher";
import type { RunStatus } from "../types";

function AnalysesSection() {
  const list = useApi(() => api.analyses());
  useEffect(() => {
    const busy = list.data?.some((r) => r.status === "running" || r.status === "queued");
    if (!busy) return;
    const t = setInterval(list.reload, 1200);
    return () => clearInterval(t);
  }, [list.data, list.reload]);
  return (
    <section aria-labelledby="an-h" className="space-y-3">
      <h2 id="an-h" className="font-display text-2xl font-bold">Dataset analyses</h2>
      {list.error && <ErrorBox message={list.error} />}
      {list.data && !list.data.length && (
        <p className="glass rounded-3xl p-5 text-ink-soft">No analyses yet. On Discover, choose <b>Analyze dataset</b> on a result, or upload a file from its Inspect panel.</p>
      )}
      {!!list.data?.length && (
        <div className="glass overflow-x-auto rounded-3xl p-2">
          <table className="w-full min-w-[720px] text-sm">
            <thead><tr className="text-left text-ink-soft">{["Status", "Dataset", "File", "Rows", "Started"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.id} className="border-t border-white/80 hover:bg-white/60">
                  <td className="px-3 py-2.5">
                    <StatusPill status={r.status} />
                    {r.status === "failed" && <span className="ml-1.5 text-xs font-semibold text-bad">{failureLabel(r.error_kind, r.stage)}</span>}
                    {r.mode === "sample" && r.status !== "failed" && <span className="ml-1.5 text-xs text-ink-faint">sample</span>}
                  </td>
                  <td className="px-3 py-2.5 font-semibold"><Link className="underline-offset-2 hover:underline" to={`/analyses/${r.id}`}>{r.dataset_title}</Link></td>
                  <td className="max-w-[260px] truncate px-3 py-2.5 text-ink-soft" title={r.file_name}>{r.file_name}</td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-soft">{r.status === "succeeded" ? (r.coverage === "full" ? (r.rows ?? 0).toLocaleString() : `sample of ${r.rows != null ? r.rows.toLocaleString() : "?"}`)
                    : r.error ? <span className="text-bad" title={r.error}>{r.error.slice(0, 70)}{r.error.length > 70 ? "…" : ""}</span> : "—"}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-faint">{timeAgo(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function RunsPage() {
  const runs = useApi(() => api.runs());
  const [filter, setFilter] = useState<RunStatus | "all">("all");

  useEffect(() => {
    const busy = runs.data?.some((r) => r.status === "running" || r.status === "queued");
    if (!busy) return;
    const t = setInterval(runs.reload, 1500);
    return () => clearInterval(t);
  }, [runs.data, runs.reload]);

  const shown = (runs.data ?? []).filter((r) => filter === "all" || r.status === filter);
  const remove = async (id: string) => {
    await api.deleteRun(id);
    void runs.reload();
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight">Run history</h1>
          <p className="mt-1 text-ink-soft">Analyses and starter-pack runs on this machine, newest first.</p>
        </div>
      </div>
      <AnalysesSection />
      <div className="flex flex-wrap items-end gap-4 pt-4">
        <h2 className="font-display text-2xl font-bold">Starter pack runs</h2>
        <select className="field ml-auto w-auto" value={filter} onChange={(e) => setFilter(e.target.value as RunStatus | "all")} aria-label="Filter by status">
          {["all", "succeeded", "failed", "running", "queued", "canceled"].map((s) => <option key={s} value={s}>{s === "all" ? "All statuses" : s}</option>)}
        </select>
      </div>
      {runs.loading && <Spinner />}
      {runs.error && <ErrorBox message={runs.error} />}
      {runs.data && !shown.length && (
        <p className="glass rounded-3xl p-5 text-ink-soft">No pack runs to show. <Link to="/packs" className="font-semibold text-link underline">Open a starter pack</Link> and run its sample.</p>
      )}
      {shown.length > 0 && (
        <div className="glass overflow-x-auto rounded-3xl p-2">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="text-left text-ink-soft">
                {["Status", "Pack", "Data", "Result", "Started", "Time", ""].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} className="border-t border-white/80 hover:bg-white/60">
                  <td className="px-3 py-2.5"><StatusPill status={r.status} /></td>
                  <td className="px-3 py-2.5 font-semibold"><Link className="underline-offset-2 hover:underline" to={`/runs/${r.id}`}>{r.slug}</Link></td>
                  <td className="px-3 py-2.5">{r.mode === "real" ? "Real" : "Sample"}</td>
                  <td className="max-w-[420px] truncate px-3 py-2.5 text-ink-soft" title={r.headline ?? r.error ?? ""}>{r.headline ?? r.error?.split("\n")[0] ?? ""}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-faint">{timeAgo(r.created_at)}</td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-faint">{r.duration_s != null ? `${r.duration_s.toFixed(1)} s` : ""}</td>
                  <td className="px-3 py-2.5 text-right">
                    {!["running", "queued"].includes(r.status) && (
                      <button className="rounded-lg p-1.5 text-ink-faint hover:bg-white hover:text-bad" onClick={() => remove(r.id)} aria-label={`Delete run ${r.id}`}>
                        <Trash2 size={16} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function RunDetailPage() {
  const { id = "" } = useParams();
  const { run, log, error } = useRunWatcher(id);
  if (error && !run) return <ErrorBox message={error} action={<Link className="btn-ghost" to="/runs">Back to run history</Link>} />;
  if (!run) return <Spinner label="Loading run" />;
  return (
    <div className="space-y-5">
      <Link to="/runs" className="text-sm font-semibold text-ink-soft hover:text-ink">Run history</Link>
      <div className="glass-strong flex flex-wrap items-center gap-3 rounded-3xl p-5">
        <StatusPill status={run.status} />
        <h1 className="text-2xl font-extrabold">
          <Link className="hover:underline" to={`/packs/${run.slug}?run=${run.id}`}>{run.slug}</Link>
        </h1>
        <span className="text-sm text-ink-soft">
          {run.mode === "real" ? "Real data" : "Sample"} · {new Date(run.created_at).toLocaleString()}
          {Object.keys(run.params).length > 0 && ` · ${Object.entries(run.params).map(([k, v]) => `${k}=${v}`).join(", ")}`}
        </span>
      </div>
      {run.status === "failed" && run.error && <ErrorBox message={run.error} />}
      {run.results && <ResultsView runId={run.id} results={run.results} />}
      <details className="glass rounded-3xl p-4" open={run.status !== "succeeded"}>
        <summary className="cursor-pointer font-display text-lg font-bold">Run log</summary>
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-2xl bg-sky-wash p-4 font-[ui-monospace,Menlo,Consolas,monospace] text-[12.5px] leading-6">{log}</pre>
      </details>
    </div>
  );
}
