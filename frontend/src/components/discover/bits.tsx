import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import type { EvidenceStatus, Fit, Reason } from "../../types";

export const FIT_STYLE: Record<Fit, { label: string; cls: string; icon: ReactNode; hint: string }> = {
  meets: { label: "Meets requirements", cls: "text-ok", icon: <CheckCircle2 size={18} />, hint: "Every required criterion is supported by the source." },
  "needs-verification": {
    label: "Needs verification",
    cls: "text-warn",
    icon: <AlertCircle size={18} />,
    hint: "At least one requirement isn't confirmed by the source yet.",
  },
  "does-not-meet": { label: "Doesn't meet", cls: "text-ink-faint", icon: <XCircle size={18} />, hint: "The source shows a required criterion isn't satisfied." },
};

export function OutcomeIcon({ outcome, size = 15 }: { outcome: Reason["outcome"]; size?: number }) {
  if (outcome === "met") return <CheckCircle2 size={size} className="shrink-0 text-ok" aria-label="Met" />;
  if (outcome === "unverified") return <CircleHelp size={size} className="shrink-0 text-warn" aria-label="Unverified" />;
  return <XCircle size={size} className="shrink-0 text-bad" aria-label="Not met" />;
}

export function EvidenceBadge({ status }: { status: EvidenceStatus }) {
  const map = {
    verified: { t: "Verified", c: "bg-ok/12 text-ok", title: "Checked by this project: a pack loader validated it against the data." },
    "provider-reported": { t: "Provider-reported", c: "bg-peri/15 text-peri-ink", title: "Stated by the publisher; see the evidence link." },
    unknown: { t: "Unknown", c: "bg-sun/50 text-warn-ink", title: "Not established. Check the source before relying on it." },
  }[status];
  return (
    <span title={map.title} className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-bold ${map.c}`}>
      {map.t}
    </span>
  );
}

export function SkeletonRows({ n = 4 }: { n?: number }) {
  return (
    <ul className="space-y-3" aria-hidden>
      {Array.from({ length: n }).map((_, i) => (
        <li key={i} className="glass animate-pulse rounded-3xl p-5">
          <div className="h-5 w-2/5 rounded-lg bg-white/90" />
          <div className="mt-3 h-3.5 w-4/5 rounded bg-white/80" />
          <div className="mt-2 h-3.5 w-3/5 rounded bg-white/70" />
          <div className="mt-4 flex gap-2">
            <div className="h-6 w-24 rounded-full bg-white/80" />
            <div className="h-6 w-20 rounded-full bg-white/80" />
            <div className="h-6 w-28 rounded-full bg-white/80" />
          </div>
        </li>
      ))}
    </ul>
  );
}

export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s.length <= 10 ? `${s}T00:00:00` : s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "Unknown";

/** Render `field_name` spans from explanation text as inline code. */
export function RichText({ text }: { text: string }) {
  const parts = text.split(/`([^`]+)`/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? <code key={i} className="rounded-md bg-sky-deep/70 px-1 py-px text-[0.92em] text-ink">{p}</code> : <span key={i}>{p}</span>,
      )}
    </>
  );
}
