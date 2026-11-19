import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, FileJson, Maximize2, X, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Results } from "../types";
import { ModeBadge } from "./ui";

function fmt(v: unknown) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return String(v);
}

function Lightbox({ src, title, onClose }: { src: string; title: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4 backdrop-blur-sm"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <motion.figure
        initial={{ scale: 0.92, y: 12 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0 }}
        transition={{ type: "spring", stiffness: 260, damping: 24 }}
        className="glass-strong max-h-full max-w-6xl overflow-auto rounded-3xl p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between gap-4">
          <figcaption className="font-display text-lg font-bold">{title}</figcaption>
          <button className="btn-ghost" onClick={onClose} autoFocus>
            <X size={16} /> Close
          </button>
        </div>
        <img src={src} alt={title} className="rounded-2xl bg-paper" />
      </motion.figure>
    </motion.div>
  );
}

export default function ResultsView({ runId, results }: { runId: string; results: Results }) {
  const [open, setOpen] = useState<{ src: string; title: string } | null>(null);
  const file = (name: string) => api.url(`/api/runs/${runId}/files/${name}`);
  const passed = results.checks.filter((c) => c.passed).length;

  return (
    <section className="space-y-5" aria-label="Results">
      <div className="glass-strong rounded-3xl p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <ModeBadge sample={results.is_sample} />
          <span className="text-xs text-ink-faint">Generated {new Date(results.generated_at).toLocaleString()}</span>
          <a className="btn-ghost ml-auto" href={file("results.json")} download>
            <FileJson size={15} /> results.json
          </a>
        </div>
        <p className="mt-3 font-display text-xl font-semibold leading-snug sm:text-2xl">{results.headline}</p>
        {results.is_sample && (
          <p className="mt-2 text-sm text-ink-soft">
            These numbers come from invented data. They show the pipeline works, not how the real dataset behaves.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {results.metrics.map((m, i) => (
          <div key={m.key} className={`glass rounded-3xl p-4 ${i < 2 ? "md:col-span-1" : ""}`} title={m.hint}>
            <p className="text-sm text-ink-soft">{m.label}</p>
            <p className="mt-1 font-display text-3xl font-bold leading-none">
              {fmt(m.value)}
              {m.unit && <span className="ml-1 text-base font-semibold text-ink-faint">{m.unit}</span>}
            </p>
            {m.hint && <p className="mt-2 text-xs leading-snug text-ink-faint">{m.hint}</p>}
          </div>
        ))}
      </div>

      <div className="glass rounded-3xl p-5">
        <h3 className="text-lg font-bold">
          Trap checks <span className="font-body text-sm font-semibold text-ink-soft">{passed} of {results.checks.length} passed</span>
        </h3>
        <ul className="mt-3 grid gap-2 md:grid-cols-3">
          {results.checks.map((c) => (
            <li key={c.name} className="flex gap-3 rounded-2xl bg-white/75 p-3">
              {c.passed ? <CheckCircle2 className="shrink-0 text-ok" size={20} /> : <XCircle className="shrink-0 text-bad" size={20} />}
              <div>
                <p className="text-sm font-semibold">{c.name}</p>
                <p className="text-xs text-ink-soft">{c.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {results.charts.map((c, i) => (
          <figure key={c.file} className={`glass rounded-3xl p-3 ${i === 0 && results.charts.length % 2 === 1 ? "lg:col-span-2" : ""}`}>
            <button
              className="group relative block w-full overflow-hidden rounded-2xl bg-white"
              onClick={() => setOpen({ src: file(c.file), title: c.title })}
              aria-label={`Enlarge chart: ${c.title}`}
            >
              <img src={file(c.file)} alt={c.title} className="mx-auto max-h-[460px] w-auto rounded-xl bg-paper" loading="lazy" />
              <span className="absolute right-2 top-2 rounded-lg bg-white/90 p-1.5 opacity-0 transition-opacity group-hover:opacity-100">
                <Maximize2 size={16} />
              </span>
            </button>
            <figcaption className="px-2 pb-1 pt-3">
              <span className="font-semibold">{c.title}.</span> <span className="text-sm text-ink-soft">{c.caption}</span>
            </figcaption>
          </figure>
        ))}
      </div>

      <div className="space-y-3">
        {results.tables.map((t, i) => (
          <details key={t.title} className="glass group rounded-3xl p-4" open={i === 0 && t.rows.length <= 12}>
            <summary className="cursor-pointer select-none font-display text-lg font-bold">{t.title}</summary>
            <div className="mt-3 max-h-[420px] overflow-auto rounded-2xl bg-white/80">
              {t.columns.length === 1 && t.columns[0] === "sql" ? (
                <pre className="p-4 text-[13px] leading-6">{String(t.rows[0][0])}</pre>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      {t.columns.map((c, ci) => (
                        <th key={c} className={`sticky top-0 border-b border-sky-deep bg-white px-3 py-2 font-semibold ${typeof t.rows[0]?.[ci] === "number" ? "text-right" : "text-left"}`}>{c.replaceAll("_", " ")}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {t.rows.map((r, ri) => (
                      <tr key={ri} className="odd:bg-sky-wash/50">
                        {r.map((v, vi) => (
                          <td key={vi} className={`px-3 py-1.5 ${typeof v === "number" ? "text-right tabular-nums" : ""}`}>{fmt(v)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </details>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Notes</h3>
          <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-ink-soft">
            {results.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </div>
        <div className="glass rounded-3xl p-5">
          <h3 className="text-lg font-bold">Where this data came from</h3>
          <dl className="mt-2 space-y-1 text-sm">
            {Object.entries(results.provenance).map(([k, v]) => (
              <div key={k} className="grid grid-cols-[9rem_1fr] gap-2">
                <dt className="text-ink-faint">{k.replaceAll("_", " ")}</dt>
                <dd className="break-all text-ink-soft">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      <AnimatePresence>{open && <Lightbox {...open} onClose={() => setOpen(null)} />}</AnimatePresence>
    </section>
  );
}
