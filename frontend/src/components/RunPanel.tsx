import { motion } from "framer-motion";
import { Database, ExternalLink, FlaskConical, Loader2, Play, Square, Trash2, Upload } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, fmtBytes, timeAgo, useDiscoverMeta } from "../api";
import type { DataStatus, Mode, PackDetail } from "../types";
import { QueueNotice } from "./QueueNotice";
import ResultsView from "./ResultsView";
import { ErrorBox, StatusPill } from "./ui";
import { useRunWatcher } from "./useRunWatcher";

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const opts: { value: Mode; label: string; icon: ReactNode }[] = [
    { value: "sample", label: "Sample", icon: <FlaskConical size={16} /> },
    { value: "real", label: "Real data", icon: <Database size={16} /> },
  ];
  return (
    <div className="neu-track relative grid grid-cols-2" role="radiogroup" aria-label="Data mode">
      {opts.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={mode === o.value}
          onClick={() => onChange(o.value)}
          className="relative z-10 flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold"
        >
          {mode === o.value && (
            <motion.span
              layoutId="mode-pill"
              className="absolute inset-0 -z-10 rounded-xl bg-white shadow-neu"
              transition={{ type: "spring", stiffness: 380, damping: 30 }}
            />
          )}
          <span className={mode === o.value ? "text-ink" : "text-ink-soft"}>{o.icon}</span>
          <span className={mode === o.value ? "text-ink" : "text-ink-soft"}>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

function RealDataPanel({ pack, status, onChange }: { pack: PackDetail; status: DataStatus; onChange: (s: DataStatus) => void }) {
  const src = pack.source;
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.upload(pack.slug, file);
      onChange(res.data_status);
      setMsg(res.ok ? { ok: true, text: "Imported. You can run on real data now." } : { ok: false, text: `Still missing: ${res.missing.join(", ")}` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const clear = async () => onChange(await api.clearData(pack.slug));

  return (
    <div className="space-y-3 rounded-2xl bg-white/70 p-4 text-sm">
      {status.has_real_data ? (
        <>
          <p className="font-semibold text-ok">Real data is cached on this machine.</p>
          <ul className="space-y-1 text-ink-soft">
            {status.cached_files.map((f) => (
              <li key={f.name} className="flex justify-between gap-2">
                <span className="truncate">{f.name}</span>
                <span className="shrink-0 tabular-nums">{fmtBytes(f.bytes)} · {timeAgo(f.modified)}</span>
              </li>
            ))}
          </ul>
          <button className="btn-ghost" onClick={clear}>
            <Trash2 size={14} /> Delete cached data
          </button>
        </>
      ) : src.access_method === "kaggle" ? (
        <>
          <p className="font-semibold">This dataset needs a free Kaggle sign-in, so it can't download automatically.</p>
          <ol className="list-decimal space-y-1 pl-5 text-ink-soft">
            {(src.manual_steps ?? []).map((s) => <li key={s}>{s}</li>)}
          </ol>
          <div className="flex flex-wrap gap-2">
            <a className="btn-ghost" href={src.dataset_page} target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> Open on Kaggle
            </a>
            <input ref={fileRef} type="file" accept=".zip,.csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            <button className="btn-ghost" onClick={() => fileRef.current?.click()} disabled={busy}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} Upload archive.zip
            </button>
          </div>
        </>
      ) : (
        <p className="text-ink-soft">
          {src.access_method === "api" ? "The pack queries " : "The pack downloads "}
          <a className="font-semibold text-link underline" href={src.dataset_page} target="_blank" rel="noreferrer">{src.name}</a>{" "}
          the first time you run it, caches it in <code>data/raw/</code>, and records the URL and retrieval date. Your machine needs internet access.
        </p>
      )}
      {msg && <p className={msg.ok ? "font-semibold text-ok" : "font-semibold text-bad"}>{msg.text}</p>}
    </div>
  );
}

export default function RunPanel({ pack, initialRunId, autoStart, onRunChange }: {
  pack: PackDetail;
  initialRunId: string | null;
  autoStart: boolean;
  onRunChange: (id: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("sample");
  const [dataStatus, setDataStatus] = useState(pack.data_status);
  const defaults = useMemo(
    () => Object.fromEntries(pack.parameters.map((p) => [p.name, p.default === undefined ? "" : String(p.default)])),
    [pack.parameters],
  );
  const [params, setParams] = useState<Record<string, string>>(defaults);
  const [runId, setRunId] = useState<string | null>(initialRunId);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const { run, log, error, progress, stepLabel } = useRunWatcher(runId);
  const logRef = useRef<HTMLPreElement>(null);
  const started = useRef(false);

  const active = run?.status === "queued" || run?.status === "running" || starting;
  const visibleParams = pack.parameters.filter((p) => !p.modes || p.modes.includes(mode));

  const start = async (m: Mode = mode) => {
    setStarting(true);
    setStartError(null);
    try {
      const allowed = new Set(pack.parameters.filter((p) => !p.modes || p.modes.includes(m)).map((p) => p.name));
      const sent = Object.fromEntries(Object.entries(params).filter(([k, v]) => allowed.has(k) && v !== ""));
      const r = await api.startRun(pack.slug, m, sent);
      setRunId(r.id);
      onRunChange(r.id);
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  useEffect(() => {
    if (autoStart && !started.current) {
      started.current = true;
      void start("sample");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);

  useEffect(() => {
    if (run?.status === "succeeded" && run.mode === "real") api.dataStatus(pack.slug).then(setDataStatus).catch(() => {});
  }, [run?.status, run?.mode, pack.slug]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log]);

  const realBlocked = mode === "real" && pack.source.access_method === "kaggle" && !dataStatus.has_real_data;
  const meta = useDiscoverMeta();
  const runsOff = meta?.capabilities?.packRuns === false;

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_1fr]">
        <div className="glass space-y-4 rounded-3xl p-5">
          <ModeToggle mode={mode} onChange={setMode} />
          <p className="text-sm text-ink-soft">
            {mode === "sample"
              ? `Runs on a small invented dataset with the real schema. No download, about ${pack.expected_runtime.sample.replace("~", "")}.`
              : `Runs on ${pack.source.name}. Expect ${pack.expected_runtime.real}.`}
          </p>
          {mode === "real" && <RealDataPanel pack={pack} status={dataStatus} onChange={setDataStatus} />}

          {visibleParams.length > 0 && (
            <fieldset className="space-y-3">
              <legend className="mb-1 font-display text-base font-bold">Settings</legend>
              {visibleParams.map((p) => (
                <label key={p.name} className="block">
                  <span className="text-sm font-semibold">{p.label}</span>
                  {p.type === "select" ? (
                    <select className="field mt-1 capitalize" value={params[p.name]} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
                      {p.options!.map((o) => <option key={o} value={o}>{o.replaceAll("_", " ")}</option>)}
                    </select>
                  ) : (
                    <input
                      className="field mt-1"
                      type={p.type === "number" ? "number" : p.type === "date" ? "date" : "text"}
                      min={p.min}
                      max={p.max}
                      step={p.step}
                      value={params[p.name]}
                      onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}
                    />
                  )}
                  {p.help && <span className="mt-1 block text-xs text-ink-faint">{p.help}</span>}
                </label>
              ))}
            </fieldset>
          )}

          <div className="flex gap-2">
            <button
              className="btn-clay flex-1 text-base"
              style={{ background: pack.accent }}
              disabled={active || realBlocked || runsOff}
              onClick={() => start()}
            >
              {active ? <Loader2 size={18} className="animate-spin" /> : <Play size={18} fill="currentColor" />}
              {active ? "Running" : mode === "sample" ? "Run on sample" : "Run on real data"}
            </button>
            {active && run && (
              <button className="btn-ghost" onClick={() => api.cancelRun(run.id)}>
                <Square size={14} /> Stop
              </button>
            )}
          </div>
          {realBlocked && <p className="text-xs text-ink-soft">Upload the Kaggle archive first.</p>}
          {runsOff && <p className="text-xs text-ink-soft">Runs are off on this deployment: it has no shared database for a worker to read. Set DATABASE_URL and start the worker, or download the starter and run it locally.</p>}
          {startError && <ErrorBox message={startError} />}
        </div>

        <div className="glass flex min-h-[340px] flex-col rounded-3xl p-5">
          {!runId ? (
            <div className="m-auto max-w-sm text-center">
              <p className="font-display text-2xl font-bold">Nothing has run yet</p>
              <p className="mt-2 text-sm text-ink-soft">
                Start with the sample. It takes seconds and shows exactly what the real run will produce.
              </p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                {run && <StatusPill status={run.status} />}
                <span className="text-sm text-ink-soft">
                  {run?.mode === "real" ? "Real data" : "Sample"} · run {runId}
                  {run?.duration_s != null && ` · ${run.duration_s.toFixed(1)} s`}
                </span>
              </div>
              <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/80 shadow-neu-in" aria-hidden>
                <motion.div
                  className="h-full rounded-full"
                  style={{ background: run?.status === "failed" ? "#E5484D" : pack.accent }}
                  animate={{ width: `${Math.max(progress, active ? 0.06 : 0) * 100}%` }}
                  transition={{ type: "spring", stiffness: 120, damping: 20 }}
                />
              </div>
              {run?.status === "queued" && <QueueNotice queue={run.queue} />}
              {stepLabel && active && run?.status !== "queued" && <p className="mt-2 text-sm font-semibold">{stepLabel}</p>}
              <pre
                ref={logRef}
                className="mt-3 max-h-72 flex-1 overflow-auto whitespace-pre-wrap rounded-2xl border border-white bg-sky-wash p-4 font-[ui-monospace,Menlo,Consolas,monospace] text-[12.5px] leading-6 text-ink-soft"
                aria-live="polite"
                aria-label="Run log"
              >
                {log || "Waiting for output"}
              </pre>
              {run?.status === "failed" && run.error && (
                <div className="mt-3">
                  <ErrorBox message={run.error} />
                </div>
              )}
              {error && <div className="mt-3"><ErrorBox message={error} /></div>}
            </>
          )}
        </div>
      </div>

      {run?.status === "succeeded" && run.results && <ResultsView runId={run.id} results={run.results} />}
    </div>
  );
}
