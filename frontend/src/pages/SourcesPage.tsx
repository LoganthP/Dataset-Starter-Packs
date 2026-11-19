import { CheckCircle2, HelpCircle, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api, timeAgo, useApi } from "../api";
import { ErrorBox, Spinner } from "../components/ui";

const STATUS = {
  ok: { label: "Responding", cls: "text-ok", icon: <CheckCircle2 size={20} /> },
  error: { label: "Not reachable", cls: "text-bad", icon: <XCircle size={20} /> },
  manual: { label: "Check by hand", cls: "text-warn", icon: <HelpCircle size={20} /> },
};

function LiveProvidersPanel() {
  const meta = useApi(api.discoverMeta);
  const m = meta.data;
  if (!m) return null;
  return (
    <section className="glass rounded-3xl p-5" aria-labelledby="live-h">
      <h2 id="live-h" className="font-display text-xl font-bold">What Discover searches</h2>
      <p className="text-sm text-ink-soft">
        A local catalog of {m.total} records ({m.reviewed} reviewed, {m.curated} starter packs), plus these sources live on every search.
      </p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {m.liveProviders.map((p) => (
          <li key={p.key} className="flex items-start gap-2 rounded-2xl bg-white/75 p-3 text-sm">
            {p.configured ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-ok" /> : <HelpCircle size={17} className="mt-0.5 shrink-0 text-ink-faint" />}
            <span><b>{p.label}</b>{!p.configured && p.note && <span className="block text-xs text-ink-faint">{p.note}</span>}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ImportsPanel() {
  const meta = useApi(api.discoverMeta);
  const imports = meta.data?.imports;
  useEffect(() => {
    if (!imports?.running) return;
    const t = setInterval(meta.reload, 2000);
    return () => clearInterval(t);
  }, [imports?.running, meta.reload]);
  const run = async () => {
    await api.runImports();
    await meta.reload();
  };
  const configured = Object.keys(imports?.configured ?? {});
  const rows = configured.map((k) => imports?.sources.find((s) => s.source === k) ?? { source: k, label: k, status: "never" as const, detail: "Not imported yet.", last_attempt_at: null, last_success_at: null, records: 0 });
  return (
    <section className="glass rounded-3xl p-5" aria-labelledby="imp-h">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 id="imp-h" className="font-display text-xl font-bold">Discover imports</h2>
          <p className="text-sm text-ink-soft">Provider searches that add unreviewed records to Discover. If one fails, earlier results stay searchable.</p>
        </div>
        <button className="btn-ghost ml-auto" onClick={run} disabled={imports?.running}>
          {imports?.running ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} {imports?.running ? "Importing" : "Refresh imports"}
        </button>
      </div>
      <ul className="mt-3 grid gap-3 md:grid-cols-3">
        {rows.map((r) => (
          <li key={r.source} className="rounded-2xl bg-white/75 p-3 text-sm">
            <div className="flex items-center gap-2 font-semibold">
              {r.status === "ok" ? <CheckCircle2 size={17} className="text-ok" /> : r.status === "error" ? <XCircle size={17} className="text-bad" /> : <HelpCircle size={17} className="text-ink-faint" />}
              {r.label}
              <span className="ml-auto text-xs font-normal text-ink-faint">{r.records} records</span>
            </div>
            <p className={`mt-1 break-words text-xs ${r.status === "error" ? "text-bad" : "text-ink-soft"}`}>{r.detail}</p>
            <p className="mt-1 text-xs text-ink-faint">
              {r.last_attempt_at ? `Tried ${timeAgo(r.last_attempt_at)}` : "Never tried"}{r.last_success_at ? ` · last success ${timeAgo(r.last_success_at)}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function SourcesPage() {
  const src = useApi(api.sources);

  useEffect(() => {
    if (!src.data?.running) return;
    const t = setInterval(src.reload, 1500);
    return () => clearInterval(t);
  }, [src.data?.running, src.reload]);

  const check = async () => {
    await api.checkSources();
    await src.reload();
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="max-w-[62ch]">
          <h1 className="text-4xl font-extrabold tracking-tight">Source health</h1>
          <p className="mt-1 text-ink-soft">
            Checks that each pack's official source still answers and that small API queries return the expected fields. Checking also probes every Discover record's source page.
            Requests go out from the machine running the API.
          </p>
        </div>
        <button className="btn-clay ml-auto bg-peri" onClick={check} disabled={src.data?.running}>
          {src.data?.running ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
          {src.data?.running ? "Checking sources" : "Check sources now"}
        </button>
      </div>
      <LiveProvidersPanel />
      <ImportsPanel />
      {src.loading && <Spinner />}
      {src.error && <ErrorBox message={src.error} />}
      {src.data && !src.data.results.length && !src.data.running && (
        <div className="glass rounded-3xl p-8 text-center text-ink-soft">No checks yet. Run one to see whether NASA, UCI and Kaggle are reachable from here.</div>
      )}
      {src.data?.checked_at && <p className="text-sm text-ink-soft">Last checked {timeAgo(src.data.checked_at)}.</p>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {src.data?.results.map((r) => {
          const s = STATUS[r.status];
          return (
            <article key={r.slug} className="glass rounded-3xl p-5">
              <div className={`flex items-center gap-2 font-semibold ${s.cls}`}>{s.icon}{s.label}</div>
              <h2 className="mt-2 text-xl font-bold"><Link to={`/packs/${r.slug}`} className="hover:underline">{r.title}</Link></h2>
              <p className="text-sm text-ink-soft">{r.provider} · {r.access_method}</p>
              <ul className="mt-3 space-y-2">
                {r.probes.map((p) => (
                  <li key={p.url} className="rounded-2xl bg-white/75 p-3 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold capitalize">{p.kind}</span>
                      <span className="tabular-nums text-ink-faint">{p.status ?? "no response"} · {p.ms} ms</span>
                    </div>
                    <p className={`mt-1 break-words ${p.ok ? "text-ink-soft" : "text-bad"}`}>{p.detail}</p>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </div>
  );
}
