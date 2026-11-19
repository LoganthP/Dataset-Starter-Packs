import { BarChart3, Check as CheckIcon, ChevronDown, ExternalLink, FileText, FileUp, Play, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { timeAgo } from "../../api";
import { label } from "../../lib/searchState";
import { useShortlist } from "../../lib/shortlist";
import type { DatasetSummary } from "../../types";
import { FIT_STYLE, OutcomeIcon, RichText } from "./bits";
import DataAccessPanel from "./DataAccessPanel";

export function SourceBadges({ item }: { item: DatasetSummary }) {
  return (
    <>
      {item.curated && <span className="rounded-full bg-aqua/30 px-2 py-0.5 font-bold text-aqua-ink">Starter pack</span>}
      {item.analysis && (
        <span className="rounded-full bg-ok/12 px-2 py-0.5 font-bold text-ok" title={`Latest analysis ${timeAgo(item.analysis.at)}${item.analysis.sampleMethod ? `: ${item.analysis.sampleMethod}` : ""}`}>
          Analyzed{item.analysis.coverage === "sample" ? ` · sample of ${item.analysis.rowsAnalyzed.toLocaleString()}` : ""}
        </span>
      )}
      {item.kind === "documentation" && <span className="inline-flex items-center gap-1 rounded-full bg-sky-deep px-2 py-0.5 font-bold text-ink-soft"><FileText size={11} />Documentation</span>}
      {item.origin === "live" && !item.analysis && (
        <span className="rounded-full bg-peri/15 px-2 py-0.5 font-bold text-peri-ink" title={item.liveHit ? `Found by a live search ${timeAgo(item.liveHit.fetched_at)}; metadata not reviewed.` : undefined}>
          Live result
        </span>
      )}
      {item.stale && <span className="rounded-full bg-bad/12 px-2 py-0.5 font-bold text-bad">Stale</span>}
    </>
  );
}

/** Lean result card: title, short description, three details, one primary action. Everything else is under Inspect. */
export default function ResultRow({ item, detailQuery, hideFit = false }: { item: DatasetSummary; detailQuery: string; hideFit?: boolean }) {
  const shortlist = useShortlist();
  const [open, setOpen] = useState<false | "inspect">(false);
  const fit = FIT_STYLE[item.fit];
  const inList = shortlist.has(item.id);
  const formats = item.formats.values.length ? item.formats.values.map((f) => label("formats", f)).join(", ") : "Format unknown";
  const reasons = [...item.reasons].sort((a, b) => Number(b.required) - Number(a.required));
  const headline = reasons.find((r) => r.required && r.outcome !== "met") ?? reasons[0];
  const href = `/datasets/${encodeURIComponent(item.id)}${detailQuery ? `?${detailQuery}` : ""}`;

  // One primary action, picked by what can actually run.
  const id = encodeURIComponent(item.id);
  const unsupported = item.unsupportedFormats?.length ? item.unsupportedFormats.join(", ") : null;
  let primary;
  let note: string | null = null;
  if (item.curated) {
    primary = (
      <Link to={`/packs/${item.curated.slug}?start=sample`} className="btn-clay px-4 py-2 text-sm" style={{ background: item.curated.accent }}>
        <Play size={15} fill="currentColor" /> Run sample
      </Link>
    );
  } else if (item.analysis) {
    primary = <Link to={`/datasets/${id}/run`} className="btn-clay bg-ok px-4 py-2 text-sm dark:!text-on-accent"><BarChart3 size={15} /> View run</Link>;
  } else if (item.runnable === "kaggle") {
    primary = <Link to={`/datasets/${id}/run`} className="btn-clay bg-peri px-4 py-2 text-sm"><Play size={15} fill="currentColor" /> Fetch and analyze</Link>;
    note = "Kaggle files are fetched with your own Kaggle account. Connect it once from the Run view or Settings.";
  } else if (item.runnable === "sign-in" || item.runnable === "unsupported" || item.runnable === "documentation") {
    primary = <a className="btn-clay bg-peri px-4 py-2 text-sm" href={item.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open source</a>;
    note = item.runnable === "sign-in" ? `${item.provider} needs a sign-in to download. Download the file there, then upload it.`
      : item.runnable === "unsupported" ? `${unsupported ?? "This format"} has no analyzer yet. Upload any file to get an inspection, or a CSV/Parquet export to analyze it.`
      : "This page documents the data but has no downloadable file.";
  } else {
    primary = <Link to={`/datasets/${id}/run?start=sample`} className="btn-clay bg-peri px-4 py-2 text-sm"><Play size={15} fill="currentColor" /> Run sample</Link>;
  }
  const canUpload = !item.curated && !item.analysis && (item.runnable === "sign-in" || item.runnable === "unsupported");

  return (
    <li className="glass rounded-3xl p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {!hideFit && <span className={`inline-flex items-center gap-1 font-bold ${fit.cls}`}>{fit.icon}{fit.label}</span>}
        <span className="font-semibold text-ink-soft">{item.provider}</span>
        <SourceBadges item={item} />
      </div>
      <h3 className="mt-1.5 font-display text-lg font-bold leading-snug">
        <Link to={href} className="hover:underline">{item.title}</Link>
      </h3>
      <p className="mt-0.5 line-clamp-2 max-w-[80ch] text-sm text-ink-soft">{item.description}</p>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-soft">
        <span className={item.coverage.temporal.status === "unknown" ? "text-warn-ink" : ""}>{item.coverage.temporal.text === "Unknown" ? "Dates unknown" : item.coverage.temporal.text}</span>
        <span>{formats}{item.access.signInRequired ? ", sign-in" : ""}</span>
        <span className={!item.license.name ? "text-warn-ink" : ""}>{item.license.name ?? "License unknown"}</span>
      </p>
      {headline && !hideFit && (
        <p className="mt-2 flex gap-2 text-sm">
          <OutcomeIcon outcome={headline.outcome} />
          <span className="text-ink-soft"><RichText text={headline.text} />{reasons.length > 1 && <span className="text-ink-faint"> (+{reasons.length - 1} more under Inspect)</span>}</span>
        </p>
      )}

      {note && <p className="mt-2 rounded-2xl bg-sun/30 px-3 py-2 text-xs text-warn-ink">{note}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {primary}
        <button className="btn-ghost" onClick={() => setOpen(open === "inspect" ? false : "inspect")} aria-expanded={open === "inspect"}>
          Inspect <ChevronDown size={14} className={open === "inspect" ? "rotate-180 transition-transform" : "transition-transform"} />
        </button>
        {canUpload && <Link className="btn-ghost" to={`/datasets/${id}/run?source=upload`}><FileUp size={15} /> Upload a file</Link>}
        {!item.analysis && !item.curated && (item.runnable ?? "sample") === "sample" && (
          <a className="btn-ghost" href={item.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open source</a>
        )}
        <button
          className={`btn-ghost ${inList ? "!bg-peri/15 !text-peri-ink" : ""}`}
          onClick={() => shortlist.toggle(item.id, item.title)}
          disabled={!inList && shortlist.full}
          aria-pressed={inList}
          title={!inList && shortlist.full ? "You can compare up to three datasets" : undefined}
        >
          {inList ? <CheckIcon size={15} /> : <Plus size={15} />} {inList ? "In comparison" : "Compare"}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 border-t border-white/80 pt-4">
          {open === "inspect" && (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
                <div><dt className="text-xs text-ink-faint">Area</dt><dd>{item.coverage.spatial.text}</dd></div>
                <div><dt className="text-xs text-ink-faint">Access</dt><dd>{label("access", item.access.class)}</dd></div>
                <div><dt className="text-xs text-ink-faint">Publisher</dt><dd className="truncate" title={item.publisher}>{item.publisher}</dd></div>
                {item.unitOfAnalysis && <div className="col-span-full"><dt className="text-xs text-ink-faint">Unit of analysis</dt><dd>{item.unitOfAnalysis}</dd></div>}
                {item.fieldNames.length > 0 && (
                  <div className="col-span-full"><dt className="text-xs text-ink-faint">Sample fields</dt>
                    <dd className="flex flex-wrap gap-1 pt-0.5">{item.fieldNames.slice(0, 10).map((f) => <code key={f} className="rounded-md bg-sky-deep/70 px-1.5 text-xs">{f}</code>)}
                      {item.fieldNames.length > 10 && <span className="text-xs text-ink-faint">+{item.fieldNames.length - 10}</span>}</dd>
                  </div>
                )}
              </dl>
              {reasons.length > 0 && (
                <ul className="space-y-1.5">
                  {reasons.map((r) => (
                    <li key={r.key} className="flex gap-2 text-sm">
                      <OutcomeIcon outcome={r.outcome} />
                      <span className={r.required ? "" : "text-ink-soft"}><RichText text={r.text} />{!r.required && <span className="ml-1 text-xs text-ink-faint">(preferred)</span>}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          <DataAccessPanel d={item} compact autoFiles={false} />
          <Link to={href} className="inline-block text-sm font-semibold text-link underline underline-offset-2">Full dataset details</Link>
        </div>
      )}
    </li>
  );
}
