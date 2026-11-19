import { Link } from "react-router-dom";
import { timeAgo, useDiscoverMeta } from "../api";
import { FIT_STYLE } from "../components/discover/bits";
import { criteriaKeys, removeCriterion } from "../components/discover/CriteriaBar";
import ResultRow from "../components/discover/ResultRow";
import SearchWorkspace, { type LiveInfo } from "../components/discover/SearchWorkspace";
import { SkeletonRows } from "../components/discover/bits";
import { toggleInList } from "../lib/searchState";
import type { DatasetSummary, DiscoverMeta, Fit, SearchResponse } from "../types";

function Header({ meta }: { meta: DiscoverMeta | null }) {
  const failing = meta?.imports.sources.filter((s) => s.status === "error") ?? [];
  return (
    <header className="pt-2">
      <h1 className="font-display text-[clamp(2rem,4.2vw,3.2rem)] font-extrabold leading-[1.02] tracking-[-0.025em]">Find data for your project</h1>
      <p className="mt-2 max-w-[68ch] text-ink-soft">
        Describe what you're building; we check each dataset against your requirements and show what's confirmed. <Link to="/sources" className="font-semibold text-link underline underline-offset-2">Sources</Link>
      </p>
      {meta && meta.total === 0 && (
        <div role="status" className="mt-3 rounded-2xl bg-bad/10 px-4 py-3 text-sm text-ink">
          <p className="font-semibold">The local catalog on this machine is empty, so only live sources are searched.</p>
          <ul className="mt-1 list-disc pl-5 text-ink-soft">
            {(meta.catalogHealth.errors?.length ? meta.catalogHealth.errors.slice(0, 3) : ["No catalog records or packs were found when the API started."]).map((e) => <li key={e}>{e}</li>)}
          </ul>
          <p className="mt-1 text-ink-soft">Looked in <code>{meta.catalogHealth.recordsDir}</code> and <code>{meta.catalogHealth.packsDir}</code>. Restart the API after fixing.</p>
        </div>
      )}
      {failing.length > 0 && (
        <p role="status" className="mt-3 rounded-2xl bg-sun/40 px-4 py-2.5 text-sm text-warn-ink">
          {failing.map((s) => s.label).join(", ")} couldn't be refreshed
          {failing[0].last_attempt_at ? ` (last attempt ${timeAgo(failing[0].last_attempt_at)})` : ""}. Earlier results are still shown.{" "}
          <Link to="/sources" className="font-semibold underline">Source status</Link>
        </p>
      )}
    </header>
  );
}

function Section({ fit, items, detailQuery, children }: { fit: Fit; items: DatasetSummary[]; detailQuery: string; children?: React.ReactNode }) {
  const s = FIT_STYLE[fit];
  return (
    <section aria-labelledby={`sec-${fit}`} className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 px-1">
        <h2 id={`sec-${fit}`} className={`flex items-center gap-1.5 font-display text-xl font-bold ${s.cls}`}>{s.icon}{s.label}</h2>
        <span className="text-sm text-ink-soft">{items.length} · {s.hint}</span>
      </div>
      {children}
      <ul className="space-y-3">{items.map((it) => <ResultRow key={it.id} item={it} detailQuery={detailQuery} />)}</ul>
    </section>
  );
}

export function renderGroupedResults(data: SearchResponse, detailQuery: string, setSp: (n: URLSearchParams) => void, sp: URLSearchParams, live?: LiveInfo) {
  const by = (f: Fit) => data.items.filter((i) => i.fit === f);
  const meets = by("meets");
  const needs = by("needs-verification");
  const fails = by("does-not-meet");
  const unverifiedKeys = [...new Map(needs.flatMap((i) => i.reasons).filter((r) => r.required && r.outcome === "unverified").map((r) => [r.key, r.label])).entries()];

  if (!data.items.length && live?.enabled && !live.done) {
    return (
      <div className="space-y-3">
        <p className="px-1 text-sm text-ink-soft">Nothing in the local catalog yet. Waiting for live sources…</p>
        <SkeletonRows n={3} />
      </div>
    );
  }
  if (!data.items.length) {
    const answered = live ? Object.values(live.status).filter((s) => s.result && ["ok", "cached"].includes(s.result.status)).length : 0;
    const total = live ? Object.values(live.status).filter((s) => s.result?.status !== "not-configured").length : 0;
    return (
      <div className="glass rounded-3xl p-8 text-center">
        <p className="font-display text-2xl font-bold">Nothing matches that search</p>
        <p className="mx-auto mt-2 max-w-[52ch] text-ink-soft">
          {data.counts.candidates === 0
            ? live?.enabled
              ? `The local catalog and ${answered} of ${total} live sources answered, and none had a dataset for this topic. Try different words, or check Sources if a provider failed.`
              : "No indexed dataset mentions those words. Try a broader topic."
            : "Datasets mention your topic, but the filters rule them all out. Clear a filter or remove a requirement."}
        </p>
      </div>
    );
  }
  if (!criteriaKeys(data.criteria).length) {
    return (
      <section aria-labelledby="sec-all" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 px-1">
          <h2 id="sec-all" className="font-display text-xl font-bold">{data.criteria.topic ? "Matching datasets" : "All datasets"}</h2>
          <span className="text-sm text-ink-soft">{data.items.length} · Add required fields, coverage or format to sort them by fit.</span>
        </div>
        <ul className="space-y-3">{data.items.map((it) => <ResultRow key={it.id} item={it} detailQuery={detailQuery} hideFit />)}</ul>
      </section>
    );
  }
  return (
    <div className="space-y-8">
      {meets.length > 0 && <Section fit="meets" items={meets} detailQuery={detailQuery} />}
      {needs.length > 0 && (
        <Section fit="needs-verification" items={needs} detailQuery={detailQuery}>
          {unverifiedKeys.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-sun/30 px-4 py-3 text-sm">
              <span className="text-warn-ink">These are unconfirmed, not ruled out. To broaden results:</span>
              {unverifiedKeys.map(([key, text]) => (
                <span key={key} className="inline-flex gap-1">
                  <button className="btn-ghost !py-1" onClick={() => setSp(toggleInList(sp, "soft", key))}>Make “{text}” preferred</button>
                  <button className="btn-ghost !py-1" onClick={() => setSp(removeCriterion(sp, key))}>Remove it</button>
                </span>
              ))}
            </div>
          )}
        </Section>
      )}
      {meets.length === 0 && needs.length === 0 && (
        <div className="glass rounded-3xl p-6 text-ink-soft">
          No dataset meets every required criterion. Look below for the reasons, then make a requirement preferred or remove it.
        </div>
      )}
      {fails.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer select-none px-1 font-display text-lg font-bold text-ink-soft">
            {fails.length} dataset{fails.length > 1 ? "s" : ""} {fails.length > 1 ? "don't" : "doesn't"} meet a requirement. Show why
          </summary>
          <ul className="mt-3 space-y-3 opacity-90">{fails.map((it) => <ResultRow key={it.id} item={it} detailQuery={detailQuery} />)}</ul>
        </details>
      )}
    </div>
  );
}

export default function Discover() {
  const meta = useDiscoverMeta();
  return (
    <SearchWorkspace
      scope="all"
      meta={meta}
      header={<Header meta={meta} />}
      examples={meta?.examples}
      live
      renderResults={(data, dq, setSp, sp, live) => renderGroupedResults(data, dq, setSp, sp, live)}
    />
  );
}
