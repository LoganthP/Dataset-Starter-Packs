import { useEffect, useRef } from "react";
import { api } from "../api";
import type { QueueInfo } from "../types";

/**
 * A queued run the server says can run on the site itself (queue.state === "inline") is started from here: one request that
 * stays open until the run ends. Reloading the page drives it again, which is safe (the server claims a run only once), and a
 * connected worker takes the job instead when there is one.
 */
export function useInlineDrive(kind: "pack" | "analysis", run: { id: string; status: string; queue?: QueueInfo | null } | null | undefined) {
  const driven = useRef<string | null>(null);
  useEffect(() => {
    if (!run || run.status !== "queued" || run.queue?.state !== "inline" || driven.current === run.id) return;
    driven.current = run.id;
    api.driveRun(kind, run.id).catch(() => { driven.current = null; });  // polling shows the real state either way
  }, [kind, run?.id, run?.status, run?.queue?.state]);  // eslint-disable-line react-hooks/exhaustive-deps
}
