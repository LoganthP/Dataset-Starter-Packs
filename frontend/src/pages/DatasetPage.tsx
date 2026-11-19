import { ArrowLeft, BarChart3, CheckCircle2, CircleDashed, ExternalLink, Loader2, Play, Plus, RefreshCw, Check as CheckIcon, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, timeAgo, useApi } from "../api";
import { EvidenceBadge, FIT_STYLE, OutcomeIcon, fmtDate, RichText } from "../components/discover/bits";
import DataAccessPanel from "../components/discover/DataAccessPanel";
import { SourceBadges } from "../components/discover/ResultRow";
import { ErrorBox, Spinner } from "../components/ui";
import { label } from "../lib/searchState";
import { useShortlist } from "../lib/shortlist";
import type { DatasetDetail, StatusTile } from "../types";

function Status({ title, question, tile, action }: { title: string; question: string; tile: StatusTile; action?: React.ReactNode }) {
  const look = {
    ok: { icon: <CheckCircle2 size={20} className="text-ok" />, word: "Yes" },
    error: { icon: <XCircle size={20} className="text-bad" />, word: "No" },
    pending: { icon: <CircleDashed size={20} className="text-warn" />, word: "Not yet" },
    unchecked: { icon: <CircleDashed size={20} className="text-ink-faint" />, word: "Not checked" },
    "not-applicable": { icon: <CircleDashed size={20} className="text-ink-faint" />, word: "No starter" },
  }[tile.state];
  return (
    <div className="glass flex flex-col rounded-3xl p-4">
      <div className="flex items-center gap-2">
        {look.icon}
        <h3 className="font-display text-base font-bold">{title}</h3>
        <span className="ml-auto text-sm font-semibold">{look.word}</span>
      </div>
      <p className="mt-1 text-xs text-ink-faint">{question}</p>
      <p className="mt-2 text-sm text-ink-soft">{tile.detail}</p>
      {tile.at && <p className="mt-1 text-xs text-ink-faint">{tile.at.length <= 10 ? fmtDate(tile.at) : timeAgo(tile.at)}</p>}
      {action && <div className="mt-auto pt-3">{action}</div>}
    </div>
  );
}

function Row({ k, children, status }: { k: string; children: React.ReactNode; status?: DatasetDetail["formats"]["status"] }) {
  return (
    <div className="grid gap-1 border-b border-white/80 py-2.5 last:border-0 sm:grid-cols-[10rem_1fr]">
      <dt className="text-sm font-semibold text-ink-soft">{k}</dt>
      <dd className="flex flex-wrap items-center gap-2 text-sm">{children}{status && <EvidenceBadge status={status} />}</dd>
    </div>
  );
}

const Note = ({ text }: { text?: string | null }) => (text ? <span className="w-full text-xs text-ink-faint">{text}</span> : null);

export default function DatasetPage() {
  const { id = "" } = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const query = sp.toString();
  const ds = useApi(() => api.dataset(id, query), [id, query]);
  const shortlist = useShortlist();
  const [checking, setChecking] = useState(false);

  if (ds.loading && !ds.data) return <div className="glass rounded-3xl p-6"><Spinner label="Loading dataset" /></div>;
  if (ds.error || !ds.data) return <ErrorBox message={ds.error ?? "Dataset not found"} action={<Link className="btn-ghost" to="/discover">Back to Discover</Link>} />;
  const d = ds.data;
  const fit = FIT_STYLE[d.fit];
  const t = d.coverage.temporal;
  const s = d.coverage.spatial;
  const inList = shortlist.has(d.id);
  const back = () => (window.history.length > 1 ? nav(-1) : nav(`/discover?${query}`));

  const check = async () => {
    setChecking(true);
    try {
      await api.checkDataset(d.id);
      await ds.reload();
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="space-y-6">
      <button onClick={back} className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-soft hover:text-ink">
        <ArrowLeft size={16} /> Back to results
      </button>

      <header className="glass-strong rounded-4xl p-6 sm:p-8">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-ink px-2.5 py-0.5 font-bold text-on-accent">{d.provider}</span>
          <SourceBadges item={d} />
          {d.origin === "import" && <span className="rounded-full bg-sun/50 px-2.5 py-0.5 font-bold text-warn-ink">Unreviewed import</span>}
          {d.purposes.map((p) => <span key={p} className="chip">{label("purpose", p)}</span>)}
        </div>
        <h1 className="mt-3 text-[clamp(1.8rem,3.6vw,2.8rem)] font-extrabold leading-[1.05] tracking-[-0.02em]">{d.title}</h1>
        <p className="mt-2 max-w-[70ch] text-lg text-ink-soft">{d.description}</p>
        <p className="mt-1 text-sm text-ink-faint">Published by {d.publisher}{d.origin === "live" ? " · found by live search, not yet reviewed" : ""}</p>
        {d.unitOfAnalysis && <p className="mt-3 max-w-[70ch] rounded-2xl bg-white/70 px-4 py-2.5 text-sm"><b>Unit of analysis:</b> {d.unitOfAnalysis}</p>}
        {d.configs && d.configs.length > 1 && <p className="mt-2 text-sm text-ink-soft">Subsets (configs): {d.configs.join(", ")}</p>}
        {d.analysis && (
          <p className="mt-3 text-sm text-ok">Fields and dates verified by analyzing <Link className="font-semibold underline" to={`/datasets/${encodeURIComponent(d.id)}/run`}>{d.analysis.file}</Link> ({fmtDate(d.analysis.at)}).</p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          {d.curated ? (
            <>
              <Link to={`/packs/${d.curated.slug}?start=sample`} className="btn-clay px-4 py-2.5" style={{ background: d.curated.accent }}>
                <Play size={16} fill="currentColor" /> Run sample
              </Link>
              <Link to={`/packs/${d.curated.slug}`} className="btn-ghost">Open starter pack</Link>
              <a className="btn-ghost" href={d.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> View source</a>
            </>
          ) : d.analysis ? (
            <>
              <Link className="btn-clay bg-ok px-4 py-2.5 dark:!text-on-accent" to={`/datasets/${encodeURIComponent(d.id)}/run`}><BarChart3 size={16} /> View run</Link>
              <a className="btn-ghost" href={d.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open source</a>
            </>
          ) : (
            <a className="btn-clay bg-ink px-4 py-2.5 !text-on-accent" href={d.canonicalUrl} target="_blank" rel="noreferrer"><ExternalLink size={16} /> Open source</a>
          )}
          <button className="btn-ghost" onClick={() => shortlist.toggle(d.id, d.title)} disabled={!inList && shortlist.full} aria-pressed={inList}>
            {inList ? <CheckIcon size={15} /> : <Plus size={15} />} {inList ? "In comparison" : "Add to comparison"}
          </button>
        </div>
      </header>

      <section aria-label="Verification status" className="grid gap-4 md:grid-cols-3">
        <Status title="Source responded" question="Is the official page reachable right now?" tile={d.statuses.sourceResponded}
          action={<button className="btn-ghost" onClick={check} disabled={checking}>{checking ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Check now</button>} />
        <Status title="Metadata reviewed" question="Has someone checked these fields, dates and terms against the source?" tile={d.statuses.metadataReviewed} />
        <Status title="Sample ran successfully" question="Does the starter pack's sample run on this machine?" tile={d.statuses.sampleRan}
          action={d.statuses.sampleRan.run_id ? <Link className="btn-ghost" to={`/runs/${d.statuses.sampleRan.run_id}`}>View run</Link>
            : d.curated ? <Link className="btn-ghost" to={`/packs/${d.curated.slug}?start=sample`}>Run sample</Link> : undefined} />
      </section>

      {d.reasons.length > 0 && (
        <section className="glass rounded-3xl p-5" aria-labelledby="fit-h">
          <h2 id="fit-h" className={`flex items-center gap-1.5 font-display text-xl font-bold ${fit.cls}`}>{fit.icon}{fit.label} for your search</h2>
          <ul className="mt-3 space-y-2">
            {d.reasons.map((r) => (
              <li key={r.key} className="flex gap-2.5 rounded-2xl bg-white/70 p-3 text-sm">
                <OutcomeIcon outcome={r.outcome} size={17} />
                <div className="min-w-0">
                  <p className="font-semibold">{r.label}{!r.required && <span className="ml-1 font-normal text-ink-faint">(preferred)</span>}</p>
                  <p className="text-ink-soft"><RichText text={r.text} /></p>
                  {r.evidence && (
                    <p className="mt-0.5 break-all text-xs text-ink-faint">Evidence: {r.evidence.startsWith("http")
                      ? <a className="underline" href={r.evidence} target="_blank" rel="noreferrer">{r.evidence}</a> : r.evidence}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <section className="glass rounded-3xl p-5" aria-labelledby="sum-h">
          <h2 id="sum-h" className="font-display text-xl font-bold">Summary</h2>
          <dl className="mt-2">
            <Row k="Observations" status={t.status}>{t.text}{t.granularity.length > 0 && <span className="text-ink-faint">· {t.granularity.join(", ")}</span>}<Note text={t.note} /></Row>
            <Row k="Area covered" status={s.status}>{s.text}<Note text={s.note} /></Row>
            <Row k="Formats" status={d.formats.status}>{d.formats.values.length ? d.formats.values.map((f) => label("formats", f)).join(", ") : "Unknown"}<Note text={d.formats.note} /></Row>
            <Row k="Access" status={d.access.status}>{label("access", d.access.class)}{d.access.signInRequired === null && <span className="text-ink-faint">· sign-in unknown</span>}<Note text={d.access.note} /></Row>
            <Row k="License" status={d.license.status}>
              {d.license.url ? <a className="underline" href={d.license.url} target="_blank" rel="noreferrer">{d.license.name ?? "Unknown"}</a> : d.license.name ?? "Unknown"}
              <span className="text-ink-faint">· {label("license", d.license.class)}</span><Note text={d.license.note} />
            </Row>
            <Row k="Size">{[d.size.rows ? `${d.size.rows.toLocaleString()} rows` : null, d.size.note].filter(Boolean).join(" · ") || "Unknown"}</Row>
          </dl>
        </section>

        <aside className="space-y-4">
          <section className="glass rounded-3xl p-5" aria-labelledby="dates-h">
            <h2 id="dates-h" className="font-display text-lg font-bold">Three different dates</h2>
            <dl className="mt-2 space-y-2 text-sm">
              <div><dt className="text-ink-faint">What the data covers</dt><dd className="font-semibold">{t.text}</dd></div>
              <div><dt className="text-ink-faint">Source last updated</dt><dd className="font-semibold">{fmtDate(d.sourceUpdatedAt)}</dd></div>
              <div><dt className="text-ink-faint">We last verified this metadata</dt><dd className="font-semibold">{fmtDate(d.lastVerifiedAt)}</dd></div>
              {d.lastFetchedAt && <div><dt className="text-ink-faint">Last refreshed from the provider</dt><dd className="font-semibold">{fmtDate(d.lastFetchedAt)}</dd></div>}
            </dl>
          </section>
          <section className="glass rounded-3xl p-5" aria-labelledby="links-h">
            <h2 id="links-h" className="font-display text-lg font-bold">Source links</h2>
            <ul className="mt-2 space-y-1.5 text-sm">
              {d.sourceLinks.map((l) => <li key={l.url}><a className="break-all text-link underline" href={l.url} target="_blank" rel="noreferrer">{l.label}</a></li>)}
            </ul>
          </section>
          {d.limitations.length > 0 && (
            <section className="glass rounded-3xl p-5" aria-labelledby="lim-h">
              <h2 id="lim-h" className="font-display text-lg font-bold">Limitations</h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-soft">{d.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </section>
          )}
        </aside>
      </div>

      {!d.curated && <DataAccessPanel d={d} autoFiles={new URLSearchParams(window.location.search).get("analyze") === "1"} />}

      <section className="glass rounded-3xl p-5" aria-labelledby="fields-h">
        <h2 id="fields-h" className="font-display text-xl font-bold">Fields and units</h2>
        <p className="mt-1 text-sm text-ink-soft">
          {d.schemaStatus === "complete" ? "The full schema is documented, so a missing field is confirmed missing."
            : d.schemaStatus === "partial" ? "Key fields only. A field missing here may still exist; check the source."
              : "No schema is indexed yet. Check the source before relying on any field."}
        </p>
        {d.fields.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-2xl bg-white/80">
            <table className="w-full min-w-[680px] text-sm">
              <thead><tr className="text-left">{["Field", "Type", "Unit", "Meaning", "Level", "Evidence"].map((h) => <th key={h} className="border-b border-sky-deep px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
              <tbody>
                {d.fields.map((f) => (
                  <tr key={f.name} className="odd:bg-sky-wash/50 align-top">
                    <td className="px-3 py-2 font-semibold">{f.name}{f.configs && f.configs.length > 0 && d.configs && d.configs.length > 1 && <span className="ml-1 text-xs font-normal text-ink-faint">({f.configs.join(", ")})</span>}{f.concepts.map((c) => <span key={c} className="ml-1.5 rounded-full bg-peri/15 px-1.5 py-0.5 text-[10px] font-bold text-peri-ink">{c}</span>)}</td>
                    <td className="px-3 py-2 text-ink-soft">{f.type ?? "?"}</td>
                    <td className="px-3 py-2 text-ink-soft">{f.unit ?? "—"}</td>
                    <td className="px-3 py-2 text-ink-soft">{f.description || "—"}</td>
                    <td className="px-3 py-2 text-ink-soft">{{ record: "Every record", input: "API input", grid: "Grid cell", derived: "Derived" }[f.level]}</td>
                    <td className="px-3 py-2"><EvidenceBadge status={f.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
