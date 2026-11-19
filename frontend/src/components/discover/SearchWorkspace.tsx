import { AnimatePresence, motion } from "framer-motion";
import { Loader2, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, searchCache } from "../../api";
import { forgetSection } from "../../lib/session";
import { FILTER_KEYS, criteriaQuery, label, list, paramsFromParsed, toggleInList, withParam } from "../../lib/searchState";
import type { DiscoverMeta, SearchResponse } from "../../types";
import { ErrorBox } from "../ui";
import CriteriaBar from "./CriteriaBar";
import FilterPanel from "./FilterPanel";
import LiveStrip from "./LiveStrip";
import { type LiveState, useLiveSearch } from "./useLiveSearch";
import SearchBar from "./SearchBar";
import { SkeletonRows } from "./bits";

const SORTS = [
  { v: "fit", t: "Best fit" },
  { v: "relevance", t: "Relevance" },
  { v: "updated", t: "Recently updated at source" },
  { v: "title", t: "Name" },
];

/** Shared search + filter shell for Discover (scope=all) and Curated Packs (scope=curated). */
export interface LiveInfo {
  enabled: boolean;
  done: boolean;
  status: LiveState;
}

export default function SearchWorkspace({ scope, header, examples, meta, placeholder, renderResults, live = false }: {
  scope: "all" | "curated";
  header: ReactNode;
  examples?: string[];
  meta: DiscoverMeta | null;
  placeholder?: string;
  renderResults: (data: SearchResponse, detailQuery: string, setSp: (n: URLSearchParams) => void, sp: URLSearchParams, live: LiveInfo) => ReactNode;
  live?: boolean;
}) {
  const [sp, setSpRaw] = useSearchParams();
  const cacheKey = `${scope}?${sp.toString()}`;
  const [data, setData] = useState<SearchResponse | null>(() => searchCache.get(cacheKey) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!searchCache.has(cacheKey));
  const [parsing, setParsing] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const reqId = useRef(0);
  const [tick, setTick] = useState(0);
  const tickTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const bump = () => {
    clearTimeout(tickTimer.current);
    tickTimer.current = setTimeout(() => setTick((t) => t + 1), 150);
  };

  const setSp = (next: URLSearchParams) => setSpRaw(next, { preventScrollReset: true });
  const queryString = sp.toString();

  useEffect(() => {
    const id = ++reqId.current;
    const q = new URLSearchParams(sp);
    q.set("scope", scope);
    q.set("include_failed", "1");
    q.set("page_size", "50");
    setLoading(true);
    api.datasets(q.toString())
      .then((res) => {
        searchCache.set(`${scope}?${queryString}`, res);
        if (id === reqId.current) {
          setData(res);
          setError(null);
        }
      })
      .catch((e: Error) => id === reqId.current && setError(e.message))
      .finally(() => id === reqId.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryString, scope, tick]);

  const topic = live && data ? data.criteria.topic : null;
  const liveSearch = useLiveSearch(sp.get("q") ?? "", topic, live ? meta?.liveProviders : undefined, bump);
  const liveInfo: LiveInfo = { enabled: live && !!meta?.liveProviders?.length, done: liveSearch.done, status: liveSearch.status };


  const submit = async (q: string) => {
    setParsing(true);
    try {
      const parsed = q ? await api.parse(q) : null;
      setSp(parsed ? paramsFromParsed(q, parsed, sp) : new URLSearchParams(sp.get("sort") ? { sort: sp.get("sort")! } : {}));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setParsing(false);
    }
  };

  const activeFilters = useMemo(() => {
    const out: { key: string; value: string; text: string }[] = [];
    for (const k of FILTER_KEYS) {
      if (k === "max_minutes" || k === "max_mb") {
        const v = sp.get(k);
        if (v) out.push({ key: k, value: v, text: k === "max_minutes" ? `≤ ${v} minutes` : `≤ ${v} MB` });
      } else for (const v of list(sp, k)) out.push({ key: k, value: v, text: label(k, v) });
    }
    return out;
  }, [sp]);
  const filterCount = activeFilters.length + (data ? data.criteria.fields.length : 0);
  const detailQuery = criteriaQuery(sp).toString();
  const concepts = meta?.concepts ?? {};
  const regions = meta?.regions ?? {};

  const panel = data && (
    <FilterPanel facets={data.facets} criteria={data.criteria} sp={sp} setSp={setSp} concepts={concepts} regions={regions}
      variant={scope === "curated" ? "curated" : "discover"} />
  );

  return (
    <div className="space-y-5">
      {header}
      <SearchBar value={sp.get("q") ?? ""} onSubmit={submit} examples={examples} busy={parsing} placeholder={placeholder} />
      {[...sp.keys()].length > 0 && (
        <div className="-mt-2 flex justify-end">
          <button className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-ink-soft hover:bg-white"
            onClick={() => { forgetSection(scope === "curated" ? "packs" : "discover"); setSp(new URLSearchParams()); }}
            title="Clear the query, requirements and filters. Your comparison queue is kept.">
            <RotateCcw size={14} /> Clear search
          </button>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="hidden lg:block" aria-label="Filters">
          <div className="glass sticky top-[84px] max-h-[calc(100vh-100px)] overflow-y-auto rounded-3xl p-4">
            {panel ?? <div className="h-96 animate-pulse rounded-2xl bg-white/60" />}
          </div>
        </aside>

        <section aria-label="Results" className="min-w-0 space-y-4">
          <div className="glass rounded-3xl p-4">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="font-display text-lg font-bold">Your requirements</h2>
              <button className="btn-ghost lg:hidden" onClick={() => setDrawer(true)}>
                <SlidersHorizontal size={15} /> Filters{filterCount ? ` (${filterCount})` : ""}
              </button>
              <label className="ml-auto flex items-center gap-2 text-sm">
                <span className="text-ink-soft">Sort</span>
                <select className="field w-auto py-1.5" value={sp.get("sort") ?? "fit"} onChange={(e) => setSp(withParam(sp, "sort", e.target.value === "fit" ? null : e.target.value))}>
                  {SORTS.map((s) => <option key={s.v} value={s.v}>{s.t}</option>)}
                </select>
              </label>
            </div>
            <div className="mt-3">
              {data && <CriteriaBar criteria={data.criteria} sp={sp} setSp={setSp} concepts={concepts} regions={regions} />}
            </div>
            {activeFilters.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/80 pt-3">
                <span className="text-sm text-ink-soft">Filters</span>
                {activeFilters.map((f) => (
                  <button key={`${f.key}:${f.value}`} className="chip gap-1 !py-1 hover:bg-white"
                    onClick={() => setSp(f.key === "max_minutes" || f.key === "max_mb" ? withParam(sp, f.key, null) : toggleInList(sp, f.key, f.value))}
                    aria-label={`Remove filter ${f.text}`}>
                    {f.text} <X size={12} />
                  </button>
                ))}
                <button className="text-sm font-semibold text-link underline underline-offset-2"
                  onClick={() => { let n = new URLSearchParams(sp); for (const k of FILTER_KEYS) n = withParam(n, k, null); setSp(n); }}>
                  Clear filters
                </button>
              </div>
            )}
          </div>

          {data && (data.criteria.fields.length > 0 || data.criteria.min_years || data.criteria.formats.length > 0 || data.criteria.region || data.criteria.granularity || data.criteria.commercial || data.criteria.period_from || data.criteria.period_to) && (
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-sm" aria-live="polite">
              <span><b className="text-ok">{data.counts.meets}</b> meet requirements</span>
              <span><b className="text-warn">{data.counts["needs-verification"]}</b> need verification</span>
              <span className="text-ink-soft"><b>{data.counts["does-not-meet"]}</b> don't meet</span>
              {loading && <Loader2 size={15} className="animate-spin text-ink-faint" aria-label="Updating" />}
            </p>
          )}

          {live && meta?.liveProviders && (
            <LiveStrip providers={meta.liveProviders} status={liveSearch.status} done={liveSearch.done} refreshing={liveSearch.refreshing} onRerun={liveSearch.rerun} />
          )}
          {error && (
            <ErrorBox message={`The search request failed: ${error}`}
              action={<button className="btn-ghost" onClick={() => setTick((t) => t + 1)}>Try again</button>} />
          )}
          {!data && loading && !error && <SkeletonRows />}
          {data && !error && <div className={loading ? "opacity-70 transition-opacity" : "transition-opacity"}>{renderResults(data, detailQuery, setSp, sp, liveInfo)}</div>}
        </section>
      </div>

      <AnimatePresence>
        {drawer && panel && (
          <motion.div className="fixed inset-0 z-50 flex justify-end bg-ink/25 backdrop-blur-sm lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setDrawer(false)} role="dialog" aria-modal="true" aria-label="Filters">
            <motion.div initial={{ x: 40 }} animate={{ x: 0 }} exit={{ x: 40 }} transition={{ type: "spring", stiffness: 320, damping: 30 }}
              className="glass-strong flex h-full w-[min(92vw,380px)] flex-col rounded-l-3xl" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between border-b border-white p-4">
                <h2 className="font-display text-lg font-bold">Filters</h2>
                <button className="btn-ghost" onClick={() => setDrawer(false)} autoFocus><X size={15} /> Close</button>
              </div>
              <div className="flex-1 overflow-y-auto px-4">{panel}</div>
              <div className="border-t border-white p-4">
                <button className="btn-clay w-full bg-peri" onClick={() => setDrawer(false)}>
                  Show {data ? data.counts.meets + data.counts["needs-verification"] : ""} results
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
