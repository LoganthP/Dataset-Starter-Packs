/** Pieces of the analyzed-dataset Run view: file picker (paged, grouped, searchable), archive inspector,
 * Kaggle connection banner, limit/failure notices with next actions, and phase progress text. */
import { CheckCircle2, ExternalLink, FileSearch, FileUp, Loader2, PlugZap, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, sizeLabel } from "../../api";
import { ACTION_LABEL } from "../../lib/analysisText";
import type { AnalysisRun, DataFileInfo, FileList, InspectResult, KaggleStatus, LimitDetail, User } from "../../types";

const GROUP_LABEL: Record<string, string> = { whole: "Entire dataset", pairs: "Paired files (state vectors + metadata)", unpaired: "Metadata without a pair",
  converted: "Parquet conversions (datasets-server)" };

export function fileLabel(f: DataFileInfo): string {
  const size = f.bytes ? ` · ${sizeLabel(f.bytes + (f.pair_bytes ?? 0))}` : "";
  if (f.label) return `${f.label}${size}`;
  return `${f.name ?? f.url} (${(f.format ?? "").toUpperCase()})${size}`;
}

export function FilePicker({ id, files, value, onChange, onMore }: {
  id: string; files: FileList; value: string; onChange: (url: string) => void; onMore: (next: FileList) => void;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const many = (files.total ?? files.files.length) > files.files.length || (files.total ?? 0) > 80;
  const supported = files.files.filter((f) => f.supported);
  const groups = new Map<string, DataFileInfo[]>();
  for (const f of supported) groups.set(f.group ?? "files", [...(groups.get(f.group ?? "files") ?? []), f]);
  const search = async (text: string, offset = 0) => {
    setBusy(true);
    try {
      const next = await api.files(id, { q: text || undefined, offset, limit: 80 });
      onMore(offset ? { ...next, files: [...files.files, ...next.files] } : next);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2">
      {many && (
        <form className="relative" onSubmit={(e) => { e.preventDefault(); void search(q); }}>
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" aria-hidden />
          <input className="field pl-8" placeholder="Filter files by name or prefix" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter files" />
        </form>
      )}
      <select id="src" className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        {[...groups.entries()].map(([g, list]) => (
          <optgroup key={g} label={GROUP_LABEL[g] ?? "Files"}>
            {list.map((f) => <option key={f.url} value={f.url}>{fileLabel(f)}</option>)}
          </optgroup>
        ))}
        <option value="upload">Upload a file I downloaded…</option>
      </select>
      {many && (
        <p className="flex items-center justify-between text-xs text-ink-soft">
          <span>Showing {files.files.length.toLocaleString()} of {(files.matched ?? files.total).toLocaleString()} files{files.pairs ? ` · ${files.pairs.toLocaleString()} pairs` : ""}</span>
          {files.files.length < (files.matched ?? files.total) && (
            <button type="button" className="font-semibold text-link underline" disabled={busy} onClick={() => search(q, files.files.length)}>
              {busy ? "Loading…" : "Load more"}
            </button>
          )}
        </p>
      )}
    </div>
  );
}

export function PairNote({ file }: { file?: DataFileInfo }) {
  if (!file?.pair_url) return null;
  return (
    <p className="rounded-2xl bg-white/70 px-3 py-2 text-xs text-ink-soft [overflow-wrap:anywhere]">
      Runs <code className="break-all">{file.name}</code> with <code>{file.pair_name}</code> (same <code>{file.prefix}</code> prefix): trajectory, state components over time and
      maneuver markers from the state vectors; the simulation settings from the metadata.
    </p>
  );
}

export function KaggleBanner({ files, user, kaggle }: { files: FileList | null; user: User | null; kaggle: KaggleStatus | null }) {
  const loc = useLocation();
  if (files?.connect !== "kaggle") return null;
  const back = encodeURIComponent(loc.pathname + loc.search);
  if (kaggle?.connected && files.files.length) {
    return <p className="flex items-center gap-1.5 text-xs text-ok"><CheckCircle2 size={13} /> Fetching with your Kaggle account{kaggle.account ? ` (${kaggle.account})` : ""}.</p>;
  }
  return (
    <div className="rounded-2xl bg-peri/10 px-3 py-3 text-sm">
      <p className="font-semibold">{kaggle?.connected ? "Kaggle didn't list files for your account." : "Connect Kaggle to fetch this dataset here."}</p>
      <p className="mt-1 text-xs text-ink-soft">{files.note ?? "Kaggle downloads need your own account. Connect once; the files then list here and run like any other source."}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Link className="btn-clay bg-peri px-3 py-1.5 text-sm" to={`/settings?return=${back}`}><PlugZap size={14} /> {user ? (kaggle?.connected ? "Reconnect Kaggle" : "Connect Kaggle") : "Log in and connect Kaggle"}</Link>
        {files.consentUrl && <a className="btn-ghost px-3 py-1.5 text-sm" href={files.consentUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open on Kaggle</a>}
      </div>
    </div>
  );
}

export function Inspector({ id, file, chosen, onChoose }: { id: string; file?: DataFileInfo; chosen: string[]; onChoose: (names: string[]) => void }) {
  const [info, setInfo] = useState<InspectResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setInfo(null); setError(null); }, [file?.url]);
  if (!file || file.pair_url || !["zip", "unknown"].includes(file.format ?? "")) return null;
  const look = async () => {
    setBusy(true);
    setError(null);
    try {
      setInfo(await api.inspect(id, file.url));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const toggle = (name: string) => onChoose(chosen.includes(name) ? chosen.filter((n) => n !== name) : [...chosen, name]);
  return (
    <div className="rounded-2xl border border-white/70 bg-white/50 p-3">
      {!info ? (
        <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={look} disabled={busy}>
          {busy ? <Loader2 size={14} className="animate-spin" /> : <FileSearch size={14} />} Look inside before running
        </button>
      ) : (
        <div className="space-y-2 text-sm">
          <p className="font-semibold">
            {info.detected === "zip" ? `ZIP · ${info.memberCount?.toLocaleString() ?? "?"} files · ${sizeLabel(info.bytes)} → ${sizeLabel(info.expandedBytes)} expanded` : `Detected: ${info.detected}`}
          </p>
          {info.suggested && (
            <p className="text-xs text-ink-soft">
              Analysis: <strong className="text-ink">{info.suggested.label}</strong>. A sample reads {plural(info.suggested.sampleFiles, "file")}
              ({sizeLabel(info.suggested.sampleBytes)}); a full run reads {plural(info.suggested.fullFiles, "file")} ({sizeLabel(info.suggested.fullBytes)}).
            </p>
          )}
          {info.suggested && (
            <p className="text-xs text-ink-soft">
              {info.cached ? "The archive is already downloaded here: runs reuse it, nothing is transferred."
                : info.membersCached ? "The files this analysis reads are saved from an earlier run: runs reuse them, nothing is transferred."
                : info.rangeReads ? <>The server allows partial reads, so a run transfers about <strong className="text-ink">{sizeLabel(info.suggested.fullTransfer)}</strong> of the {sizeLabel(info.bytes)} archive.</>
                  : `Runs download the whole ${sizeLabel(info.bytes)} archive once and keep it.`}
              {info.source === "cache" ? (info.cached ? " Listed from the saved copy." : " Listed from the saved archive directory.") : ""}
            </p>
          )}
          {info.types && <p className="text-xs text-ink-soft">{info.types.slice(0, 6).map((t) => `${t.files.toLocaleString()} ${t.type}`).join(" · ")}</p>}
          {info.note && <p className="text-xs text-warn-ink">{info.note}</p>}
          {info.members && (
            <details>
              <summary className="cursor-pointer text-xs font-semibold">Choose files to analyze {chosen.length ? `(${chosen.length} chosen)` : "(optional)"}</summary>
              <ul className="mt-2 max-h-56 space-y-1 overflow-auto pr-1">
                {info.members.map((m) => (
                  <li key={m.name}>
                    <label className="flex items-center gap-2 text-xs">
                      <input type="checkbox" checked={chosen.includes(m.name)} onChange={() => toggle(m.name)} />
                      <span className="min-w-0 flex-1 truncate" title={m.name}>{m.name}</span>
                      <span className="shrink-0 text-ink-faint">{m.type} · {sizeLabel(m.size)}</span>
                    </label>
                  </li>
                ))}
              </ul>
              {chosen.length > 0 && <button type="button" className="mt-1 text-xs font-semibold text-link underline" onClick={() => onChoose([])}>Clear choice</button>}
            </details>
          )}
        </div>
      )}
      {error && <p className="mt-2 text-xs text-bad">{error}</p>}
    </div>
  );
}

/** Which limit, the measured or estimated size, and buttons for the next actions the API suggested. */
export function NextActions({ message, kind, detail, onAction, sourceUrl, prefix }: {
  message: string; kind?: string | null; detail?: LimitDetail | null; sourceUrl: string; prefix?: string;
  onAction: (action: string) => void;
}) {
  const actions = detail?.actions?.length ? detail.actions
    : kind === "auth" || kind === "not_found" ? ["open_source", "upload"] : kind === "format" ? ["upload", "open_source"]
    : kind === "consent" ? ["open_consent", "retry"] : [];
  return (
    <div className="space-y-2 rounded-2xl border border-bad/20 bg-white/80 p-3" role="alert">
      <p className="text-sm font-semibold text-ink">{prefix ? `${prefix}: ` : ""}{message}</p>
      {detail?.limit && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-xs text-ink-soft">
          <dt>Limit</dt><dd>{detail.limitLabel ?? detail.limit}: {sizeLabel(detail.limitBytes)}{detail.limitEnv ? ` (${detail.limitEnv})` : ""}</dd>
          <dt>{detail.estimated ? "Reported size" : "Measured"}</dt><dd>{sizeLabel(detail.measuredBytes)}{detail.estimated ? " (from the server, before downloading)" : ""}</dd>
        </dl>
      )}
      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {actions.map((a) => a === "open_source" ? (
            <a key={a} className="btn-ghost px-3 py-1.5 text-sm" href={sourceUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> {ACTION_LABEL[a]}</a>
          ) : a === "open_consent" ? (
            <a key={a} className="btn-clay bg-peri px-3 py-1.5 text-sm" href={detail?.consentUrl ?? sourceUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> {ACTION_LABEL[a]}</a>
          ) : (
            <button key={a} className={a === "prepare_archive_sample" || a === "retry" ? "btn-clay bg-peri px-3 py-1.5 text-sm" : "btn-ghost px-3 py-1.5 text-sm"}
              onClick={() => onAction(a)}>
              {a === "upload" && <FileUp size={14} />} {ACTION_LABEL[a] ?? a}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** "412 MB of 1.2 GB downloaded", "Extracting 120 of 500 files", "Analyzing 300 of 500 images", rows for paged sources. */
export function phaseText(run: AnalysisRun): string | null {
  const p = run.progress;
  if (!p) return null;
  if (p.rows != null && p.row_total != null && (run.stage === "downloading" || run.stage === "resolving")) {
    return `${p.rows.toLocaleString()} of ${p.row_total.toLocaleString()} rows fetched`;
  }
  if (p.phase === "downloading" || (run.stage === "downloading" && p.bytes != null)) {
    return `${sizeLabel(p.bytes ?? p.done ?? 0)}${p.total ? ` of ${sizeLabel(p.total)} received (${Math.round((100 * (p.bytes ?? 0)) / p.total)}%)` : " received (total size not reported)"}`;
  }
  if (p.phase === "extracting") return run.stage === "extracting" && p.bytes_total != null && p.bytes != null && p.bytes <= (p.bytes_total ?? 0) * 1.5 && run.log.includes("HTTP ranges")
    ? `Reading ${p.done?.toLocaleString()} of ${p.total_items?.toLocaleString()} files from the remote archive: ${sizeLabel(p.bytes)} received`
    : `Extracting ${p.done?.toLocaleString()} of ${p.total_items?.toLocaleString()} files (${sizeLabel(p.bytes)})`;
  if (p.phase === "analyzing" && p.unit) return `Analyzing ${p.done?.toLocaleString()} of ${p.total_items?.toLocaleString()} ${p.unit}`;
  if (p.rows != null && p.row_total != null) return `${p.rows.toLocaleString()} of ${p.row_total.toLocaleString()} rows fetched · all pages verified`;
  return null;
}

export function phaseShare(run: AnalysisRun): number {
  const p = run.progress;
  if (!p) return 0.5;
  if (p.rows != null && p.row_total) return Math.min(1, p.rows / p.row_total);
  if (p.phase === "downloading" && p.total) return Math.min(1, (p.bytes ?? 0) / p.total);
  if ((p.phase === "extracting" || p.phase === "analyzing") && p.total_items) return Math.min(1, (p.done ?? 0) / p.total_items);
  return 0.5;
}

function plural(count: number, word: string) {
  return `${count.toLocaleString()} ${word}${count === 1 ? "" : "s"}`;
}
