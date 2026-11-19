/** Why a queued run hasn't started. Hosted runs are executed by a separate worker, so "Queued" must say whether one is there. */
import { Clock, Hourglass, ServerOff } from "lucide-react";
import type { QueueInfo } from "../types";

const WARNING: Record<string, string> = {
  database: "The worker is connected to a different database than this app (DATABASE_URL must match).",
  blob_token: "The worker's BLOB_READ_WRITE_TOKEN differs from this app's, so it can't read uploaded files.",
  secret_key: "The worker's DSP_SECRET_KEY differs from this app's, so it can't use connected Kaggle accounts.",
};

function waited(seconds: number | null): string | null {
  if (seconds == null || seconds < 5) return null;
  return seconds < 90 ? `${Math.round(seconds)} s` : seconds < 5400 ? `${Math.round(seconds / 60)} min` : `${(seconds / 3600).toFixed(1)} h`;
}

export function QueueNotice({ queue }: { queue?: QueueInfo | null }) {
  if (!queue || queue.state === "inline") return null;
  const stuck = queue.state === "none" || queue.state === "offline";
  const Icon = stuck ? ServerOff : queue.state === "busy" ? Hourglass : Clock;
  const w = waited(queue.waitingSeconds);
  return (
    <div role="status" className={`mt-3 rounded-2xl border px-4 py-3 text-sm ${stuck ? "border-bad/30 bg-bad/5" : "border-white bg-white/70"}`}>
      <p className="flex items-center gap-2 font-semibold"><Icon size={15} aria-hidden /> {queue.headline}{w ? <span className="font-normal text-ink-soft"> · waiting {w}</span> : null}</p>
      <p className="mt-1 text-ink-soft [overflow-wrap:anywhere]">{queue.detail}</p>
      {queue.warnings.map((k) => <p key={k} className="mt-1 text-bad">{WARNING[k]}</p>)}
    </div>
  );
}
