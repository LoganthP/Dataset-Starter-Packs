import { motion } from "framer-motion";
import { ArrowLeft, BookOpen, Download, ExternalLink, GitBranch } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, timeAgo, useApi } from "../api";
import RunPanel from "../components/RunPanel";
import { ErrorBox, Markdown, PROVIDER_TINT, Spinner, StatusPill } from "../components/ui";
import type { PackDetail } from "../types";

const TABS = ["Run", "Guide", "Data dictionary", "Dataset card", "Challenges", "History"] as const;
type Tab = (typeof TABS)[number];

function DatasetCard({ pack }: { pack: PackDetail }) {
  const s = pack.source;
  const rows: [string, React.ReactNode][] = [
    ["Dataset", s.name],
    ["Publisher", s.publisher],
    ["Official source", <a className="text-link underline" href={s.dataset_page} target="_blank" rel="noreferrer">{s.dataset_page}</a>],
    ["Access", { "direct-download": "Direct download, no account", api: "Public API, no key", kaggle: "Kaggle download, free sign-in" }[s.access_method]],
    ["License or terms", <a className="text-link underline" href={s.license_url} target="_blank" rel="noreferrer">{s.license}</a>],
    ["DOI", s.doi ? <a className="text-link underline" href={`https://doi.org/${s.doi}`} target="_blank" rel="noreferrer">{s.doi}</a> : "None published"],
    ["Files used", s.files.join(", ")],
    ["Source last checked", pack.last_source_check],
  ];
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
      <div className="glass rounded-3xl p-5">
        <dl className="divide-y divide-white">
          {rows.map(([k, v]) => (
            <div key={k} className="grid gap-1 py-3 sm:grid-cols-[11rem_1fr]">
              <dt className="text-sm font-semibold text-ink-soft">{k}</dt>
              <dd className="break-words text-sm">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="space-y-4">
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Cite it like this</h3>
          <p className="mt-2 rounded-2xl bg-white/80 p-3 text-sm">{s.citation}</p>
          <button className="btn-ghost mt-3" onClick={() => navigator.clipboard?.writeText(s.citation)}>Copy citation</button>
        </div>
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Cached real data</h3>
          {pack.data_status.provenance.length ? (
            <pre className="mt-2 max-h-64 overflow-auto rounded-2xl bg-white/80 p-3 text-xs">{JSON.stringify(pack.data_status.provenance, null, 2)}</pre>
          ) : (
            <p className="mt-2 text-sm text-ink-soft">Nothing downloaded yet. A real-data run saves the source URL, retrieval date and checksum here.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function History({ slug }: { slug: string }) {
  const runs = useApi(() => api.runs(slug), [slug]);
  if (runs.loading) return <Spinner />;
  if (runs.error) return <ErrorBox message={runs.error} />;
  if (!runs.data?.length) return <p className="glass rounded-3xl p-6 text-ink-soft">No runs yet for this pack. Start one from the Run tab.</p>;
  return (
    <ul className="space-y-2">
      {runs.data.map((r) => (
        <li key={r.id}>
          <Link to={`/runs/${r.id}`} className="glass flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3 hover:bg-white/80">
            <StatusPill status={r.status} />
            <span className="text-sm font-semibold">{r.mode === "real" ? "Real data" : "Sample"}</span>
            <span className="min-w-0 flex-1 truncate text-sm text-ink-soft">{r.headline ?? r.error ?? ""}</span>
            <span className="text-xs text-ink-faint">{timeAgo(r.created_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function PackPage() {
  const { slug = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const pack = useApi(() => api.pack(slug), [slug]);
  const [tab, setTab] = useState<Tab>("Run");
  const datasetId = useApi(() => api.datasets(`scope=curated&page_size=50`), []).data?.items.find((i) => i.packId === slug)?.id;

  if (pack.loading) return <div className="glass rounded-3xl p-6"><Spinner label="Loading pack" /></div>;
  if (pack.error || !pack.data)
    return <ErrorBox message={pack.error ?? "Pack not found"} action={<Link className="btn-ghost" to="/packs">Back to all packs</Link>} />;
  const p = pack.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <Link to="/packs" className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-soft hover:text-ink">
          <ArrowLeft size={16} /> Curated packs
        </Link>
        {datasetId && <Link to={`/datasets/${encodeURIComponent(datasetId)}`} className="text-sm font-semibold text-link underline underline-offset-2">Dataset details and verification</Link>}
      </div>

      <motion.header
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 200, damping: 22 }}
        className="grid gap-5 lg:grid-cols-[1fr_360px]"
      >
        <div className="glass-strong relative overflow-hidden rounded-4xl p-6 sm:p-8">
          <span className="absolute inset-y-0 left-0 w-2" style={{ background: p.accent }} aria-hidden />
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full px-2.5 py-0.5 text-xs font-bold text-paper" style={{ background: PROVIDER_TINT[p.provider] ?? p.accent }}>{p.provider}</span>
            <span className="chip capitalize">{p.difficulty}</span>
            <span className="chip">{p.task_type}</span>
            <span className="chip">{p.estimated_time}</span>
          </div>
          <h1 className="mt-4 text-[clamp(2rem,4.4vw,3.4rem)] font-extrabold leading-[1] tracking-[-0.025em]">{p.title}</h1>
          <p className="mt-4 max-w-[60ch] font-display text-xl font-medium leading-snug text-ink-soft sm:text-2xl">{p.question}</p>
          <div className="mt-5 flex flex-wrap gap-1.5">
            {p.skills.map((s) => <span key={s} className="chip">{s}</span>)}
          </div>
          <div className="mt-6 flex flex-wrap gap-2">
            <a className="btn-ghost" href={api.url(`/api/packs/${p.slug}/starter.zip`)}><Download size={15} /> Download starter</a>
            <a className="btn-ghost" href={api.url(`/api/packs/${p.slug}/notebook`)}><BookOpen size={15} /> Notebook (.ipynb)</a>
            <a className="btn-ghost" href={p.source.dataset_page} target="_blank" rel="noreferrer"><ExternalLink size={15} /> View dataset</a>
            {p.github_url && <a className="btn-ghost" href={p.github_url} target="_blank" rel="noreferrer"><GitBranch size={15} /> Open on GitHub</a>}
          </div>
        </div>

        <aside className="flex flex-col rounded-4xl p-6 shadow-clay" style={{ background: "var(--sun-panel)" }}>
          <h2 className="text-sm font-bold text-warn-ink">The trap in this dataset</h2>
          <p className="mt-2 font-display text-2xl font-extrabold leading-tight text-warn-ink">{p.lesson.title}</p>
          <p className="mt-3 text-[15px] leading-relaxed text-warn-ink">{p.lesson.summary}</p>
          <p className="mt-auto pt-4 text-sm text-warn-ink">Each run checks for it and shows pass or fail.</p>
        </aside>
      </motion.header>

      <div className="glass-strong sticky top-[76px] z-20 flex gap-1 overflow-x-auto rounded-2xl p-1.5" role="tablist" aria-label="Pack sections">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className="relative whitespace-nowrap rounded-xl px-4 py-2 text-sm font-semibold"
          >
            {tab === t && <motion.span layoutId="tab-pill" className="absolute inset-0 -z-0 rounded-xl bg-white shadow-neu" transition={{ type: "spring", stiffness: 380, damping: 32 }} />}
            <span className={`relative ${tab === t ? "text-ink" : "text-ink-soft"}`}>{t}</span>
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={tab}>
        {/* RunPanel stays mounted so a running job keeps streaming while you read other tabs */}
        <div hidden={tab !== "Run"}>
          <RunPanel
            pack={p}
            initialRunId={search.get("run")}
            autoStart={search.get("start") === "sample"}
            onRunChange={(id) => setSearch({ run: id }, { replace: true })}
          />
        </div>
        {tab === "Guide" && <div className="glass-strong rounded-3xl p-6 sm:p-8"><Markdown slug={p.slug}>{p.documents.readme}</Markdown></div>}
        {tab === "Data dictionary" && <div className="glass-strong rounded-3xl p-6 sm:p-8"><Markdown slug={p.slug}>{p.documents.data_dictionary}</Markdown></div>}
        {tab === "Dataset card" && <DatasetCard pack={p} />}
        {tab === "Challenges" && (
          <ol className="grid gap-4 md:grid-cols-3">
            {p.challenges.map((c, i) => (
              <li key={c.title} className="glass flex flex-col rounded-3xl p-5">
                <span className="font-display text-3xl font-extrabold" style={{ color: p.accent }}>{i + 1}</span>
                <h3 className="mt-1 text-xl font-bold">{c.title}</h3>
                <p className="mt-2 text-sm text-ink-soft">{c.description}</p>
                <p className="mt-auto rounded-2xl bg-white/75 p-3 pt-3 text-sm"><span className="font-semibold">Done when: </span>{c.outcome}</p>
              </li>
            ))}
          </ol>
        )}
        {tab === "History" && <History slug={p.slug} />}
      </div>
    </div>
  );
}
