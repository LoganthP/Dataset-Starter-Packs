import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api";
import type { RunStatus } from "../types";

export const PROVIDER_TINT: Record<string, string> = {
  NASA: "#0EA5E9",
  UCI: "#7C83FD",
  Kaggle: "#F97316",
};

export function StatusPill({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, { label: string; cls: string; icon: ReactNode }> = {
    queued: { label: "Queued", cls: "bg-white/80 text-ink-soft", icon: <CircleDashed size={14} /> },
    running: { label: "Running", cls: "bg-peri/15 text-peri-ink", icon: <Loader2 size={14} className="animate-spin" /> },
    succeeded: { label: "Succeeded", cls: "bg-ok/12 text-ok", icon: <CheckCircle2 size={14} /> },
    failed: { label: "Failed", cls: "bg-bad/12 text-bad", icon: <XCircle size={14} /> },
    canceled: { label: "Canceled", cls: "bg-white/80 text-ink-faint", icon: <XCircle size={14} /> },
  };
  const s = map[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${s.cls}`}>
      {s.icon}
      {s.label}
    </span>
  );
}

export function ModeBadge({ sample }: { sample: boolean }) {
  return sample ? (
    <span className="inline-flex items-center rounded-full bg-sun/70 px-2.5 py-1 text-xs font-bold text-warn-ink">Synthetic sample</span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-aqua/30 px-2.5 py-1 text-xs font-bold text-aqua-ink">Real data</span>
  );
}

export function ErrorBox({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div role="alert" className="glass-strong flex items-start gap-3 rounded-2xl p-4 text-sm">
      <AlertTriangle className="mt-0.5 shrink-0 text-bad" size={18} />
      <div className="min-w-0 flex-1">
        <p className="whitespace-pre-wrap break-words">{message}</p>
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-soft" role="status">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  );
}

/** Markdown with pack-relative asset links rewritten to the API. */
export function Markdown({ children, slug }: { children: string; slug?: string }) {
  return (
    <div className="prose-pack">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) =>
          slug && url.startsWith("assets/") ? api.url(`/api/packs/${slug}/${url}`) : url
        }
        components={{
          a: ({ href, children }) => (
            <a href={href} target={href?.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
