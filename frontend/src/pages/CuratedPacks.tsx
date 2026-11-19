import { motion } from "framer-motion";
import { Check as CheckIcon, Download, ExternalLink, Play, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { api, useDiscoverMeta } from "../api";
import { FIT_STYLE, OutcomeIcon, RichText } from "../components/discover/bits";
import { PROVIDER_TINT } from "../components/ui";
import SearchWorkspace from "../components/discover/SearchWorkspace";
import { Spark } from "../components/insights/Charts";
import { useShortlist } from "../lib/shortlist";
import type { DatasetSummary, SearchResponse } from "../types";

const STEPS = [
  ["Pick a pack", "Each one answers a single question with one dataset."],
  ["Run the sample", "Synthetic data with the real schema - works offline in seconds."],
  ["Switch to real data", "The pack downloads or queries the official source and records where it came from."],
  ["Read the trap", "Every pack has a check for its classic mistake, shown as pass or fail."],
  ["Beat the baseline", "Download the starter, open the notebook, take on a challenge."],
];

function PackCard({ item, index, detailQuery }: { item: DatasetSummary; index: number; detailQuery: string }) {
  const cur = item.curated!;
  const fit = FIT_STYLE[item.fit];
  const tint = PROVIDER_TINT[item.provider] ?? cur.accent;
  return (
    <motion.article
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 220, damping: 22, delay: 0.05 * index }}
      className={`glass relative flex flex-col overflow-hidden rounded-4xl p-5 ${item.fit === "does-not-meet" ? "opacity-60" : ""}`}
    >
      <span className="absolute inset-x-0 top-0 h-1.5" style={{ background: cur.accent }} aria-hidden />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full px-2.5 py-0.5 font-bold text-paper" style={{ background: tint }}>{item.provider}</span>
        <span className="rounded-full bg-aqua/30 px-2.5 py-0.5 font-bold text-aqua-ink">Starter pack</span>
        {item.analysis && <Link to={`/datasets/${encodeURIComponent(item.id)}/run`} className="rounded-full bg-ok/12 px-2.5 py-0.5 font-bold text-ok hover:underline">Analyzed</Link>}
        <span className="chip capitalize">{cur.difficulty}</span>
        {cur.estimatedMinutes && <span className="chip">{cur.estimatedMinutes} min</span>}
        {cur.offlineSample && <span className="chip">Offline sample</span>}
      </div>
      <h2 className="mt-3 text-2xl font-bold leading-tight">
        <Link to={`/packs/${cur.slug}`} className="hover:underline">{cur.title}</Link>
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{item.description}</p>
      <p className="mt-2 text-sm"><span className="font-semibold">Trap: </span><span className="text-ink-soft">{cur.lesson}</span></p>
      {cur.hasPreview && (
        <div className="mt-3 overflow-hidden rounded-2xl border border-white bg-paper">
          <img src={api.url(`/api/packs/${cur.slug}/assets/preview.png`)} alt={`Example output of ${cur.title} (synthetic sample)`} className="h-40 w-full object-contain" loading="lazy" />
        </div>
      )}
      {item.reasons.length > 0 && (
        <div className="mt-3 rounded-2xl bg-white/60 p-3 text-sm">
          <p className={`flex items-center gap-1 font-bold ${fit.cls}`}>{fit.icon}{fit.label}</p>
          <ul className="mt-1.5 space-y-1">
            {item.reasons.map((r) => <li key={r.key} className="flex gap-2"><OutcomeIcon outcome={r.outcome} /><span className="text-ink-soft"><RichText text={r.text} /></span></li>)}
          </ul>
        </div>
      )}
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        <Link to={`/packs/${cur.slug}?start=sample`} className="btn-clay px-4 py-2 text-sm" style={{ background: cur.accent }}>
          <Play size={15} fill="currentColor" /> Run sample
        </Link>
        <a className="btn-ghost" href={api.url(`/api/packs/${cur.slug}/starter.zip`)}><Download size={15} /> Starter</a>
        <Link className="btn-ghost" to={`/datasets/${encodeURIComponent(item.id)}${detailQuery ? `?${detailQuery}` : ""}`}>Dataset details</Link>
        <a className="btn-ghost" href={item.canonicalUrl} target="_blank" rel="noreferrer" aria-label={`View source for ${cur.title}`}><ExternalLink size={15} /></a>
      </div>
    </motion.article>
  );
}

/** A dataset that joined Curated Packs by being analyzed. Its preview is drawn from the latest successful run's saved chart data. */
function AnalyzedCard({ item, index, detailQuery }: { item: DatasetSummary; index: number; detailQuery: string }) {
  const a = item.analysis!;
  const shortlist = useShortlist();
  const inList = shortlist.has(item.id);
  const runHref = `/datasets/${encodeURIComponent(item.id)}/run`;
  return (
    <motion.article initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ type: "spring", stiffness: 220, damping: 22, delay: 0.05 * index }}
      className="glass relative flex flex-col overflow-hidden rounded-4xl p-5">
      <span className="absolute inset-x-0 top-0 h-1.5 bg-peri" aria-hidden />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full bg-ink px-2.5 py-0.5 font-bold text-on-accent">{item.provider}</span>
        <span className="rounded-full bg-ok/12 px-2.5 py-0.5 font-bold text-ok">Analyzed</span>
        <span className="rounded-full bg-sun/40 px-2.5 py-0.5 font-bold text-warn-ink" title={a.sampleMethod ?? undefined}>
          {a.kind === "inspection" ? "Inspection only" : `${a.scope ?? (a.coverage === "full" ? "Full dataset" : "Sample")} · ${a.rowsAnalyzed.toLocaleString()} ${a.kind === "images" ? "images" : a.kind === "sinex" ? "station solutions" : "rows"}`}
        </span>
      </div>
      <h2 className="mt-3 text-2xl font-bold leading-tight"><Link to={runHref} className="hover:underline">{item.title}</Link></h2>
      <p className="mt-1 line-clamp-2 text-sm text-ink-soft">{item.description}</p>
      <div className="mt-3 h-40 overflow-hidden rounded-2xl border border-white bg-white/60">
        {a.preview && a.preview.values.length > 1 ? (
          <figure className="flex h-full flex-col p-3">
            <div className="min-h-0 flex-1"><Spark values={a.preview.values} label={a.preview.label} kind={a.preview.kind} /></div>
            <figcaption className="mt-1 text-[11px] font-semibold text-ink-soft">{a.preview.label} · from the saved run</figcaption>
          </figure>
        ) : (
          <div className="flex h-full items-center justify-center p-4 text-center text-sm text-ink-faint">The saved run has no charts. Open it to see the schema and checks.</div>
        )}
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 rounded-2xl bg-white/60 p-3 text-sm">
        <div><dt className="text-xs text-ink-faint">{a.kind === "images" ? (a.coverage === "full" ? "Images" : "Images sampled") : a.kind === "sinex" ? "Solutions" : a.coverage === "full" ? "Rows" : "Rows sampled"}</dt><dd className="font-semibold tabular-nums">{a.rowsAnalyzed.toLocaleString()}</dd></div>
        <div><dt className="text-xs text-ink-faint">Columns</dt><dd className="font-semibold tabular-nums">{a.columns}</dd></div>
        <div><dt className="text-xs text-ink-faint">Missing cells</dt><dd className="font-semibold tabular-nums">{a.missingPct}%</dd></div>
      </dl>
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        <Link to={runHref} className="btn-clay bg-peri px-4 py-2 text-sm"><Play size={15} fill="currentColor" /> View run</Link>
        <button className={`btn-ghost ${inList ? "!bg-peri/15 !text-peri-ink" : ""}`} onClick={() => shortlist.toggle(item.id, item.title)} disabled={!inList && shortlist.full} aria-pressed={inList}>
          {inList ? <CheckIcon size={15} /> : <Plus size={15} />} {inList ? "In comparison" : "Compare"}
        </button>
        <Link className="btn-ghost" to={`/datasets/${encodeURIComponent(item.id)}${detailQuery ? `?${detailQuery}` : ""}`}>Dataset details</Link>
        <a className="btn-ghost" href={item.canonicalUrl} target="_blank" rel="noreferrer" aria-label={`Open source for ${item.title}`}><ExternalLink size={15} /></a>
      </div>
    </motion.article>
  );
}

function results(data: SearchResponse, detailQuery: string) {
  if (!data.items.length) {
    return <div className="glass rounded-3xl p-8 text-center text-ink-soft">Nothing here matches. Clear a filter, or find and analyze a dataset on <Link to="/discover" className="font-semibold underline">Discover</Link>.</div>;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {data.items.map((it, i) => (it.curated
        ? <PackCard key={it.id} item={it} index={i} detailQuery={detailQuery} />
        : <AnalyzedCard key={it.id} item={it} index={i} detailQuery={detailQuery} />))}
    </div>
  );
}

export default function CuratedPacks() {
  const meta = useDiscoverMeta();
  return (
    <div className="space-y-14">
      <SearchWorkspace
        scope="curated"
        meta={meta}
        placeholder="Search starter packs and analyzed datasets"
        examples={["Beginner forecasting project with an offline sample", "SQL analytics practice", "classification under an hour"]}
        header={
          <header className="pt-2">
            <h1 className="font-display text-[clamp(2rem,4.2vw,3.2rem)] font-extrabold leading-[1.02] tracking-[-0.025em]">Curated packs</h1>
            <p className="mt-2 max-w-[66ch] text-ink-soft">
              Runnable starter packs, plus every dataset you've analyzed.
            </p>
          </header>
        }
        renderResults={(data, dq) => results(data, dq)}
      />
      <section aria-labelledby="how">
        <h2 id="how" className="text-3xl font-bold">How a pack works</h2>
        <ol className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="glass rounded-3xl p-5">
              <span className="font-display text-3xl font-extrabold text-peri">{i + 1}</span>
              <h3 className="mt-1 text-lg font-bold">{title}</h3>
              <p className="mt-1 text-sm text-ink-soft">{body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
