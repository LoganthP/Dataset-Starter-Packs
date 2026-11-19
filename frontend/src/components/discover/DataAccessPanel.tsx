import { BarChart3, ExternalLink, Eye, FileText, FileUp, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ApiError, fmtBytes, timeAgo, useDiscoverMeta } from "../../api";
import type { DatasetSummary, FileList, PreviewData } from "../../types";
import { ErrorBox } from "../ui";
import { rowsLabel } from "../../lib/analysisText";

function cell(v: unknown) {
  if (v === null || v === undefined) return "—";
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  return s.length > 120 ? `${s.slice(0, 117)}…` : s;
}

const FORMAT_LABEL: Record<string, string> = { csv: "CSV", tsv: "TSV", parquet: "Parquet", json: "JSON", zip: "ZIP", xlsx: "Excel" };

/**
 * Analyze: ask the provider for the dataset's files (even when search said "Format unknown"), pick a CSV,
 * Parquet, JSON or Excel file and analyze it, or upload a file downloaded from a sign-in source.
 * `autoFiles` starts resolving straight away (the "Analyze dataset" button on a result card).
 */
export default function DataAccessPanel({ d, compact = false, autoFiles = false }: { d: DatasetSummary; compact?: boolean; autoFiles?: boolean }) {
  const nav = useNavigate();
  const meta = useDiscoverMeta();
  const caps = meta?.capabilities;
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [files, setFiles] = useState<FileList | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<{ message: string; kind?: string } | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const isDoc = d.kind === "documentation";
  // Runs open on the dataset's own page (Insights tab), so analyzing feels like staying with this dataset.
  const open = (runId: string) => nav(`/datasets/${encodeURIComponent(d.id)}/run?run=${runId}`);

  const act = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError({ message: (e as Error).message, kind: (e as ApiError).kind });
    } finally {
      setBusy(null);
      setProgress(null);
    }
  };
  const listFiles = (refresh = false) =>
    act("files", async () => {
      const res = await api.files(d.id, { refresh });
      setFiles(res);
      setChosen(res.files.find((f) => f.supported)?.url ?? null);
    });

  useEffect(() => {
    if (autoFiles && !files) void listFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFiles]);

  const supported = files?.files.filter((f) => f.supported) ?? [];
  const others = files?.files.filter((f) => !f.supported) ?? [];
  const chosenFile = supported.find((f) => f.url === chosen);

  return (
    <section className={compact ? "space-y-3" : "glass space-y-3 rounded-3xl p-5"} aria-label="Analyze this dataset">
      {!compact && <h2 className="font-display text-xl font-bold">Analyze this dataset</h2>}

      {d.analysis && (
        <p className="flex flex-wrap items-center gap-2 rounded-2xl bg-ok/10 px-3 py-2 text-sm">
          <BarChart3 size={15} className="text-ok" />
          <span>Analyzed {timeAgo(d.analysis.at)}: {rowsLabel(d.analysis.rowsAnalyzed, d.analysis.rows, d.analysis.coverage)}, {d.analysis.columns} columns.</span>
          <Link className="font-semibold text-link underline" to={`/datasets/${encodeURIComponent(d.id)}/run`}>View run</Link>
        </p>
      )}

      {isDoc && !files && (
        <p className="flex gap-2 rounded-2xl bg-sky-deep/60 px-3 py-2 text-sm text-ink-soft">
          <FileText size={16} className="mt-0.5 shrink-0" />
          <span>The source describes this record as documentation. Find its files to check whether data is attached, or upload a data file.</span>
        </p>
      )}

      {busy === "files" && (
        <p className="flex items-center gap-2 rounded-2xl bg-white/70 px-3 py-3 text-sm text-ink-soft" role="status">
          <Loader2 size={15} className="animate-spin text-peri" /> Asking {d.provider} for this dataset's files…
        </p>
      )}

      {files && busy !== "files" && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">
              {supported.length ? "Choose a file to analyze" : files.signInRequired ? `${d.provider} needs sign-in to download` : "No file can be fetched directly"}
            </span>
            {files.via && supported.length > 0 && <span className="text-xs text-ink-faint">listed by {files.via}</span>}
            <button className="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-ink-soft hover:bg-white"
              onClick={() => listFiles(true)}><RefreshCw size={12} /> Check again</button>
          </div>
          {supported.length > 0 && (
            <ul className="overflow-hidden rounded-2xl bg-white/80" role="radiogroup" aria-label="Files you can analyze">
              {supported.slice(0, 25).map((f) => {
                const tooBig = !!f.bytes && f.bytes > files.maxMB * 2 ** 20;
                return (
                  <li key={f.url} className="border-b border-sky-deep/50 last:border-0">
                    <label className={`flex cursor-pointer items-center gap-3 px-3 py-2.5 text-sm ${chosen === f.url ? "bg-peri/10" : "hover:bg-sky-wash/60"} ${tooBig ? "opacity-50" : ""}`}>
                      <input type="radio" name={`file-${d.id}`} className="accent-peri" checked={chosen === f.url} disabled={tooBig}
                        onChange={() => setChosen(f.url)} />
                      <span className="min-w-0 flex-1 truncate font-semibold" title={f.url}>{f.name ?? f.url}</span>
                      <span className="rounded-md bg-sky-deep/70 px-1.5 text-xs font-semibold">{FORMAT_LABEL[f.format ?? ""] ?? f.format}</span>
                      <span className="w-20 text-right text-xs tabular-nums text-ink-faint">{f.bytes ? fmtBytes(f.bytes) : "size ?"}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {others.length > 0 && (
            <p className="text-xs text-ink-faint">
              Also listed, not analyzable: {others.slice(0, 6).map((f) => `${f.name} (${(f.format ?? "unknown").toUpperCase()})`).join(", ")}
              {others.length > 6 ? `, +${others.length - 6} more` : ""}
            </p>
          )}
          {(files.signInRequired || !supported.length) && (
            <div className="space-y-2 rounded-2xl bg-sun/30 px-3 py-2.5 text-sm text-warn-ink">
              <p>
                {files.unsupportedFormats?.length
                  ? `This dataset's files are ${files.unsupportedFormats.join(", ")}, which the app can't analyze yet. Nothing was started.`
                  : files.note ?? (files.signInRequired
                  ? `${d.provider} only serves this file to signed-in users who accept its terms.`
                  : `${d.provider} didn't list a CSV, Parquet, JSON or Excel file that can be fetched.`)}
              </p>
              <p className="font-semibold">{files.unsupportedFormats?.length
                ? "Open the source. If it offers a CSV or Parquet export, download that and choose Upload downloaded file."
                : "Open the source, download the file, then choose Upload downloaded file."}</p>
            </div>
          )}
          {supported.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn-clay bg-peri px-4 py-2 text-sm" disabled={!chosenFile || !!busy}
                onClick={() => act("sample", async () => open((await api.analyze(d.id, chosenFile!.url, "sample")).runId))}>
                {busy === "sample" ? <Loader2 size={15} className="animate-spin" /> : <BarChart3 size={15} />}
                {busy === "sample" ? "Checking the file…" : d.analysis ? "Reanalyze sample" : "Analyze sample"}
              </button>
              <button className="btn-ghost" disabled={!chosenFile || !!busy}
                title={`Download and profile the whole file (up to ${files.maxMB} MB). Can take minutes for big tables.`}
                onClick={() => act("full", async () => open((await api.analyze(d.id, chosenFile!.url, "full")).runId))}>
                {busy === "full" ? <Loader2 size={15} className="animate-spin" /> : null}
                {busy === "full" ? "Checking the file…" : "Run full analysis"}
              </button>
              <span className="text-xs text-ink-faint">A sample reads the first 1,000 rows and finishes within a minute.</span>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {!files && busy !== "files" && (
          <button className="btn-ghost" disabled={!!busy} onClick={() => listFiles()}><BarChart3 size={15} /> Find files to analyze</button>
        )}
        <input ref={upload} type="file" accept=".csv,.tsv,.tab,.txt,.parquet,.json,.jsonl,.ndjson,.geojson,.xlsx,.zip,.gz" className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void act("upload", async () => open((await api.analyzeUpload(d.id, f, caps, setProgress)).runId));
            e.target.value = "";
          }} />
        <button className="btn-ghost" disabled={!!busy} onClick={() => upload.current?.click()}>
          {busy === "upload" ? <Loader2 size={15} className="animate-spin" /> : <FileUp size={15} />}
          {busy === "upload" ? (progress !== null ? `Uploading ${Math.round(progress)}%` : "Uploading…") : "Upload downloaded file"}
        </button>
        {!isDoc && !files?.signInRequired && !d.access.signInRequired && (
          <button className="btn-ghost" disabled={!!busy} onClick={() => act("preview", async () => setPreview(await api.preview(d.id)))}>
            {busy === "preview" ? <Loader2 size={15} className="animate-spin" /> : <Eye size={15} />} Preview rows
          </button>
        )}
        <a className="btn-ghost" href={d.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open source</a>
      </div>

      {error && (
        <div className="space-y-2">
          <ErrorBox message={error.message} />
          {(error.kind === "auth" || error.kind === "not_found") && (
            <p className="text-sm text-ink-soft">Nothing was started. Open the source, download the file, then upload it here.</p>
          )}
          {error.kind === "too_large" && <p className="text-sm text-ink-soft">Nothing was started. Try the other option: a sample reads only the first rows.</p>}
        </div>
      )}

      {preview && (
        <div>
          <p className="mb-2 text-xs text-ink-faint">
            {preview.config ? `Config ${preview.config}, split ${preview.split}. ` : preview.file ? `${preview.file}. ` : ""}First {preview.rows.length} rows from{" "}
            <a className="underline" href={preview.source} target="_blank" rel="noreferrer">the provider</a>
          </p>
          <div className="max-h-80 overflow-auto rounded-2xl bg-white/85">
            <table className="w-full text-sm">
              <thead>
                <tr>{preview.columns.map((c) => <th key={c.name} className="sticky top-0 border-b border-sky-deep bg-white px-3 py-2 text-left font-semibold">{c.name}<span className="ml-1 text-xs font-normal text-ink-faint">{c.type}</span></th>)}</tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={i} className="align-top odd:bg-sky-wash/50">{r.map((v, j) => <td key={j} className="max-w-[360px] px-3 py-1.5 text-ink-soft">{cell(v)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
