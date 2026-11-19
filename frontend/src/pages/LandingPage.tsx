import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Database,
  Download,
  Eye,
  FileSpreadsheet,
  Globe,
  HardDrive,
  Layers,
  Play,
  PlugZap,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TableProperties,
  UserPlus,
} from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ChartCard, Columns, RankedBars } from "../components/insights/Charts";
import { Scatter } from "../components/insights/RelationCharts";
import { ErrorBox, ModeBadge, PROVIDER_TINT } from "../components/ui";
import { useAccount } from "../lib/account";
import type { Pack } from "../types";

/** Detect prefers-reduced-motion so animations and transitions are disabled instantly. */
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(prefers-reduced-motion: reduce)").matches : false,
  );
  useEffect(() => {
    const m = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(m.matches);
    m.addEventListener("change", onChange);
    return () => m.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Scroll-reveal wrapper: fade + 12px rise, once, with configurable staggered delay. */
function ScrollReveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = useState(false);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) {
      setRevealed(true);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setRevealed(true);
          observer.disconnect();
        }
      },
      { threshold: 0.08, rootMargin: "0px 0px -40px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [reduced]);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: revealed ? 1 : 0,
        transform: revealed ? "translateY(0)" : "translateY(12px)",
        transition: reduced
          ? "none"
          : `opacity 480ms cubic-bezier(0.16, 1, 0.3, 1) ${delay}ms, transform 480ms cubic-bezier(0.16, 1, 0.3, 1) ${delay}ms`,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- DEMO REPORT DATA (Fixed, no API calls)
const DEMO_HOURLY: [string, number][] = [
  ["00", 54], ["02", 22], ["04", 8], ["06", 36], ["08", 362], ["10", 175],
  ["12", 253], ["14", 240], ["16", 311], ["18", 428], ["20", 226], ["22", 131],
];

const DEMO_SCATTER: [number, number][] = [
  [8.2, 85], [10.5, 110], [12.4, 140], [14.0, 185], [15.1, 210],
  [16.8, 240], [18.7, 290], [20.2, 330], [22.0, 385], [23.8, 415],
  [24.5, 430], [26.0, 445], [27.2, 455], [29.1, 420], [31.5, 380],
];

const DEMO_WEATHER: { label: string; value: number; tone?: "warn" | "bad" }[] = [
  { label: "Clear / Few clouds", value: 65 },
  { label: "Mist / Cloudy", value: 24 },
  { label: "Light rain / Snow", value: 10 },
  { label: "Heavy rain / Ice", value: 1, tone: "warn" },
];

const CHIP_EXAMPLES = [
  "weather time series",
  "motor vehicle collisions",
  "satellite images",
  "exoplanet discovery",
];

// ---------------------------------------------------------------- MAIN COMPONENT
export default function LandingPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAccount();

  // Redirect old /?q= and query links to /discover
  if (location.search && location.search !== "?") {
    return <Navigate to={`/discover${location.search}`} replace />;
  }

  // Hero search state
  const [query, setQuery] = useState("");
  const [emptyHint, setEmptyHint] = useState(false);

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    const clean = query.trim();
    if (!clean) {
      setEmptyHint(true);
      return;
    }
    setEmptyHint(false);
    navigate(`/discover?q=${encodeURIComponent(clean)}`);
  };

  const handleChip = (chip: string) => {
    setQuery(chip);
    setEmptyHint(false);
    navigate(`/discover?q=${encodeURIComponent(chip)}`);
  };

  // Curated packs state
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [packsLoading, setPacksLoading] = useState(true);
  const [packsError, setPacksError] = useState<string | null>(null);

  const loadPacks = () => {
    setPacksLoading(true);
    setPacksError(null);
    api.packs()
      .then((data) => {
        setPacks(data);
        setPacksLoading(false);
      })
      .catch((err) => {
        setPacksError((err as Error).message || "Could not load curated packs.");
        setPacksLoading(false);
      });
  };

  useEffect(() => {
    loadPacks();
  }, []);

  // Step connector line progress state
  const stepsContainerRef = useRef<HTMLDivElement>(null);
  const [stepsVisible, setStepsVisible] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const [previewVisible, setPreviewVisible] = useState(false);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) {
      setStepsVisible(true);
      setPreviewVisible(true);
      return;
    }
    const obsSteps = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setStepsVisible(true);
        obsSteps.disconnect();
      }
    }, { threshold: 0.15 });

    const obsPreview = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setPreviewVisible(true);
        obsPreview.disconnect();
      }
    }, { threshold: 0.1 });

    if (stepsContainerRef.current) obsSteps.observe(stepsContainerRef.current);
    if (previewRef.current) obsPreview.observe(previewRef.current);

    return () => {
      obsSteps.disconnect();
      obsPreview.disconnect();
    };
  }, [reduced]);

  return (
    <div className="relative space-y-24 sm:space-y-32">
      {/* Background drifting blobs in sky/sun palette (GPU-only) */}
      <div className="pointer-events-none absolute -top-16 inset-x-0 h-[480px] overflow-hidden -z-10" aria-hidden>
        <div className="hero-blob-1 absolute -left-20 top-2 h-72 w-72 rounded-full bg-peri/20 blur-3xl" />
        <div className="hero-blob-2 absolute right-0 top-16 h-80 w-80 rounded-full bg-sun/25 blur-3xl" />
      </div>

      {/* ========================================================================= */}
      {/* 1. HERO SECTION */}
      {/* ========================================================================= */}
      <section aria-label="Hero" className="pt-4 sm:pt-10">
        <div className="mx-auto max-w-4xl text-center">
          <h1 className="hero-enter-1 font-display text-[clamp(2.4rem,5.5vw,4.5rem)] font-extrabold leading-[1.04] tracking-[-0.03em] text-ink">
            Ready-to-run dataset starter packs
          </h1>
          <p className="hero-enter-2 mx-auto mt-4 max-w-[62ch] text-lg text-ink-soft sm:text-xl">
            Pick a real dataset, inspect schemas and distributions before downloading, and beat working baselines with self-contained notebooks.
          </p>

          {/* Search box */}
          <div className="hero-enter-3 mt-8">
            <form
              role="search"
              aria-label="Search datasets"
              onSubmit={handleSearchSubmit}
              className="glass-strong mx-auto flex max-w-2xl items-center gap-2 rounded-2xl p-2 sm:gap-3 sm:p-2.5"
            >
              <label htmlFor="hero-search-input" className="sr-only">Describe your project</label>
              <div className="relative flex min-w-0 flex-1 items-center pl-2">
                <Search size={20} className="shrink-0 text-ink-faint" aria-hidden />
                <input
                  id="hero-search-input"
                  type="text"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    if (emptyHint) setEmptyHint(false);
                  }}
                  placeholder="Describe your project…"
                  className="w-full bg-transparent px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-none sm:text-base"
                />
              </div>
              <button
                type="submit"
                className="btn-clay bg-peri px-5 py-2.5 text-sm font-semibold text-paper shadow-clay sm:px-6 sm:py-3 sm:text-base"
              >
                Search
              </button>
            </form>

            {emptyHint && (
              <p
                role="status"
                className="mx-auto mt-3 flex max-w-md items-center justify-center gap-1.5 rounded-xl bg-sun/40 px-3 py-1.5 text-xs font-semibold text-warn-ink"
              >
                <AlertCircle size={15} aria-hidden />
                <span>Enter what you're building or looking for, or pick an example below.</span>
              </p>
            )}

            {/* Example chips */}
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <span className="text-xs font-medium text-ink-faint">Try:</span>
              {CHIP_EXAMPLES.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => handleChip(chip)}
                  className="chip cursor-pointer py-1 px-3 text-xs font-semibold text-ink-soft transition-colors hover:bg-white hover:text-ink focus-visible:ring-2 focus-visible:ring-peri"
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 2. HOW IT WORKS */}
      {/* ========================================================================= */}
      <section aria-labelledby="heading-how-it-works" className="relative">
        <ScrollReveal>
          <div className="text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-peri-ink">Methodology</p>
            <h2 id="heading-how-it-works" className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
              How it works
            </h2>
            <p className="mx-auto mt-2 max-w-[55ch] text-sm text-ink-soft sm:text-base">
              From requirement search to verifiable results in four disciplined steps.
            </p>
          </div>
        </ScrollReveal>

        <div ref={stepsContainerRef} className="relative mt-10">
          {/* Connecting line on desktop that draws as you scroll */}
          <div className="pointer-events-none absolute top-1/2 -translate-y-8 inset-x-8 hidden lg:block -z-10" aria-hidden>
            <svg className="w-full h-3 overflow-visible" viewBox="0 0 1000 12" fill="none">
              <line
                x1="40"
                y1="6"
                x2="960"
                y2="6"
                stroke="rgb(var(--c-peri))"
                strokeWidth="2.5"
                strokeDasharray="6 6"
                strokeOpacity={stepsVisible ? "0.45" : "0.1"}
                className="transition-all duration-700 ease-out"
              />
            </svg>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {/* Step 1 */}
            <ScrollReveal delay={0}>
              <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
                <div className="flex items-center justify-between">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-peri/20 font-display text-sm font-bold text-peri-ink">
                    1
                  </span>
                  <span className="chip text-[11px]">Requirement match</span>
                </div>
                <h3 className="mt-4 font-display text-lg font-bold">Find a dataset</h3>
                <p className="mt-1 text-sm text-ink-soft">
                  Search by project topic, required columns, granularity, or format. We check schemas and live sources against your criteria.
                </p>
                {/* Illustration */}
                <div className="mt-4 rounded-2xl bg-white/70 p-3" aria-hidden>
                  <div className="flex items-center gap-1.5 text-xs text-ink-faint">
                    <Search size={13} />
                    <span className="truncate font-mono text-[11px]">bike rental weather</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <span className="rounded-md bg-peri/15 px-1.5 py-0.5 text-[10px] font-bold text-peri-ink">tabular</span>
                    <span className="rounded-md bg-aqua/20 px-1.5 py-0.5 text-[10px] font-bold text-aqua-ink">time-series</span>
                    <span className="rounded-md bg-ok/15 px-1.5 py-0.5 text-[10px] font-bold text-ok">hourly</span>
                  </div>
                </div>
              </div>
            </ScrollReveal>

            {/* Step 2 */}
            <ScrollReveal delay={60}>
              <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
                <div className="flex items-center justify-between">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-aqua/25 font-display text-sm font-bold text-aqua-ink">
                    2
                  </span>
                  <span className="chip text-[11px]">Zero download</span>
                </div>
                <h3 className="mt-4 font-display text-lg font-bold">Look inside before downloading</h3>
                <p className="mt-1 text-sm text-ink-soft">
                  Inspect columns, null rates, data types, and verified date coverage before pulling gigabytes over your network.
                </p>
                {/* Illustration */}
                <div className="mt-4 space-y-1.5 rounded-2xl bg-white/70 p-3 text-xs" aria-hidden>
                  <div className="flex justify-between font-mono text-[11px] text-ink-soft">
                    <span>temp (float)</span>
                    <span className="text-ok">0% null</span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-sky-deep">
                    <div className="h-1.5 rounded-full bg-ok w-full" />
                  </div>
                  <div className="flex justify-between font-mono text-[11px] text-ink-soft">
                    <span>casual (int)</span>
                    <span className="text-warn">Trap source</span>
                  </div>
                </div>
              </div>
            </ScrollReveal>

            {/* Step 3 */}
            <ScrollReveal delay={120}>
              <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
                <div className="flex items-center justify-between">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-sun/40 font-display text-sm font-bold text-warn-ink">
                    3
                  </span>
                  <span className="chip text-[11px]">Instant run</span>
                </div>
                <h3 className="mt-4 font-display text-lg font-bold">Run a sample</h3>
                <p className="mt-1 text-sm text-ink-soft">
                  Test the complete pipeline in seconds using offline synthetic fixtures that match the real schema, or pull live official APIs.
                </p>
                {/* Illustration */}
                <div className="mt-4 rounded-2xl bg-white/70 p-3" aria-hidden>
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1 rounded-full bg-sun/50 px-2 py-0.5 text-[10px] font-bold text-warn-ink">
                      Sample mode
                    </span>
                    <span className="font-mono text-[11px] text-ink-faint">0.8 s</span>
                  </div>
                  <div className="mt-2.5 flex items-center gap-2">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-peri text-paper">
                      <Play size={10} fill="currentColor" />
                    </div>
                    <span className="text-[11px] font-semibold text-ink">python analysis.py</span>
                  </div>
                </div>
              </div>
            </ScrollReveal>

            {/* Step 4 */}
            <ScrollReveal delay={180}>
              <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
                <div className="flex items-center justify-between">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-ok/20 font-display text-sm font-bold text-ok">
                    4
                  </span>
                  <span className="chip text-[11px]">Trap verified</span>
                </div>
                <h3 className="mt-4 font-display text-lg font-bold">Read the report</h3>
                <p className="mt-1 text-sm text-ink-soft">
                  Review verified distributions, baseline predictions, and technical traps caught upfront with automated regression tests.
                </p>
                {/* Illustration */}
                <div className="mt-4 space-y-1.5 rounded-2xl bg-white/70 p-3 text-xs" aria-hidden>
                  <div className="flex items-center gap-1.5 font-semibold text-ok text-[11px]">
                    <CheckCircle2 size={13} className="shrink-0" />
                    <span className="truncate">casual + registered = cnt</span>
                  </div>
                  <p className="text-[10px] text-ink-faint">No target leakage in holdout window</p>
                  <div className="mt-1 flex items-baseline justify-between text-[11px]">
                    <span className="text-ink-soft">Baseline MAE:</span>
                    <span className="font-mono font-bold text-ink">28.4</span>
                  </div>
                </div>
              </div>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 3. REPORT PREVIEW (Live-looking, real chart components, fixed demo data) */}
      {/* ========================================================================= */}
      <section ref={previewRef} aria-labelledby="heading-report-preview" className="space-y-6">
        <ScrollReveal>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-peri-ink">Interactive Inspection</p>
              <h2 id="heading-report-preview" className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
                A live-looking report preview
              </h2>
              <p className="mt-1 max-w-[62ch] text-sm text-ink-soft sm:text-base">
                Rendered with the platform's native SVG charts, headline cards, metric summaries, and automated trap checks.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-sun/60 px-3 py-1 text-xs font-bold text-warn-ink shadow-sm">
                Example data · Sample
              </span>
              <span className="rounded-full bg-ok/15 px-3 py-1 text-xs font-bold text-ok">
                Zero API calls
              </span>
            </div>
          </div>
        </ScrollReveal>

        {/* Report Shell */}
        <ScrollReveal delay={60}>
          <div className="space-y-5 rounded-4xl border border-white/80 bg-white/40 p-4 shadow-glass backdrop-blur-xl sm:p-6">
            {/* Header info */}
            <div className="glass-strong rounded-3xl p-5 sm:p-6">
              <div className="flex flex-wrap items-center gap-2">
                <ModeBadge sample={true} />
                <span className="rounded-full bg-sun/40 px-2.5 py-0.5 text-xs font-bold text-warn-ink">
                  Example data · Sample · 17,379 rows
                </span>
                <span className="ml-auto text-xs text-ink-faint">Simulated run output</span>
              </div>
              <p className="mt-3 font-display text-xl font-bold leading-snug sm:text-2xl text-ink">
                Bike Sharing Demand: 17,379 hourly records; temp 0.8 to 41.0°C; most associated with hour of day (r = +0.40)
              </p>
              <p className="mt-2 text-sm text-ink-soft">
                These numbers come from sample data. They demonstrate automated schema profiling, distribution analysis, and baseline predictions.
              </p>
            </div>

            {/* Grid with yellow callout card & metric tiles */}
            <div className="grid gap-4 lg:grid-cols-3">
              {/* Yellow Callout Card (matching DatasetRunPage aside) */}
              <aside
                className="flex flex-col rounded-3xl p-5 sm:p-6 shadow-clay lg:col-span-1"
                style={{ background: "var(--sun-panel)" }}
              >
                <span className="text-xs font-bold uppercase tracking-wider text-warn-ink">
                  Sample-first inspection
                </span>
                <h3 className="mt-2 font-display text-2xl font-extrabold leading-tight text-warn-ink">
                  Real records, not the whole dataset
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-warn-ink">
                  A sample verifies field types, null rates, and date ranges without moving gigabytes over the network. Every pack catches classic traps before modeling.
                </p>
                <p className="mt-auto pt-5 text-xs text-warn-ink opacity-90">
                  Detected: Tabular time-series · Hourly intervals · Regression baseline
                </p>
              </aside>

              {/* 4 Metric Tiles */}
              <div className="grid grid-cols-2 gap-3 lg:col-span-2">
                <div className="glass rounded-3xl p-4">
                  <p className="text-xs font-semibold text-ink-soft">Rows analyzed</p>
                  <p className="mt-1 font-display text-2xl font-bold sm:text-3xl">17,379</p>
                  <p className="mt-1 text-xs text-ink-faint">Hourly observations</p>
                </div>
                <div className="glass rounded-3xl p-4">
                  <p className="text-xs font-semibold text-ink-soft">Median rentals</p>
                  <p className="mt-1 font-display text-2xl font-bold sm:text-3xl">
                    142 <span className="text-sm font-semibold text-ink-faint">/hr</span>
                  </p>
                  <p className="mt-1 text-xs text-ink-faint">Range: 1 to 977</p>
                </div>
                <div className="glass rounded-3xl p-4">
                  <p className="text-xs font-semibold text-ink-soft">Strongest association</p>
                  <p className="mt-1 font-display text-2xl font-bold sm:text-3xl text-ok">+0.40</p>
                  <p className="mt-1 text-xs text-ink-faint">Pearson r with hour</p>
                </div>
                <div className="glass rounded-3xl p-4">
                  <p className="text-xs font-semibold text-ink-soft">Trap status</p>
                  <p className="mt-1 font-display text-2xl font-bold sm:text-3xl text-ok">Passed</p>
                  <p className="mt-1 text-xs text-ink-faint">No target leakage</p>
                </div>
              </div>
            </div>

            {/* Trap Check Card */}
            <div className="glass rounded-3xl p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <h3 className="font-display text-base font-bold sm:text-lg">
                  Trap checks <span className="font-body text-xs font-semibold text-ink-soft">2 of 2 passed</span>
                </h3>
                <span className="chip text-[11px] text-ok">Regression verified</span>
              </div>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                <li className="flex items-start gap-2.5 rounded-2xl bg-white/75 p-3">
                  <CheckCircle2 size={18} className="shrink-0 text-ok mt-0.5" />
                  <div>
                    <p className="text-xs font-bold text-ink">casual + registered = cnt</p>
                    <p className="text-xs text-ink-soft">Verified that casual and registered counts are excluded from training features.</p>
                  </div>
                </li>
                <li className="flex items-start gap-2.5 rounded-2xl bg-white/75 p-3">
                  <CheckCircle2 size={18} className="shrink-0 text-ok mt-0.5" />
                  <div>
                    <p className="text-xs font-bold text-ink">Temporal holdout order</p>
                    <p className="text-xs text-ink-soft">Evaluation splits chronologically to prevent future information leaking into the past.</p>
                  </div>
                </li>
              </ul>
            </div>

            {/* REAL CHARTS (Columns, Scatter, RankedBars) */}
            <div
              className={`grid gap-4 lg:grid-cols-2 ${previewVisible ? "opacity-100" : "opacity-90"} transition-opacity duration-500`}
              style={{ "--analysis-series": "rgb(var(--c-chart-green))" } as React.CSSProperties}
            >
              {/* Chart 1: Columns */}
              <ChartCard
                title="Hourly rental profile"
                scope="Example data"
                note="Average bike rentals by hour of day (sample subset)."
                table={{
                  head: ["Hour", "Avg rentals"],
                  rows: DEMO_HOURLY.map(([h, v]) => [`${h}:00`, v.toLocaleString()]),
                }}
              >
                <Columns
                  data={DEMO_HOURLY}
                  unit="rentals/hr"
                  xLabel="Hour of day (0–23)"
                  yLabel="Avg rentals"
                />
              </ChartCard>

              {/* Chart 2: Scatter */}
              <ChartCard
                title="Temperature vs. demand"
                scope="Example data"
                note="Scatter relationship between temperature and rental volume."
                table={{
                  head: ["Temp (°C)", "Hourly rentals"],
                  rows: DEMO_SCATTER.map(([t, r]) => [`${t}°C`, r.toLocaleString()]),
                }}
              >
                <Scatter
                  points={DEMO_SCATTER}
                  xLabel="Temperature (°C)"
                  yLabel="Rentals / hr"
                />
              </ChartCard>

              {/* Chart 3: RankedBars */}
              <div className="lg:col-span-2">
                <ChartCard
                  title="Weather condition distribution"
                  scope="Example data"
                  note="Observed weather situations across analyzed records."
                  table={{
                    head: ["Weather", "Share"],
                    rows: DEMO_WEATHER.map((d) => [d.label, `${d.value}%`]),
                  }}
                >
                  <RankedBars data={DEMO_WEATHER} percentages />
                </ChartCard>
              </div>
            </div>
          </div>
        </ScrollReveal>
      </section>

      {/* ========================================================================= */}
      {/* 4. WHAT YOU CAN IMPORT */}
      {/* ========================================================================= */}
      <section aria-labelledby="heading-import" className="space-y-6">
        <ScrollReveal>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-peri-ink">Universal Ingestion</p>
            <h2 id="heading-import" className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
              What you can import
            </h2>
            <p className="mt-1 max-w-[64ch] text-sm text-ink-soft sm:text-base">
              Direct files, live queries, or connected provider catalogs with format detection and immediate profiling.
            </p>
          </div>
        </ScrollReveal>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {/* 1. Tables */}
          <ScrollReveal delay={0}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-peri/20 text-peri-ink">
                <TableProperties size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Tables</h3>
              <p className="mt-1 text-xs font-semibold text-peri-ink">CSV, TSV, JSON, Parquet, Excel</p>
              <p className="mt-2 text-sm text-ink-soft">
                Automatic column profiling, missingness detection, and distribution analysis for single and multi-sheet workbooks.
              </p>
            </div>
          </ScrollReveal>

          {/* 2. Images in archives */}
          <ScrollReveal delay={60}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-aqua/25 text-aqua-ink">
                <Layers size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Images in archives</h3>
              <p className="mt-1 text-xs font-semibold text-aqua-ink">ZIP and tarballs</p>
              <p className="mt-2 text-sm text-ink-soft">
                Inspect image dimensions, color profiles, class balance, and bounding-box annotations before training.
              </p>
            </div>
          </ScrollReveal>

          {/* 3. SINEX */}
          <ScrollReveal delay={120}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sun/40 text-warn-ink">
                <Globe size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">SINEX</h3>
              <p className="mt-1 text-xs font-semibold text-warn-ink">Space geodesy solutions</p>
              <p className="mt-2 text-sm text-ink-soft">
                Station coordinates, normal equations, and site velocity vectors verified across international GNSS networks.
              </p>
            </div>
          </ScrollReveal>

          {/* 4. Kaggle */}
          <ScrollReveal delay={180}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-orange-500/20 text-orange-600">
                <PlugZap size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Kaggle</h3>
              <p className="mt-1 text-xs font-semibold text-orange-600">Datasets & API hub</p>
              <p className="mt-2 text-sm text-ink-soft">
                Connect your account to list files and analyze datasets in one click without downloading manually.
              </p>
              <div className="mt-auto pt-4">
                <Link
                  to="/settings"
                  className="btn-ghost inline-flex items-center gap-1.5 text-xs font-semibold"
                >
                  <PlugZap size={14} /> Connect Kaggle
                </Link>
              </div>
            </div>
          </ScrollReveal>

          {/* 5. Hugging Face */}
          <ScrollReveal delay={0}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-500/20 text-amber-700">
                <Database size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Hugging Face</h3>
              <p className="mt-1 text-xs font-semibold text-amber-700">Hub datasets</p>
              <p className="mt-2 text-sm text-ink-soft">
                Stream parquet partitions, split configurations, and structured metadata directly from model hub repositories.
              </p>
            </div>
          </ScrollReveal>

          {/* 6. Zenodo */}
          <ScrollReveal delay={60}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-500/20 text-blue-600">
                <BookOpen size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Zenodo</h3>
              <p className="mt-1 text-xs font-semibold text-blue-600">Open-science deposits</p>
              <p className="mt-2 text-sm text-ink-soft">
                Direct access to multi-file research deposits, persistent DOIs, and scientific benchmark archives.
              </p>
            </div>
          </ScrollReveal>

          {/* 7. NASA / CMR */}
          <ScrollReveal delay={120}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sky-500/20 text-sky-600">
                <HardDrive size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">NASA / CMR</h3>
              <p className="mt-1 text-xs font-semibold text-sky-600">Earthdata & POWER APIs</p>
              <p className="mt-2 text-sm text-ink-soft">
                Live solar irradiance, daily meteorology, exoplanet archives, and global Earth observation satellite granules.
              </p>
            </div>
          </ScrollReveal>

          {/* 8. Socrata */}
          <ScrollReveal delay={180}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-emerald-500/20 text-emerald-700">
                <FileSpreadsheet size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Socrata</h3>
              <p className="mt-1 text-xs font-semibold text-emerald-700">Open city portals</p>
              <p className="mt-2 text-sm text-ink-soft">
                Civic crash data, transit records, and public safety datasets queried live through open SODA API endpoints.
              </p>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 5. CURATED PACKS */}
      {/* ========================================================================= */}
      <section aria-labelledby="heading-curated-packs" className="space-y-6">
        <ScrollReveal>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-peri-ink">Curated Portfolio</p>
              <h2 id="heading-curated-packs" className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
                Curated starter packs
              </h2>
              <p className="mt-1 max-w-[62ch] text-sm text-ink-soft sm:text-base">
                Self-contained projects with working baseline notebooks, official loaders, and technical trap checks.
              </p>
            </div>
            <Link to="/packs" className="btn-ghost text-sm font-semibold">
              Browse all packs <ArrowRight size={15} />
            </Link>
          </div>
        </ScrollReveal>

        {/* Loading skeleton */}
        {packsLoading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="glass min-h-[360px] animate-pulse rounded-4xl p-5">
                <div className="h-4 w-24 rounded-full bg-sky-deep" />
                <div className="mt-4 h-6 w-3/4 rounded-xl bg-sky-deep" />
                <div className="mt-2 h-4 w-full rounded-lg bg-sky-deep" />
                <div className="mt-4 h-36 w-full rounded-2xl bg-sky-deep" />
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {!packsLoading && packsError && (
          <ErrorBox
            message={packsError}
            action={
              <button onClick={loadPacks} className="btn-clay bg-peri text-xs px-4 py-2">
                <RefreshCw size={14} /> Retry
              </button>
            }
          />
        )}

        {/* Pack cards */}
        {!packsLoading && !packsError && packs && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {packs.map((p, idx) => {
              const tint = PROVIDER_TINT[p.provider] ?? p.accent;
              return (
                <ScrollReveal key={p.slug} delay={(idx % 3) * 60}>
                  <article className="card-lift glass relative flex h-full flex-col overflow-hidden rounded-4xl p-5">
                    <span className="absolute inset-x-0 top-0 h-1.5" style={{ background: p.accent }} aria-hidden />

                    {/* Pill badges */}
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full px-2.5 py-0.5 font-bold text-paper" style={{ background: tint }}>
                        {p.provider}
                      </span>
                      <span className="chip capitalize">{p.difficulty}</span>
                      {p.estimated_time && <span className="chip">{p.estimated_time}</span>}
                    </div>

                    {/* Title */}
                    <h3 className="mt-3 font-display text-xl font-bold leading-tight">
                      <Link to={`/packs/${p.slug}`} className="hover:underline">
                        {p.title}
                      </Link>
                    </h3>

                    {/* Question / summary */}
                    <p className="mt-1 line-clamp-2 text-sm text-ink-soft">{p.tagline || p.question}</p>

                    {/* Trap avoided */}
                    <p className="mt-2 text-xs">
                      <span className="font-bold text-warn-ink">Trap: </span>
                      <span className="text-ink-soft">{p.lesson?.title || p.lesson?.summary}</span>
                    </p>

                    {/* Preview chart image */}
                    {p.has_preview && (
                      <div className="mt-3 overflow-hidden rounded-2xl border border-white bg-paper">
                        <img
                          src={api.url(`/api/packs/${p.slug}/assets/preview.png`)}
                          alt={`Preview output for ${p.title}`}
                          className="h-36 w-full object-contain"
                          loading="lazy"
                        />
                      </div>
                    )}

                    {/* Buttons */}
                    <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
                      <Link
                        to={`/packs/${p.slug}`}
                        className="btn-clay px-4 py-2 text-xs font-semibold"
                        style={{ background: p.accent }}
                      >
                        Explore pack
                      </Link>
                      <a
                        href={api.url(`/api/packs/${p.slug}/starter.zip`)}
                        className="btn-ghost text-xs"
                        download
                      >
                        <Download size={13} /> Starter ZIP
                      </a>
                    </div>
                  </article>
                </ScrollReveal>
              );
            })}
          </div>
        )}
      </section>

      {/* ========================================================================= */}
      {/* 6. TRUST SECTION */}
      {/* ========================================================================= */}
      <section aria-labelledby="heading-trust" className="space-y-6">
        <ScrollReveal>
          <div className="text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-peri-ink">Transparency</p>
            <h2 id="heading-trust" className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
              Built for trust and rigor
            </h2>
            <p className="mx-auto mt-2 max-w-[58ch] text-sm text-ink-soft sm:text-base">
              Every metric, sample, and correlation is labeled truthfully without black-box exaggerations.
            </p>
          </div>
        </ScrollReveal>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <ScrollReveal delay={0}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-peri/20 text-peri-ink">
                <Eye size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Scope labeled exactly</h3>
              <p className="mt-2 text-sm text-ink-soft">
                Every chart and metric declares whether it reflects a 1,000-row sample or the complete dataset. Synthetic numbers are always watermarked.
              </p>
            </div>
          </ScrollReveal>

          <ScrollReveal delay={60}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-aqua/25 text-aqua-ink">
                <CheckCircle2 size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Units only when verified</h3>
              <p className="mt-2 text-sm text-ink-soft">
                Units appear only when confirmed by the source dictionary or header metadata. Unverified units are flagged rather than assumed.
              </p>
            </div>
          </ScrollReveal>

          <ScrollReveal delay={120}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sun/40 text-warn-ink">
                <Sparkles size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Associations, not causes</h3>
              <p className="mt-2 text-sm text-ink-soft">
                Correlations (Pearson r, Spearman ρ) are stated as associations with sample sizes, actively preventing invalid causal claims.
              </p>
            </div>
          </ScrollReveal>

          <ScrollReveal delay={180}>
            <div className="card-lift glass flex h-full flex-col rounded-3xl p-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-ok/20 text-ok">
                <ShieldCheck size={20} />
              </div>
              <h3 className="mt-4 font-display text-lg font-bold">Kaggle tokens server-side</h3>
              <p className="mt-2 text-sm text-ink-soft">
                Your Kaggle API tokens are encrypted and sent only in authenticated HTTPS requests. Credentials never touch client storage or bundles.
              </p>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 7. FINAL CALL TO ACTION */}
      {/* ========================================================================= */}
      <section aria-label="Call to action" className="pt-4 pb-6">
        <ScrollReveal>
          <div className="glass-strong mx-auto max-w-4xl rounded-4xl p-8 text-center sm:p-12 shadow-lift">
            <h2 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl text-ink">
              Ready to start building?
            </h2>
            <p className="mx-auto mt-3 max-w-[54ch] text-base text-ink-soft sm:text-lg">
              Describe your project to search verified civic and scientific datasets, or pick an existing starter pack to run right away.
            </p>

            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <Link
                to="/discover"
                className="btn-clay bg-peri px-6 py-3 text-base font-semibold text-paper shadow-clay"
              >
                <Search size={18} /> Start searching
              </Link>
              <Link
                to="/packs"
                className="btn-ghost px-5 py-3 text-base font-semibold"
              >
                Browse curated packs
              </Link>
              {user ? (
                <Link
                  to="/settings"
                  className="btn-ghost px-4 py-3 text-sm font-semibold text-ink-soft"
                >
                  <Settings size={16} /> Account ({user.email.split("@")[0]})
                </Link>
              ) : (
                <Link
                  to="/settings"
                  className="btn-ghost px-4 py-3 text-sm font-semibold text-ink-soft"
                >
                  <UserPlus size={16} /> Log in / Sign up
                </Link>
              )}
            </div>
          </div>
        </ScrollReveal>
      </section>
    </div>
  );
}
