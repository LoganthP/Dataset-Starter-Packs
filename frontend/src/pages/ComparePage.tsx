import { ArrowLeft, BarChart3, ExternalLink, Loader2, Save, Trash2, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, timeAgo, useApi } from "../api";
import { EvidenceBadge, FIT_STYLE, OutcomeIcon, RichText, fmtDate } from "../components/discover/bits";
import { ErrorBox, Spinner } from "../components/ui";
import { criteriaQuery, label } from "../lib/searchState";
import { sectionHref } from "../lib/session";
import { rememberTitle, titleOf, useShortlist } from "../lib/shortlist";
import type { ComparisonItem, Reason } from "../types";
import { rowsLabel } from "../lib/analysisText";

const CONCEPTS: [string, string][] = [["latlon", "Latitude and longitude"], ["timestamp", "Timestamp"], ["target_label", "Target label"], ["join_key", "Join key"]];

function conceptCell(d: ComparisonItem, concept: string) {
  const f = d.fields.filter((x) => x.concepts.includes(concept));
  const rec = f.filter((x) => x.level === "record");
  if (rec.length) return <span className="flex items-center gap-1.5"><OutcomeIcon outcome="met" />{rec.map((x) => x.name).join(", ")}</span>;
  if (f.length) return <span className="flex items-center gap-1.5"><OutcomeIcon outcome="failed" />{f[0].name} ({f[0].level === "input" ? "API input" : "grid"})</span>;
  if (d.schemaStatus === "complete") return <span className="flex items-center gap-1.5"><OutcomeIcon outcome="failed" />Not in schema</span>;
  return <span className="flex items-center gap-1.5 text-warn-ink"><OutcomeIcon outcome="unverified" />Unknown</span>;
}

type Row = [string, (d: ComparisonItem) => ReactNode] | [string, null];

/** Side-by-side table, shared by the live comparison and saved reports. */
export function ComparisonTable({ items, onRemove, saved = false }: { items: ComparisonItem[]; onRemove?: (id: string) => void; saved?: boolean }) {
  const reasonKeys = [...new Map(items.flatMap((d) => d.reasons).map((r) => [r.key, r.label])).entries()];
  const reasonFor = (d: ComparisonItem, key: string): Reason | undefined => d.reasons.find((r) => r.key === key);
  const pending = (d: ComparisonItem) => (
    <span className="text-warn-ink">
      Analysis pending{!saved && d.analyzable !== false && <> · <Link className="font-semibold underline" to={`/datasets/${encodeURIComponent(d.id)}?analyze=1`}>Analyze</Link></>}
    </span>
  );
  const rows: Row[] = [
    ...(reasonKeys.length ? ([
      ["Your requirements", null],
      ["Overall fit", (d) => <span className={`flex items-center gap-1 font-bold ${FIT_STYLE[d.fit].cls}`}>{FIT_STYLE[d.fit].icon}{FIT_STYLE[d.fit].label}</span>],
      ...reasonKeys.map(([key, text]) => [text, (d: ComparisonItem) => {
        const r = reasonFor(d, key);
        return r ? <span className="flex gap-1.5"><OutcomeIcon outcome={r.outcome} /><span className="text-ink-soft"><RichText text={r.text} /></span></span> : "—";
      }] as Row),
    ] as Row[]) : []),
    ["Source", null],
    ["Provider", (d) => <a className="inline-flex items-center gap-1 underline" href={d.canonicalUrl} target="_blank" rel="noreferrer">{d.provider}<ExternalLink size={12} /></a>],
    ["Format", (d) => <span className="flex flex-wrap items-center gap-1.5">{d.formats.values.map((f) => label("formats", f)).join(", ") || "Unknown"}<EvidenceBadge status={d.formats.status} /></span>],
    ["Access", (d) => label("access", d.access.class)],
    ["License", (d) => <span className="flex flex-wrap items-center gap-1.5">{d.license.name ?? "Unknown"}<EvidenceBadge status={d.license.status} /></span>],
    ["Observations", (d) => <span className="flex flex-wrap items-center gap-1.5">{d.coverage.temporal.text}<EvidenceBadge status={d.coverage.temporal.status} /></span>],
    ["Area covered", (d) => d.coverage.spatial.text],
    ...CONCEPTS.filter(([c]) => !reasonKeys.some(([k]) => k === `field:${c}`)).map(([c, t]) => [t, (d: ComparisonItem) => conceptCell(d, c)] as Row),
    ["Latest analysis", null],
    ["Analysis run", (d) => (d.analysis
      ? <Link className="inline-flex items-center gap-1 font-semibold text-link underline" to={`/analyses/${d.analysis.runId}`}><BarChart3 size={13} />{fmtDate(d.analysis.at)}</Link>
      : pending(d))],
    ["Rows analyzed", (d) => (d.analysis ? rowsLabel(d.analysis.rowsAnalyzed, d.analysis.rowsTotal, d.analysis.coverage) : "—")],
    ["Missing cells", (d) => (d.analysis ? `${d.analysis.missingPct}%` : "—")],
    ["Duplicate rows", (d) => (d.analysis ? d.analysis.duplicateRows?.toLocaleString() ?? "n/a" : "—")],
    ["Measured dates", (d) => (d.analysis?.dateCoverage ? `${fmtDate(d.analysis.dateCoverage.min)} to ${fmtDate(d.analysis.dateCoverage.max)}` : d.analysis ? "No date column" : "—")],
    ["Schema", (d) => (d.analysis ? (
      <details>
        <summary className="cursor-pointer text-link">{d.analysis.schema.length} columns</summary>
        <ul className="mt-1 space-y-0.5 text-xs">{d.analysis.schema.map((c) => <li key={c.name}><b>{c.name}</b> <span className="text-ink-faint">{c.type}{c.missingPct ? `, ${c.missingPct}% missing` : ""}</span></li>)}</ul>
      </details>
    ) : d.fieldNames.length ? <span className="text-ink-soft">{d.fieldNames.length} documented fields</span> : "—")],
  ];

  return (
    <div className="glass overflow-x-auto rounded-3xl p-2">
      <table className="w-full min-w-[760px] border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th className="w-44 p-3" />
            {items.map((d) => (
              <th key={d.id} className="min-w-[220px] p-3 text-left align-top">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-ink-faint">{d.provider}</p>
                    <Link to={`/datasets/${encodeURIComponent(d.id)}`} className="font-display text-base font-bold leading-snug hover:underline">{d.title}</Link>
                  </div>
                  {onRemove && (
                    <button className="rounded-lg p-1 text-ink-faint hover:bg-white hover:text-ink" onClick={() => onRemove(d.id)} aria-label={`Remove ${d.title} from comparison`}><X size={16} /></button>
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, render], i) => render === null ? (
            <tr key={`h-${name}`}><th colSpan={items.length + 1} scope="colgroup" className="px-3 pb-1 pt-4 text-left font-display text-sm font-bold">{name}</th></tr>
          ) : (
            <tr key={`${i}-${name}`} className="odd:bg-white/50">
              <th scope="row" className="p-3 text-left align-top font-semibold text-ink-soft">{name}</th>
              {items.map((d) => <td key={d.id} className="p-3 align-top">{render(d)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SavedList({ refreshKey }: { refreshKey: number }) {
  const list = useApi(() => api.comparisons(), [refreshKey]);
  if (!list.data?.length) return null;
  return (
    <section aria-labelledby="saved-h" className="space-y-3">
      <h2 id="saved-h" className="font-display text-2xl font-bold">Saved comparisons</h2>
      <ul className="glass divide-y divide-white/80 rounded-3xl">
        {list.data.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <span className="w-32 shrink-0 text-ink-faint">{fmtDate(c.created_at)}</span>
            <span className="min-w-0 flex-1 font-semibold">{c.dataset_titles.join(" · ")}</span>
            <span className="text-xs text-ink-faint">{Object.values(c.analysis_run_ids).filter(Boolean).length} of {c.dataset_ids.length} analyzed</span>
            <Link className="btn-ghost !py-1" to={`/compare/${c.id}`}>Open comparison</Link>
            <button className="rounded-lg p-1.5 text-ink-faint hover:bg-white hover:text-bad" aria-label={`Delete saved comparison from ${fmtDate(c.created_at)}`}
              onClick={async () => { await api.deleteComparison(c.id); void list.reload(); }}><Trash2 size={15} /></button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The Compare tab: the queue (shared with Discover and Curated Packs), the live table, and saved reports. */
export default function ComparePage() {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const shortlist = useShortlist();
  const [saving, setSaving] = useState(false);
  const [savedKey, setSavedKey] = useState(0);
  const [saveError, setSaveError] = useState<string | null>(null);

  // A shared link (?ids=a,b) is adopted as the queue, then the URL is cleaned.
  useEffect(() => {
    const shared = (sp.get("ids") ?? "").split(",").filter(Boolean).slice(0, 3);
    if (shared.length) {
      shortlist.set(shared);
      const next = new URLSearchParams(sp);
      next.delete("ids");
      setSp(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ids = shortlist.ids;
  const lastDiscover = sectionHref("discover");
  const criteria = (sp.toString() ? criteriaQuery(sp) : criteriaQuery(new URLSearchParams(lastDiscover.split("?")[1] ?? ""))).toString();
  const res = useApi(() => (ids.length ? api.currentComparison(ids, criteria) : Promise.resolve({ items: [] as ComparisonItem[] })), [ids.join(","), criteria]);
  const items = res.data?.items ?? [];
  items.forEach((d) => rememberTitle(d.id, d.title));

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const rep = await api.saveComparison(ids, criteria);
      setSavedKey((k) => k + 1);
      nav(`/compare/${rep.id}`);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight">Compare</h1>
          <p className="mt-1 text-ink-soft">Up to three datasets side by side, with their latest analyses.</p>
        </div>
      </div>

      <section aria-labelledby="queue-h" className="glass rounded-3xl p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="queue-h" className="font-display text-lg font-bold">Current selection {ids.length}/3</h2>
          {ids.map((id) => (
            <span key={id} className="inline-flex max-w-[260px] items-center gap-1 rounded-full bg-white py-1 pl-3 pr-1 text-sm font-semibold">
              <span className="truncate">{titleOf(id)}</span>
              <button onClick={() => shortlist.toggle(id)} className="rounded-full p-0.5 hover:bg-sky-deep" aria-label={`Remove ${titleOf(id)}`}><X size={14} /></button>
            </span>
          ))}
          {ids.length > 0 && (
            <div className="ml-auto flex gap-2">
              <button className="btn-ghost" onClick={shortlist.clear}>Clear queue</button>
              <button className="btn-clay bg-peri px-4 py-2 text-sm" onClick={save} disabled={saving || ids.length < 1 || res.loading}>
                {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Save comparison
              </button>
            </div>
          )}
        </div>
        {saveError && <div className="mt-3"><ErrorBox message={saveError} /></div>}
      </section>

      {ids.length === 0 ? (
        <div className="glass rounded-3xl p-8 text-center">
          <p className="font-display text-2xl font-bold">Your comparison queue is empty</p>
          <p className="mx-auto mt-1 max-w-[52ch] text-ink-soft">Choose Compare on up to three results. They stay here while you switch tabs.</p>
          <Link to={lastDiscover} className="btn-clay mt-5 bg-peri">{lastDiscover === "/" ? "Go to Discover" : "Back to your last search"}</Link>
        </div>
      ) : res.loading && !res.data ? <Spinner label="Loading comparison" /> : res.error ? <ErrorBox message={res.error} /> : (
        <>
          <ComparisonTable items={items} onRemove={(id) => shortlist.toggle(id)} />
          {criteria && <p className="text-sm text-ink-soft">Requirements from your last Discover search: <code className="rounded bg-sky-deep/60 px-1">{decodeURIComponent(criteria)}</code></p>}
        </>
      )}

      <SavedList refreshKey={savedKey} />
    </div>
  );
}

/** A saved comparison: an immutable snapshot that keeps the analysis runs it was saved with. */
export function ComparisonReportPage() {
  const { reportId = "" } = useParams();
  const rep = useApi(() => api.comparison(reportId), [reportId]);
  if (rep.loading && !rep.data) return <Spinner label="Loading comparison" />;
  if (rep.error || !rep.data) return <ErrorBox message={rep.error ?? "Not found"} action={<Link className="btn-ghost" to="/compare">Compare</Link>} />;
  const r = rep.data;
  return (
    <div className="space-y-5">
      <Link to="/compare" className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-soft hover:text-ink"><ArrowLeft size={16} /> Compare</Link>
      <header>
        <h1 className="text-3xl font-extrabold tracking-tight">{r.name}</h1>
        <p className="mt-1 text-ink-soft">Saved {fmtDate(r.created_at)} ({timeAgo(r.created_at)}). This snapshot keeps the analysis runs it was saved with; newer analyses don't change it.</p>
      </header>
      <ComparisonTable items={r.snapshot} saved />
    </div>
  );
}
