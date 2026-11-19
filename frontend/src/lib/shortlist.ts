import { useEffect, useState } from "react";

const KEY = "dsp:shortlist";
const TITLES = "dsp:shortlist-titles";

export function rememberTitle(id: string, title: string) {
  try {
    const m = JSON.parse(localStorage.getItem(TITLES) ?? "{}");
    m[id] = title;
    localStorage.setItem(TITLES, JSON.stringify(m));
  } catch {
    /* ignore */
  }
}

export function titleOf(id: string): string {
  try {
    return JSON.parse(localStorage.getItem(TITLES) ?? "{}")[id] ?? id;
  } catch {
    return id;
  }
}
const EVENT = "dsp-shortlist";
export const SHORTLIST_MAX = 3;

function read(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.slice(0, SHORTLIST_MAX) : [];
  } catch {
    return [];
  }
}

function write(ids: string[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    /* storage unavailable: the shortlist lives for this page only */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: ids }));
}

/** Up to three dataset ids, saved locally and shared across tabs/components. */
export function useShortlist() {
  const [ids, setIds] = useState<string[]>(read);
  useEffect(() => {
    const sync = (e: Event) => setIds((e as CustomEvent<string[]>).detail ?? read());
    const storage = (e: StorageEvent) => e.key === KEY && setIds(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", storage);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", storage);
    };
  }, []);
  const toggle = (id: string, title?: string) => {
    if (title) rememberTitle(id, title);
    const cur = read();
    if (cur.includes(id)) write(cur.filter((x) => x !== id));
    else if (cur.length < SHORTLIST_MAX) write([...cur, id]);
  };
  return { ids, toggle, has: (id: string) => ids.includes(id), full: ids.length >= SHORTLIST_MAX, clear: () => write([]), set: write };
}
