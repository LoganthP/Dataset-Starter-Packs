import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Run } from "../types";

const DONE = new Set(["succeeded", "failed", "canceled"]);

/** Poll a run and stream its log until it finishes. */
export function useRunWatcher(runId: string | null) {
  const [run, setRun] = useState<Run | null>(null);
  const [log, setLog] = useState("");
  const [error, setError] = useState<string | null>(null);
  const offset = useRef(0);

  useEffect(() => {
    setRun(null);
    setLog("");
    setError(null);
    offset.current = 0;
    if (!runId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const chunk = await api.log(runId, offset.current);
        if (!alive) return;
        if (chunk.text) {
          offset.current = chunk.offset;
          setLog((l) => l + chunk.text);
        }
        const r = await api.run(runId);
        if (!alive) return;
        setRun(r);
        if (DONE.has(r.status)) {
          const rest = await api.log(runId, offset.current);
          if (alive && rest.text) setLog((l) => l + rest.text);
          return;
        }
      } catch (e) {
        if (!alive) return;
        setError((e as Error).message);
      }
      timer = setTimeout(tick, 700);
    };
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [runId]);

  const steps = [...log.matchAll(/\[(\d+)\/(\d+)\]\s*([^\n]*)/g)];
  const last = steps.at(-1);
  const progress = run?.status === "succeeded" ? 1 : last ? Number(last[1]) / Number(last[2]) : 0;
  return { run, log, error, progress, stepLabel: last?.[3] ?? "" };
}
