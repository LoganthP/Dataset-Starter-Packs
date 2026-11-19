/**
 * Run view for analyzed datasets, modeled on a starter pack's Run tab (Bengaluru Weather Explorer):
 * settings on the left, progress and log on the right, then results (summary tiles, checks, chart grid, details).
 * Opening it shows the latest successful report; from there you can change settings and run again.
 */
import { motion } from "framer-motion";
import { ArrowLeft, Check as CheckIcon, Database, ExternalLink, FileUp, FlaskConical, Loader2, Play, Plus, Square } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type ApiError, sizeLabel, timeAgo, useApi, useDiscoverMeta } from "../api";
import AnalysisResults from "../components/analysis/AnalysisResults";
import { FilePicker, Inspector, KaggleBanner, NextActions, PairNote, phaseShare, phaseText } from "../components/analysis/RunControls";
import { useAccount } from "../lib/account";
import { ErrorBox, Spinner, StatusPill } from "../components/ui";
import { RETRYABLE, STAGES, failureLabel, stageIndex } from "../lib/analysisText";
import { useShortlist } from "../lib/shortlist";
import type { AnalysisRun, DatasetDetail, FileList, LimitDetail, RunParams } from "../types";
import { SchemaTable } from "./AnalysisPage";

type Mode = "sample" | "full";
const ACCENT = "#7C83FD";
const TABS = ["Run", "Schema", "History"] as const;
type Tab = (typeof TABS)[number];

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const opts: { value: Mode; label: string; icon: ReactNode }[] = [
    { value: "sample", label: "Sample", icon: <FlaskConical size={16} /> },
    { value: "full", label: "Full analysis", icon: <Database size={16} /> },
  ];
  return (
    <div className="neu-track relative grid grid-cols-2" role="radiogroup" aria-label="Analysis mode">
      {opts.map((o) => (
        <button key={o.value} role="radio" aria-checked={mode === o.value} onClick={() => onChange(o.value)}
          className="relative z-10 flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold">
          {mode === o.value && <motion.span layoutId="an-mode-pill" className="absolute inset-0 -z-10 rounded-xl bg-white shadow-neu" transition={{ type: "spring", stiffness: 380, damping: 30 }} />}
          <span className={mode === o.value ? "text-ink" : "text-ink-soft"}>{o.icon}</span>
          <span className={mode === o.value ? "text-ink" : "text-ink-soft"}>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

function useRun(runId: string | null) {
  // lite: a saved report without its raw rows (those load when "First rows" opens)
  const res = useApi(() => (runId ? api.analysis(runId, true) : Promise.resolve(null as AnalysisRun | null)), [runId]);
  const active = res.data?.status === "queued" || res.data?.status === "running";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(res.reload, 700);
    return () => clearInterval(t);
  }, [active, res.reload]);
  return res;
}

function Elapsed({ run }: { run: AnalysisRun }) {
  const [, tick] = useState(0);
  const active = run.status === "queued" || run.status === "running";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [active]);
  const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  return <>{((end - new Date(run.created_at).getTime()) / 1000).toFixed(1)} s</>;
}

export default function DatasetRunPage() {
  const { id = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const shortlist = useShortlist();
  const meta = useDiscoverMeta();
  const ds = useApi(() => api.dataset(id, ""), [id]);
  const runs = useApi(() => api.analyses(id), [id]);
  const [files, setFiles] = useState<FileList | null>(null);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Run");
  const [mode, setMode] = useState<Mode>("sample");
  const [source, setSource] = useState<string>("");
  const [dateField, setDateField] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<{ message: string; kind?: string; detail?: LimitDetail | null } | null>(null);
  const [members, setMembers] = useState<string[]>([]);
  const [sheet, setSheet] = useState("");
  const account = useAccount();
  const upload = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLPreElement>(null);
  const autoStarted = useRef(false);

  const d: DatasetDetail | null = ds.data;
  const latestGood = d?.analysis?.runId ?? null;
  const shownId = sp.get("run") ?? latestGood ?? runs.data?.[0]?.id ?? null;
  const shown = useRun(shownId);
  const run = shown.data;
  const fallback = useRun(run && run.status !== "succeeded" && latestGood && latestGood !== run.id ? latestGood : null).data;
  const active = run?.status === "queued" || run?.status === "running";

  useEffect(() => {
    api.files(id).then((f) => {
      setFiles(f);
      const params = run?.params ?? {};
      const kept = sp.get("file") && f.files.find((x) => x.url === sp.get("file"));  // kept across Connect Kaggle / consent round trips
      const prev = run?.file_url && f.files.find((x) => x.url === run.file_url && x.supported);
      const first = f.files.find((x) => x.supported);
      setSource(sp.get("source") === "upload" ? "upload" : (kept || prev || first)?.url ?? "upload");
      if (params.dateField) { setDateField(params.dateField); setDateFrom(params.dateFrom ?? ""); setDateTo(params.dateTo ?? ""); }
    }).catch((e: Error) => { setFilesError(e.message); setSource("upload"); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, account.kaggle?.connected]);

  useEffect(() => { // keep the log scrolled to the newest line while running
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [run?.log]);

  useEffect(() => { // when a run settles, refresh the header badges and history
    if (run && !active) { void runs.reload(); void ds.reload(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  const file = files?.files.find((f) => f.url === source);
  const dateFields = file?.date_fields ?? [];
  useEffect(() => { if (dateFields.length && !dateField) setDateField(dateFields[0]); }, [dateFields, dateField]);

  const blocked = files && !files.files.some((f) => f.supported);
  useEffect(() => setMembers([]), [source]);
  // A ZIP the Quick sample can't download: say so up front and change the action, rather than failing first.
  const bigArchive = !!file && file.format === "zip" && !!file.bytes && !!files?.quickSampleBytes && file.bytes > files.quickSampleBytes;
  const start = async (m: Mode = mode, extra: RunParams = {}) => {
    if (source === "upload") { upload.current?.click(); return; }
    if (!file) return;
    setStarting(true);
    setStartError(null);
    try {
      const params: RunParams = { members: members.length ? members : undefined, pairUrl: file.pair_url, sheet: sheet || undefined, ...extra };
      if (dateFields.length && (dateFrom || dateTo)) Object.assign(params, { dateField, dateFrom: dateFrom || undefined, dateTo: dateTo || undefined });
      if (m === "sample" && bigArchive && extra.prepare === undefined) params.prepare = true;
      const { runId } = await api.analyze(id, file.url, m, params);
      setSp({ run: runId, file: file.url }, { replace: false });
    } catch (e) {
      setStartError({ message: (e as Error).message, kind: (e as ApiError).kind, detail: (e as ApiError).detail });
    } finally {
      setStarting(false);
    }
  };
  const act = async (action: string, failed?: AnalysisRun) => {
    if (action === "upload") return upload.current?.click();
    if (action === "select_member") return document.getElementById("inspector")?.scrollIntoView({ behavior: "smooth" });
    if (action === "date_range") return document.getElementById("date-range")?.scrollIntoView({ behavior: "smooth" });
    if (failed?.file_url && action !== "retry") {  // change the workflow of the failed run, keeping its file and settings
      const extra = action === "prepare_archive_sample" ? { prepare: true } : {};
      const mode2 = action === "full" ? "full" : "sample";
      setMode(mode2);
      try {
        setSp({ run: (await api.retryAnalysis(failed.id, mode2, extra)).runId, file: failed.file_url });
      } catch (e) {
        setStartError({ message: (e as Error).message, kind: (e as ApiError).kind, detail: (e as ApiError).detail });
      }
      return;
    }
    if (action === "prepare_archive_sample") { setMode("sample"); return start("sample", { prepare: true }); }
    if (action === "full") { setMode("full"); return start("full"); }
    if (action === "run_sample") { setMode("sample"); return start("sample"); }
    if (action === "retry") return failed?.file_url ? setSp({ run: (await api.retryAnalysis(failed.id)).runId, file: failed.file_url }) : start();
  };

  useEffect(() => { // "Run sample" from a Discover card: start once the file list says a supported file exists
    if (sp.get("start") !== "sample" || autoStarted.current || !files || !d) return;
    autoStarted.current = true;
    const next = new URLSearchParams(sp);
    next.delete("start");
    setSp(next, { replace: true });
    if (file && !active) void start("sample");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, d]);

  const stage = run ? stageIndex(run.stage) : 0;
  // Within a step the bar moves by its own counter: rows or bytes fetched, files extracted, images analyzed.
  const progress = run?.status === "succeeded" ? 1 : run ? Math.min(0.95, (stage + (active ? phaseShare(run) : 0.5)) / STAGES.length) : 0;
  const phase = run ? phaseText(run) : null;
  const unsupported = files?.unsupportedFormats?.length ? files.unsupportedFormats.join(", ") : null;
  const sameAsShown = run && run.file_url === file?.url && (run.mode ?? "sample") === mode;
  const runLabel = starting ? "Checking the file" : active ? "Running" : source === "upload" ? "Upload and run"
    : files?.connect === "kaggle" ? (mode === "sample" ? (bigArchive ? "Fetch archive and run sample" : "Fetch and run sample") : "Fetch and analyze")
    : mode === "sample" && bigArchive ? "Prepare archive and run sample" : sameAsShown ? "Run again" : mode === "sample" ? "Run sample" : "Run full analysis";

  const heroRows = useMemo(() => {
    const a = d?.analysis;
    if (!a) return null;
    const unit = a.kind === "images" ? "images" : a.kind === "sinex" ? "station solutions" : "rows";
    return a.kind === "inspection" ? "Inspection only" : `${a.scope ?? (a.coverage === "full" ? "Full dataset" : "Sample")} · ${a.rowsAnalyzed.toLocaleString()} ${unit}`;
  }, [d?.analysis]);

  if (ds.loading && !d) return <div className="glass rounded-3xl p-6"><Spinner label="Loading dataset" /></div>;
  if (ds.error || !d) return <ErrorBox message={ds.error ?? "Dataset not found"} action={<Link className="btn-ghost" to="/packs">Curated packs</Link>} />;
  const inList = shortlist.has(d.id);
  const failKind = run?.status === "failed" ? run.error_kind ?? "error" : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <Link to="/packs" className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-soft hover:text-ink"><ArrowLeft size={16} /> Curated packs</Link>
        <Link to={`/datasets/${encodeURIComponent(d.id)}`} className="text-sm font-semibold text-link underline underline-offset-2">Dataset details and verification</Link>
      </div>

      <motion.header initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ type: "spring", stiffness: 200, damping: 22 }}
        className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="glass-strong relative overflow-hidden rounded-4xl p-6 sm:p-8">
          <span className="absolute inset-y-0 left-0 w-2" style={{ background: ACCENT }} aria-hidden />
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-ink px-2.5 py-0.5 text-xs font-bold text-on-accent">{d.provider}</span>
            {d.analysis && <span className="rounded-full bg-ok/12 px-2.5 py-0.5 text-xs font-bold text-ok">Analyzed</span>}
            {heroRows && <span className="rounded-full bg-sun/50 px-2.5 py-0.5 text-xs font-bold text-warn-ink">{heroRows}</span>}
            {d.formats.values.slice(0, 3).map((f) => <span key={f} className="chip uppercase">{f}</span>)}
          </div>
          <h1 className="mt-4 text-[clamp(2rem,4.4vw,3.2rem)] font-extrabold leading-[1] tracking-[-0.025em]">{d.title}</h1>
          <p className="mt-4 max-w-[64ch] text-lg leading-snug text-ink-soft">{d.description}</p>
          <div className="mt-6 flex flex-wrap gap-2">
            <a className="btn-ghost" href={d.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open source</a>
            <button className="btn-ghost" onClick={() => shortlist.toggle(d.id, d.title)} disabled={!inList && shortlist.full} aria-pressed={inList}>
              {inList ? <CheckIcon size={15} /> : <Plus size={15} />} {inList ? "In comparison" : "Compare"}
            </button>
          </div>
        </div>
        <aside className="flex flex-col rounded-4xl p-6 shadow-clay" style={{ background: "var(--sun-panel)" }}>
          <h2 className="text-sm font-bold text-warn-ink">What a sample can tell you</h2>
          <p className="mt-2 font-display text-2xl font-extrabold leading-tight text-warn-ink">Real records, not the whole dataset</p>
          <p className="mt-3 text-[15px] leading-relaxed text-warn-ink">
            A sample reads the first 1,000 rows, or every k-th image of an image archive, in about a minute. Use it to check fields, labels and formats; run the full analysis for totals.
          </p>
          <p className="mt-auto pt-4 text-sm text-warn-ink">The file type is detected from its content. Tables, images, SINEX and orbit files each get their own report.</p>
        </aside>
      </motion.header>

      <div className="glass-strong sticky top-[76px] z-20 flex gap-1 overflow-x-auto rounded-2xl p-1.5" role="tablist" aria-label="Dataset sections">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className="relative whitespace-nowrap rounded-xl px-4 py-2 text-sm font-semibold">
            {tab === t && <motion.span layoutId="an-tab-pill" className="absolute inset-0 -z-0 rounded-xl bg-white shadow-neu" transition={{ type: "spring", stiffness: 380, damping: 32 }} />}
            <span className={`relative ${tab === t ? "text-ink" : "text-ink-soft"}`}>{t}</span>
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={tab}>
        <div hidden={tab !== "Run"} className="space-y-6">
          <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
            <div className="glass space-y-4 rounded-3xl p-5">
              <ModeToggle mode={mode} onChange={setMode} />
              <p className="text-sm text-ink-soft">
                {mode === "sample"
                  ? (bigArchive ? `This archive is ${sizeLabel(file?.bytes)}, more than a Quick sample downloads (${sizeLabel(files?.quickSampleBytes)}). The sample downloads it once, then reads only the files it needs.`
                    : "Reads the first 1,000 real records (or a spread of images). Finishes within a minute.")
                  : `Reads everything. Portal datasets are fetched in pages; files and archives up to ${sizeLabel(meta?.capabilities?.maxTransferBytes ?? 2e9)}, expanding to at most ${sizeLabel(meta?.capabilities?.maxExtractBytes ?? 6e9)}.`}
              </p>
              <div>
                <h3 className="font-display text-lg font-bold">Settings</h3>
                <label className="mt-2 block text-sm font-semibold" htmlFor="src">Data file</label>
                {!files && !filesError ? (
                  <p className="mt-1 flex items-center gap-2 text-sm text-ink-soft"><Loader2 size={14} className="animate-spin" /> Asking {d.provider} for its files…</p>
                ) : files ? (
                  <div className="mt-1"><FilePicker id={id} files={files} value={source} onChange={setSource} onMore={setFiles} /></div>
                ) : (
                  <select id="src" className="field mt-1" value="upload" onChange={() => {}}><option value="upload">Upload a file I downloaded…</option></select>
                )}
                <div className="mt-2 space-y-2">
                  <KaggleBanner files={files} user={account.user} kaggle={files?.kaggle ?? account.kaggle} />
                  <PairNote file={file} />
                  <div id="inspector"><Inspector id={id} file={file} chosen={members} onChoose={setMembers} /></div>
                </div>
                {blocked && files?.connect !== "kaggle" && (
                  <p className="mt-2 rounded-2xl bg-sun/30 px-3 py-2 text-xs text-warn-ink">
                    {unsupported ? `${d.provider} serves this dataset as ${unsupported}, which can't be analyzed here yet.`
                      : files?.signInRequired ? `${d.provider} needs a sign-in to download.` : `${d.provider} didn't list a CSV, Parquet, JSON or Excel file.`}{" "}
                    Open the source; if it offers a CSV or Parquet export, download it and upload it here.
                  </p>
                )}
              </div>
              {(() => { // worksheets the last report of this file found
                const rep = [run, fallback].find((r) => r?.report?.scope?.sheets && r.file_url === file?.url)?.report;
                const sheets = rep?.scope?.sheets ?? [];
                return sheets.length > 1 && source !== "upload" ? (
                  <label className="block text-sm font-semibold">Worksheet
                    <select className="field mt-1" value={sheet || rep?.scope?.sheet || ""} onChange={(e) => setSheet(e.target.value)}>
                      {sheets.map((sh) => <option key={sh}>{sh}</option>)}
                    </select>
                    <span className="mt-1 block text-xs font-normal text-ink-faint">in {rep?.scope?.file}. A report covers one worksheet.</span>
                  </label>
                ) : null;
              })()}
              {dateFields.length > 0 && source !== "upload" && (
                <fieldset className="space-y-2" id="date-range">
                  <legend className="text-sm font-semibold">Date range <span className="font-normal text-ink-faint">(optional, filtered by {d.provider})</span></legend>
                  {dateFields.length > 1 && (
                    <select className="field" value={dateField} onChange={(e) => setDateField(e.target.value)} aria-label="Date field">
                      {dateFields.map((f) => <option key={f}>{f}</option>)}
                    </select>
                  )}
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-ink-soft">From<input type="date" className="field mt-1" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></label>
                    <label className="text-xs text-ink-soft">To<input type="date" className="field mt-1" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label>
                  </div>
                </fieldset>
              )}
              <input ref={upload} type="file" className="hidden" aria-label="Upload a data file (any type; detected from its content)"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  setStarting(true);
                  setStartError(null);
                  try {
                    setSp({ run: (await api.analyzeUpload(id, f, meta?.capabilities)).runId });
                  } catch (err) {
                    setStartError({ message: (err as Error).message, kind: (err as ApiError).kind, detail: (err as ApiError).detail });
                  } finally {
                    setStarting(false);
                  }
                }} />
              <div className="flex gap-2">
                <button className="btn-clay flex-1 text-base" style={{ background: ACCENT }} disabled={active || starting || (!file && source !== "upload")} onClick={() => start()}>
                  {active || starting ? <Loader2 size={18} className="animate-spin" /> : source === "upload" ? <FileUp size={18} /> : <Play size={18} fill="currentColor" />}
                  {runLabel}
                </button>
                {active && run && <button className="btn-ghost" onClick={() => api.cancelAnalysis(run.id)}><Square size={14} /> Stop</button>}
              </div>
              {startError && (
                <div className="space-y-1">
                  <NextActions message={startError.message} kind={startError.kind} detail={startError.detail} sourceUrl={d.canonicalUrl}
                    onAction={(a) => void act(a)} />
                  <p className="text-xs text-ink-soft">Nothing was started.</p>
                </div>
              )}
              {filesError && <ErrorBox message={`Couldn't list files: ${filesError}`} />}
            </div>

            <div className="glass flex min-h-[340px] flex-col rounded-3xl p-5">
              {!run ? (
                <div className="m-auto max-w-sm text-center">
                  <p className="font-display text-2xl font-bold">Nothing has run yet</p>
                  <p className="mt-2 text-sm text-ink-soft">{blocked
                    ? "No job starts until there's a file to read. Connect the provider, or upload a file you downloaded (any type; it's detected from its content)."
                    : "Start with a sample. It reads 1,000 real records and builds the charts below."}</p>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusPill status={run.status} />
                    <span className="text-sm text-ink-soft">{run.mode === "full" ? "Full analysis" : run.params?.prepare ? "Prepared sample" : "Sample"} · {run.file_name} · run {run.id} · <Elapsed run={run} /></span>
                    {run.id !== latestGood && run.status === "succeeded" && <span className="text-xs text-ink-faint">earlier run</span>}
                  </div>
                  <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/80 shadow-neu-in" aria-hidden>
                    <motion.div className="h-full rounded-full" style={{ background: run.status === "failed" ? "#E5484D" : ACCENT }}
                      animate={{ width: `${Math.max(progress, active ? 0.06 : 0) * 100}%` }} transition={{ type: "spring", stiffness: 120, damping: 20 }} />
                  </div>
                  <ol className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm" aria-label="Stages">
                    {STAGES.map((s, i) => {
                      const done = run.status === "succeeded" || i < stage;
                      const here = i === stage && run.status !== "succeeded";
                      return (
                        <li key={s.key} className={`font-semibold ${here && run.status === "failed" ? "text-bad" : here ? "text-ink" : done ? "text-ok" : "text-ink-faint"}`} aria-current={here ? "step" : undefined}>
                          {done ? "✓ " : here && active ? "• " : ""}{s.label}{i < STAGES.length - 1 && <span className="ml-3 text-ink-faint" aria-hidden>→</span>}
                        </li>
                      );
                    })}
                  </ol>
                  {phase && <p className="mt-2 text-sm tabular-nums text-ink-soft" aria-live="polite">{phase}</p>}
                  <pre ref={logRef} className="mt-3 max-h-72 flex-1 overflow-auto whitespace-pre-wrap [overflow-wrap:anywhere] rounded-2xl border border-white bg-sky-wash p-4 font-[ui-monospace,Menlo,Consolas,monospace] text-[12.5px] leading-6 text-ink-soft"
                    aria-live="polite" aria-label="Run log">{run.log || "Waiting for output"}</pre>
                  {failKind && (
                    <div className="mt-3 space-y-2">
                      <NextActions prefix={failureLabel(failKind, run.stage)} message={run.error ?? "the run stopped"} kind={failKind} sourceUrl={d.canonicalUrl}
                        detail={run.error_detail ?? (failKind === "consent" ? { consentUrl: d.canonicalUrl, actions: ["open_consent", "retry"] } : null)}
                        onAction={(a) => void act(a, run)} />
                      {RETRYABLE.has(failKind) && run.file_url && !run.error_detail?.actions?.length && (
                        <button className="btn-ghost" onClick={() => void act("retry", run)}>Retry</button>
                      )}
                      {failKind === "timeout" && run.mode === "full" && run.file_url && (
                        <button className="btn-ghost" onClick={() => void act("run_sample", run)}>Run sample instead</button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {run?.status === "succeeded" && run.report && <AnalysisResults run={run} title={d.title} />}
          {run && run.status !== "succeeded" && fallback?.report && (
            <>
              <p className="rounded-2xl bg-white/70 px-4 py-2.5 text-sm text-ink-soft">
                Showing the last successful run ({fallback.report.kind === "inspection" ? "inspection" : fallback.mode === "full" ? "full analysis" : "sample"}, {timeAgo(fallback.finished_at ?? fallback.created_at)}).
              </p>
              <AnalysisResults run={fallback} title={d.title} />
            </>
          )}
        </div>

        {tab === "Schema" && (
          (run?.report ?? fallback?.report)
            ? <div className="glass rounded-3xl p-5"><SchemaTable rep={(run?.report ?? fallback?.report)!} bare /></div>
            : <p className="glass rounded-3xl p-6 text-ink-soft">Run a sample to measure the schema.</p>
        )}
        {tab === "History" && (
          !runs.data?.length ? <p className="glass rounded-3xl p-6 text-ink-soft">No runs yet. Start one from the Run tab.</p> : (
            <ul className="space-y-2">
              {runs.data.map((r) => (
                <li key={r.id}>
                  <button onClick={() => { setSp({ run: r.id }); setTab("Run"); }} className="glass flex w-full flex-wrap items-center gap-3 rounded-2xl px-4 py-3 text-left hover:bg-white/80">
                    <StatusPill status={r.status} />
                    <span className="text-sm font-semibold">{r.mode === "full" ? "Full analysis" : "Sample"}</span>
                    <span className="min-w-0 flex-1 truncate text-sm text-ink-soft">{r.status === "failed" ? `${failureLabel(r.error_kind, r.stage)}: ${r.error ?? ""}` : r.file_name}</span>
                    <span className="text-xs text-ink-faint">{timeAgo(r.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        )}
      </div>
    </div>
  );
}
