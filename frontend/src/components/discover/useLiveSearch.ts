import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { SessionCache } from "../../lib/session";
import type { LiveProvider, LiveResult } from "../../types";

export type LiveState = Record<string, { state: "searching" | "done"; result?: LiveResult; error?: string }>;

// Last known provider status per topic, for this browser session.
const liveCache = new SessionCache<LiveState>("dsp:live", 30);

/**
 * Query every live provider in parallel for the current topic. Each provider reports back on its
 * own; `onSettled` fires per provider so the caller can refresh results as they arrive.
 * A topic searched earlier in this session shows its last status at once and refreshes quietly.
 */
export function useLiveSearch(q: string, topic: string | null, providers: LiveProvider[] | undefined, onSettled: () => void) {
  const [status, setStatus] = useState<LiveState>(() => (topic ? liveCache.get(topic) ?? {} : {}));
  const [refreshing, setRefreshing] = useState(false);
  const runKey = useRef<string | null>(null);
  const settled = useRef(onSettled);
  settled.current = onSettled;

  const start = useCallback(
    (refresh = false) => {
      if (!providers || topic === null) return;
      if (!topic.trim()) {
        setStatus({});
        return;
      }
      const active = providers.filter((p) => p.configured);
      const cached = !refresh ? liveCache.get(topic) : undefined;
      const quiet = !!cached && Object.values(cached).every((e) => e.state === "done");
      const init: LiveState = {};
      for (const p of providers) {
        init[p.key] = p.configured
          ? quiet && cached?.[p.key] ? cached[p.key] : { state: "searching" }
          : { state: "done", result: { provider: p.key, label: p.label, status: "not-configured", detail: p.note ?? "Not configured", count: 0, ids: [] } };
      }
      setStatus(init);
      setRefreshing(quiet);
      const key = `${topic}|${Date.now()}`;
      runKey.current = key;
      let pending = active.length;
      let acc = init;
      const finish = (patch: LiveState[string], provider: string) => {
        if (runKey.current !== key) return;
        acc = { ...acc, [provider]: patch };
        setStatus(acc);
        if (--pending === 0) {
          liveCache.set(topic, acc);
          setRefreshing(false);
        }
        settled.current();
      };
      for (const p of active) {
        api.liveSearch(p.key, q, topic, refresh)
          .then((r) => finish({ state: "done", result: r }, p.key))
          .catch((e: Error) => finish({ state: "done", error: e.message }, p.key));
      }
      if (!active.length) liveCache.set(topic, init);
    },
    [providers, q, topic],
  );

  const lastTopic = useRef<string | null>(null);
  useEffect(() => {
    if (!providers || topic === null || topic === lastTopic.current) return;
    lastTopic.current = topic;
    start(false);
  }, [providers, topic, start]);

  const entries = Object.values(status);
  const done = entries.length === 0 || entries.every((e) => e.state === "done");
  return { status, done, refreshing, rerun: () => start(true) };
}
