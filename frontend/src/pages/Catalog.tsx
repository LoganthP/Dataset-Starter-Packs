import { motion } from "framer-motion";
import { Download, Play, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, timeAgo, useApi } from "../api";
import { ErrorBox, PROVIDER_TINT, Spinner, StatusPill } from "../components/ui";
import type { Pack, Stats } from "../types";

// Bento placement per pack: the tray is the catalog, so sizes encode emphasis (bike = flagship).
const PLACEMENT: Record<string, { span: string; wide: boolean; order: number }> = {
  "uci-bike-demand": { span: "lg:col-span-2", wide: true, order: 1 },
  "nasa-bengaluru-weather": { span: "", wide: false, order: 2 },
  "nasa-exoplanets": { span: "", wide: false, order: 3 },
  "uci-dry-bean": { span: "", wide: false, order: 4 },
  "kaggle-olist-delivery": { span: "lg:col-span-2", wide: true, order: 5 },
};
const INCLUDES = ["Starter notebook", "Data dictionary", "Offline sample data", "Real-data loader", "Baseline result", "Trap check", "Extension challenges"];

const tile = {
  hidden: { opacity: 0, y: 18, scale: 0.97 },
  show: (i: number) => ({ opacity: 1, y: 0, scale: 1, transition: { type: "spring" as const, stiffness: 220, damping: 22, delay: 0.06 * i } }),
};

function PackTile({ pack, index, dimmed }: { pack: Pack; index: number; dimmed: boolean }) {
  const nav = useNavigate();
  const place = PLACEMENT[pack.slug] ?? { span: "", wide: false, order: 99 };
  const tint = PROVIDER_TINT[pack.provider] ?? pack.accent;
  return (
    <motion.article
      custom={index + 1}
      variants={tile}
      initial="hidden"
      animate="show"
      whileHover={dimmed ? undefined : { y: -4 }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
      className={`glass group relative flex min-h-[290px] flex-col overflow-hidden rounded-4xl p-5 transition-[opacity,filter,box-shadow] duration-300 hover:shadow-lift ${place.span} ${
        dimmed ? "pointer-events-none opacity-35 grayscale" : ""
      }`}
      aria-hidden={dimmed || undefined}
    >
      <span className="absolute inset-x-0 top-0 h-1.5" style={{ background: pack.accent }} aria-hidden />
      <div className="flex items-center gap-2">
        <span className="rounded-full px-2.5 py-0.5 text-xs font-bold text-white" style={{ background: tint }}>
          {pack.provider}
        </span>
        <span className="chip capitalize">{pack.difficulty}</span>
        {place.wide && <span className="chip hidden whitespace-nowrap sm:inline-flex">{pack.task_type}</span>}
      </div>

      <div className={`mt-4 flex flex-1 gap-5 ${place.wide ? "flex-col sm:flex-row" : "flex-col"}`}>
        <div className={place.wide ? "sm:w-[46%]" : ""}>
          <h2 className="text-2xl font-bold leading-tight">
            <Link to={`/packs/${pack.slug}`} className="after:absolute after:inset-0 after:content-[''] focus-visible:outline-none">
              {pack.title}
            </Link>
          </h2>
          <p className="mt-2 text-[15px] leading-snug text-ink-soft">{pack.tagline}</p>
          <p className="mt-3 text-sm">
            <span className="font-semibold">Trap: </span>
            <span className="text-ink-soft">{pack.lesson.title}</span>
          </p>
        </div>
        {pack.has_preview && (
          <div className={`relative overflow-hidden rounded-2xl border border-white bg-white ${place.wide ? "self-center sm:flex-1" : "h-28"}`}>
            <img
              src={api.url(`/api/packs/${pack.slug}/assets/preview.png`)}
              alt={`Example output of ${pack.title}`}
              className={place.wide ? "h-auto w-full" : "h-full w-full object-cover object-top"}
              loading="lazy"
            />
          </div>
        )}
      </div>

      <div className="relative z-10 mt-4 flex flex-wrap items-center gap-2">
        <button
          className="btn-clay px-4 py-2 text-sm"
          style={{ background: pack.accent }}
          onClick={() => nav(`/packs/${pack.slug}?start=sample`)}
        >
          <Play size={15} fill="currentColor" /> Run sample
        </button>
        <a className="btn-ghost" href={api.url(`/api/packs/${pack.slug}/starter.zip`)}>
          <Download size={15} /> Starter
        </a>
        <span className="ml-auto text-xs text-ink-faint">
          {pack.latest_run ? (
            <span className="inline-flex items-center gap-2">
              <StatusPill status={pack.latest_run.status} />
              <span className="hidden sm:inline">{timeAgo(pack.latest_run.finished_at)}</span>
            </span>
          ) : (
            `${pack.estimated_time}`
          )}
        </span>
      </div>
    </motion.article>
  );
}

function StatsTile({ stats }: { stats: Stats | null }) {
  const rows: [string, number | string][] = stats
    ? [
        ["runs finished", stats.succeeded_runs],
        ["on real data", stats.real_runs],
        ["skills covered", stats.skills.length],
      ]
    : [];
  return (
    <motion.aside custom={6} variants={tile} initial="hidden" animate="show" className="glass flex min-h-[290px] flex-col rounded-4xl p-5">
      <h2 className="text-lg font-bold">On this machine</h2>
      <dl className="mt-3 space-y-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3 rounded-2xl bg-white/70 px-4 py-2.5">
            <dt className="text-sm text-ink-soft">{label}</dt>
            <dd className="font-display text-2xl font-bold">{value}</dd>
          </div>
        ))}
      </dl>
      <Link to="/sources" className="mt-auto pt-4 text-sm font-semibold text-[#4b52d6] underline underline-offset-2">
        {stats?.source_check.checked_at ? `Sources checked ${timeAgo(stats.source_check.checked_at)}` : "Check the data sources"}
      </Link>
    </motion.aside>
  );
}

const STEPS = [
  ["Pick a pack", "Each one answers a single question with one dataset."],
  ["Run the sample", "Synthetic data with the real schema - works offline in seconds."],
  ["Switch to real data", "The pack downloads or queries the official source and records where it came from."],
  ["Read the trap", "Every pack has a check for its classic mistake, shown as pass or fail."],
  ["Beat the baseline", "Download the starter, open the notebook, take on a challenge."],
];

export default function Catalog() {
  const packs = useApi(api.packs);
  const stats = useApi(api.stats);
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState<string>("All");
  const [level, setLevel] = useState<string>("Any level");

  const providers = useMemo(() => ["All", ...new Set((packs.data ?? []).map((p) => p.provider))], [packs.data]);
  const matches = (p: Pack) => {
    const q = query.trim().toLowerCase();
    const text = [p.title, p.tagline, p.question, p.task_type, ...p.skills].join(" ").toLowerCase();
    return (!q || text.includes(q)) && (provider === "All" || p.provider === provider) && (level === "Any level" || p.difficulty === level);
  };
  const shown = (packs.data ?? []).filter((p) => !p.error).sort((a, b) => (PLACEMENT[a.slug]?.order ?? 99) - (PLACEMENT[b.slug]?.order ?? 99));
  const visibleCount = shown.filter(matches).length;

  return (
    <div>
      <section className="grid auto-rows-auto grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4" aria-label="Dataset packs">
        <motion.div
          custom={0}
          variants={tile}
          initial="hidden"
          animate="show"
          className="glass-strong flex flex-col rounded-4xl p-6 sm:p-8 md:col-span-2 lg:row-span-2"
        >
          <h1 className="font-display text-[clamp(2.5rem,5.4vw,4.4rem)] font-extrabold leading-[0.95] tracking-[-0.03em]">
            Real datasets,
            <br />
            ready to run.
          </h1>
          <p className="mt-5 max-w-[52ch] text-lg leading-relaxed text-ink-soft">
            Five projects from NASA, UCI and Kaggle. Each runs from a small sample in seconds, then on the official data,
            and ends with a baseline result you can try to beat.
          </p>

          <div className="mt-6">
            <h2 className="font-display text-base font-bold">Every pack includes</h2>
            <ul className="mt-2 flex flex-wrap gap-2">
              {INCLUDES.map((x) => (
                <li key={x} className="rounded-full border border-white bg-white/70 px-3 py-1 text-sm font-medium text-ink-soft">{x}</li>
              ))}
            </ul>
          </div>

          <div className="mt-auto space-y-3 pt-8">
            <label className="relative block">
              <span className="sr-only">Search packs</span>
              <Search size={18} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-faint" />
              <input
                className="field py-3 pl-10 text-base"
                placeholder="Search skills or topics, like SQL or leakage"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <div className="neu-track flex gap-1" role="radiogroup" aria-label="Provider">
                {providers.map((p) => (
                  <button
                    key={p}
                    role="radio"
                    aria-checked={provider === p}
                    onClick={() => setProvider(p)}
                    className={`rounded-xl px-3 py-1.5 text-sm font-semibold transition-all ${
                      provider === p ? "bg-white text-ink shadow-neu" : "text-ink-soft hover:text-ink"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <select className="field w-auto py-2" value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Difficulty">
                {["Any level", "beginner", "intermediate", "advanced"].map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
              <span className="text-sm text-ink-soft" aria-live="polite">
                {packs.data ? `${visibleCount} of ${shown.length} packs` : ""}
              </span>
            </div>
          </div>
        </motion.div>

        {packs.loading && <div className="glass rounded-4xl p-6"><Spinner label="Loading packs" /></div>}
        {packs.error && (
          <div className="md:col-span-2">
            <ErrorBox message={packs.error} action={<button className="btn-ghost" onClick={packs.reload}>Try again</button>} />
          </div>
        )}
        {shown.map((p, i) => (
          <PackTile key={p.slug} pack={p} index={i} dimmed={!matches(p)} />
        ))}
        {packs.data && <StatsTile stats={stats.data} />}
      </section>

      {packs.data && visibleCount === 0 && (
        <p className="mt-4 text-center text-ink-soft">
          No pack matches those filters.{" "}
          <button className="font-semibold underline" onClick={() => { setQuery(""); setProvider("All"); setLevel("Any level"); }}>
            Clear filters
          </button>
        </p>
      )}

      <section className="mt-14" aria-labelledby="how">
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
