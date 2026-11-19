import { BookOpen, CheckCircle2 } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api, fmtBytes, useApi } from "../api";
import { ErrorBox, Spinner } from "../components/ui";

export interface ColumnProfile {
  name: string;
  type: string;
  parsed_as?: string;
  null_pct: number;
  min?: unknown;
  max?: unknown;
  concepts: string[];
}

export interface FileImportData {
  id: string;
  file: string;
  record_id?: string;
  format: string;
  bytes: number;
  created_at: string;
  origin_url?: string;
  zip_members?: string[];
  profile: {
    rows: number;
    columns: ColumnProfile[];
    preview: unknown[][];
  };
}

export default function ImportPage() {
  const { id = "" } = useParams();
  const imp = useApi<FileImportData | null>(async () => {
    const fn = (api as unknown as { fileImport?: (id: string) => Promise<FileImportData> }).fileImport;
    if (fn) return fn(id);
    return null;
  }, [id]);

  if (imp.loading) return <Spinner label="Loading import" />;
  if (imp.error || !imp.data) return <ErrorBox message={imp.error ?? "Import not found"} />;
  const m = imp.data;
  const timeCols = m.profile.columns.filter((c: ColumnProfile) => c.concepts.includes("timestamp") && c.min);
  return (
    <div className="space-y-5">
      {m.record_id && <Link to={`/datasets/${encodeURIComponent(m.record_id)}`} className="text-sm font-semibold text-ink-soft hover:text-ink">Back to the dataset</Link>}
      <header className="glass-strong rounded-4xl p-6 sm:p-8">
        <p className="text-sm font-semibold text-ink-soft">Imported file</p>
        <h1 className="mt-1 break-all text-3xl font-extrabold tracking-tight">{m.file}</h1>
        <p className="mt-2 text-ink-soft">
          {m.profile.rows.toLocaleString()} rows · {m.profile.columns.length} columns · {m.format.toUpperCase()} · {fmtBytes(m.bytes)} · imported {new Date(m.created_at).toLocaleString()}
        </p>
        {m.zip_members && m.zip_members.length > 1 && (
          <p className="mt-1 text-sm text-ink-faint">The ZIP held {m.zip_members.length} data files; the largest was profiled: {m.zip_members.join(", ")}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <a className="btn-clay bg-peri px-4 py-2" href={api.url(`/api/file-imports/${m.id}/notebook`)}><BookOpen size={16} /> Download a starter notebook</a>
          {m.origin_url && <a className="btn-ghost" href={m.origin_url} target="_blank" rel="noreferrer">Original file</a>}
        </div>
      </header>

      {m.record_id && (
        <p className="flex items-start gap-2 rounded-2xl bg-ok/10 px-4 py-3 text-sm">
          <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-ok" />
          <span>
            The dataset's fields{timeCols.length ? " and date coverage" : ""} are now marked <b>verified</b> from this file, so requirement checks use what the file
            actually contains. {timeCols.length > 0 && <>Dates run from <b>{String(timeCols[0].min).slice(0, 10)}</b> to <b>{String(timeCols[0].max).slice(0, 10)}</b> in <code>{timeCols[0].name}</code>.</>}
            {" "}Other files or later releases may differ.
          </span>
        </p>
      )}

      <section className="glass rounded-3xl p-5">
        <h2 className="font-display text-xl font-bold">Columns</h2>
        <div className="mt-3 overflow-x-auto rounded-2xl bg-white/80">
          <table className="w-full min-w-[640px] text-sm">
            <thead><tr className="text-left">{["Column", "Type", "Empty", "Range", "Detected as"].map((h) => <th key={h} className="border-b border-sky-deep px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
            <tbody>
              {m.profile.columns.map((c: ColumnProfile) => (
                <tr key={c.name} className="odd:bg-sky-wash/50">
                  <td className="px-3 py-1.5 font-semibold">{c.name}</td>
                  <td className="px-3 py-1.5 text-ink-soft">{c.type}{c.parsed_as ? ` → ${c.parsed_as}` : ""}</td>
                  <td className="px-3 py-1.5 tabular-nums text-ink-soft">{c.null_pct}%</td>
                  <td className="px-3 py-1.5 text-ink-soft">{c.min !== undefined ? `${String(c.min).slice(0, 19)} → ${String(c.max).slice(0, 19)}` : "—"}</td>
                  <td className="px-3 py-1.5">{c.concepts.map((k: string) => <span key={k} className="mr-1 rounded-full bg-peri/15 px-2 py-0.5 text-xs font-bold text-[#3d43c9]">{k}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass rounded-3xl p-5">
        <h2 className="font-display text-xl font-bold">First rows</h2>
        <div className="mt-3 max-h-96 overflow-auto rounded-2xl bg-white/80">
          <table className="w-full text-sm">
            <thead><tr>{m.profile.columns.map((c: ColumnProfile) => <th key={c.name} className="sticky top-0 border-b border-sky-deep bg-white px-3 py-2 text-left font-semibold">{c.name}</th>)}</tr></thead>
            <tbody>
              {m.profile.preview.map((r: unknown[], i: number) => (
                <tr key={i} className="odd:bg-sky-wash/50 align-top">{r.map((v: unknown, j: number) => <td key={j} className="max-w-[320px] truncate px-3 py-1.5 text-ink-soft">{v === null ? "—" : String(v)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
