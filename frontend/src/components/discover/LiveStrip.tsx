import { CheckCircle2, ChevronDown, CircleSlash, Clock3, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";
import { timeAgo } from "../../api";
import type { LiveProvider } from "../../types";
import type { LiveState } from "./useLiveSearch";

const short = (p: LiveProvider) => p.label.split(" (")[0];

/** One compact line ("Searching 3 sources…"); per-source details expand on demand. */
export default function LiveStrip({ providers, status, done, refreshing, onRerun }: {
  providers: LiveProvider[];
  status: LiveState;
  done: boolean;
  refreshing?: boolean;
  onRerun: () => void;
}) {
  const [open, setOpen] = useState(false);
  if (!Object.keys(status).length) return null;
  const configured = providers.filter((p) => status[p.key]?.result?.status !== "not-configured");
  const searching = providers.filter((p) => status[p.key]?.state === "searching");
  const failed = providers.filter((p) => status[p.key]?.error || status[p.key]?.result?.status === "error");
  const found = configured.reduce((n, p) => n + (status[p.key]?.result?.count ?? 0), 0);

  let summary: string;
  if (!done) summary = `Searching ${searching.length} source${searching.length === 1 ? "" : "s"}…`;
  else if (failed.length) summary = `${configured.length - failed.length} of ${configured.length} sources answered · ${failed.map(short).join(", ")} unavailable`;
  else summary = `${configured.length} sources searched · ${found} found`;

  return (
    <div className="glass rounded-2xl px-3 py-2" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {!done ? <Loader2 size={15} className="animate-spin text-peri" /> : failed.length ? <XCircle size={15} className="text-bad" /> : <CheckCircle2 size={15} className="text-ok" />}
        <span className="font-semibold">{summary}</span>
        {refreshing && <span className="text-xs text-ink-faint">refreshing…</span>}
        <button className="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-ink-soft hover:bg-white"
          onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          Details <ChevronDown size={13} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
        </button>
        {done && (
          <button className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-ink-soft hover:bg-white" onClick={onRerun}
            title="Ignore cached results and ask every source again">
            <RefreshCw size={13} /> Search again
          </button>
        )}
      </div>
      {open && (
        <ul className="mt-2 flex flex-wrap gap-2 border-t border-white/80 pt-2">
          {providers.map((p) => {
            const s = status[p.key];
            const r = s?.result;
            let icon = <Loader2 size={14} className="animate-spin text-peri" />;
            let text = "searching";
            let cls = "bg-white/80";
            if (s?.state === "done") {
              if (s.error || r?.status === "error") {
                icon = <XCircle size={14} className="text-bad" />;
                text = r?.stale ? `failed, ${r.count} earlier results kept` : "unavailable";
                cls = "bg-bad/10";
              } else if (r?.status === "not-configured") {
                icon = <CircleSlash size={14} className="text-ink-faint" />;
                text = "not configured";
                cls = "bg-white/50";
              } else if (r?.status === "cached") {
                icon = <Clock3 size={14} className="text-peri-ink" />;
                text = `${r.count}, cached ${timeAgo(r.fetched_at)}`;
              } else {
                icon = <CheckCircle2 size={14} className="text-ok" />;
                text = `${r?.count ?? 0}${r?.ms ? ` in ${(r.ms / 1000).toFixed(1)} s` : ""}`;
              }
            }
            return (
              <li key={p.key} className={`inline-flex items-center gap-1.5 rounded-full border border-white px-3 py-1 text-xs ${cls}`}
                title={s?.error ?? r?.detail ?? p.note ?? ""}>
                {icon}
                <span className="font-semibold">{short(p)}</span>
                <span className="text-ink-soft">{text}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
