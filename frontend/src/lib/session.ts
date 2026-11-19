/**
 * Browser-session memory (sessionStorage): the last Discover / Curated Packs URL, search results
 * per URL, and live-source status per topic. Everything survives tab switches and refresh, and is
 * forgotten when the browser session ends. Writes never throw (private mode, quota).
 */

function read<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota or storage disabled: keep working in memory */
  }
}

export type Section = "discover" | "packs";
export const SECTION_PATH: Record<Section, string> = { discover: "/discover", packs: "/packs" };

export function rememberSectionUrl(section: Section, search: string) {
  write(`dsp:last:${section}`, search);
}

/** Where the nav link for a section should go: its last URL in this session. */
export function sectionHref(section: Section) {
  const s = read<string>(`dsp:last:${section}`);
  return `${SECTION_PATH[section]}${s && s !== "?" ? (s.startsWith("?") ? s : `?${s}`) : ""}`;
}

export function forgetSection(section: Section) {
  write(`dsp:last:${section}`, null);
}

/** A small Map-like cache mirrored to sessionStorage (keeps the newest `limit` entries). */
export class SessionCache<V> {
  private mem = new Map<string, V>();
  constructor(private prefix: string, private limit = 24) {}

  private index(): string[] {
    return read<string[]>(`${this.prefix}:index`) ?? [];
  }

  get(key: string): V | undefined {
    if (this.mem.has(key)) return this.mem.get(key);
    const v = read<V>(`${this.prefix}:${key}`);
    if (v !== null) this.mem.set(key, v);
    return v ?? undefined;
  }

  has(key: string) {
    return this.get(key) !== undefined;
  }

  set(key: string, value: V) {
    this.mem.set(key, value);
    const idx = [key, ...this.index().filter((k) => k !== key)];
    for (const old of idx.slice(this.limit)) {
      write(`${this.prefix}:${old}`, null);
      this.mem.delete(old);
    }
    write(`${this.prefix}:index`, idx.slice(0, this.limit));
    write(`${this.prefix}:${key}`, value);
  }

  clear() {
    for (const k of this.index()) write(`${this.prefix}:${k}`, null);
    write(`${this.prefix}:index`, null);
    this.mem.clear();
  }
}
