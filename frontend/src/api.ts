import { useCallback, useEffect, useRef, useState } from "react";
import { SessionCache } from "./lib/session";
import type {
  AnalysisListItem, AnalysisRun, Capabilities, ComparisonItem, ComparisonReport, ComparisonSummary, DataStatus, DatasetDetail, DiscoverMeta,
  FileList, InspectResult, KaggleStatus, LimitDetail, LiveProvider, LiveResult, PreviewData, Mode, Pack, PackDetail, Run, RunParams, SearchCriteria,
  SearchResponse, SourceCheck, Stats, User,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

/** The Blob client's errors are terse; say which side is wrong (the server's message from /api/blob/upload-token is kept). */
function uploadFailure(e: Error): string {
  const m = e.message || "";
  if (/not configured|BLOB_READ_WRITE_TOKEN/i.test(m)) return m;
  if (/expired|invalid.*token|client token/i.test(m)) return "The upload token expired or was rejected. Reload the page and upload again; if it keeps happening, the app's BLOB_READ_WRITE_TOKEN is wrong.";
  if (/quota|402|limit/i.test(m)) return "The Blob store refused the upload (quota or plan limit). Check storage usage in the Vercel dashboard.";
  if (/Failed to fetch|NetworkError|network/i.test(m)) return "The browser couldn't reach Vercel Blob. Check the connection and try again; the file was not stored.";
  return `Upload to private storage failed: ${m || "unknown error"}`;
}

export class ApiError extends Error {
  /** Machine-readable reason from the API (auth, consent, timeout, too_large, not_found, format, network, login_required). */
  kind?: string;
  /** For limits: which one, the measured size, next actions. For consent: the provider page. */
  detail?: LimitDetail | null;
  constructor(message: string, public status: number, kind?: string, detail?: LimitDetail | null) {
    super(message);
    this.kind = kind;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  } catch {
    throw new ApiError("Can't reach the API. Start the backend (uvicorn app.main:app --port 8000) and refresh.", 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    let kind: string | undefined;
    let extra: LimitDetail | null = null;
    try {
      const body = await res.json();
      if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        detail = body.detail.message;
        kind = body.detail.kind;
        extra = body.detail.detail ?? null;
      } else {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status, kind, extra);
  }
  return res.json() as Promise<T>;
}

/** Decimal units, matching the API's limit messages (2 GB = 2,000,000,000 bytes). */
export function sizeLabel(n: number | null | undefined): string {
  if (n == null) return "an unknown size";
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i++; }
  return i === 0 ? `${v.toLocaleString()} bytes` : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${units[i]}`;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  url: (path: string) => `${BASE}${path}`,
  packs: () => request<Pack[]>("/api/packs"),
  pack: (slug: string) => request<PackDetail>(`/api/packs/${slug}`),
  stats: () => request<Stats>("/api/stats"),
  runs: (slug?: string) => request<Run[]>(`/api/runs${slug ? `?slug=${slug}` : ""}`),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  log: (id: string, offset: number) => request<{ text: string; offset: number }>(`/api/runs/${id}/log?offset=${offset}`),
  startRun: (slug: string, mode: Mode, params: Record<string, string>) =>
    request<Run>(`/api/packs/${slug}/runs`, json({ mode, params })),
  /** Starts a queued small run on the site itself (no worker). Resolves when the run ends; errors are ignored by callers. */
  driveRun: (kind: "pack" | "analysis", id: string) =>
    request<{ driver: string; status: string }>(kind === "pack" ? `/api/runs/${id}/drive` : `/api/analyses/${id}/drive`, { method: "POST" }),
  cancelRun: (id: string) => request<{ canceled: boolean }>(`/api/runs/${id}/cancel`, { method: "POST" }),
  deleteRun: (id: string) => request<{ deleted: string }>(`/api/runs/${id}`, { method: "DELETE" }),
  dataStatus: (slug: string) => request<DataStatus>(`/api/packs/${slug}/data`),
  clearData: (slug: string) => request<DataStatus>(`/api/packs/${slug}/data`, { method: "DELETE" }),
  upload: (slug: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ ok: boolean; missing: string[]; output: string; data_status: DataStatus }>(
      `/api/packs/${slug}/upload`,
      { method: "POST", body: form },
    );
  },
  sources: () => request<{ checked_at: string | null; running: boolean; results: SourceCheck[] }>("/api/sources"),
  checkSources: () => request<{ started: boolean }>("/api/sources/check", { method: "POST" }),
  // discovery
  parse: (q: string) => request<SearchCriteria>(`/api/criteria/parse?q=${encodeURIComponent(q)}`),
  discoverMeta: () => request<DiscoverMeta>("/api/discover/meta"),
  datasets: (query: string) => request<SearchResponse>(`/api/datasets?${query}`),
  dataset: (id: string, query = "") => request<DatasetDetail>(`/api/datasets/${encodeURIComponent(id)}${query ? `?${query}` : ""}`),
  compare: (ids: string[], query = "") =>
    request<{ items: DatasetDetail[] }>(`/api/datasets/compare?ids=${ids.map(encodeURIComponent).join(",")}${query ? `&${query}` : ""}`),
  checkDataset: (id: string) =>
    request<{ ok: boolean; status: number | null; detail: string; ms: number }>(`/api/datasets/${encodeURIComponent(id)}/check`, { method: "POST" }),
  runImports: () => request<{ started: boolean }>("/api/imports/run", { method: "POST" }),
  // live providers + on-demand files
  liveProviders: () => request<LiveProvider[]>("/api/live/providers"),
  liveSearch: (provider: string, q: string, topic: string, refresh = false) =>
    request<LiveResult>(`/api/live/search?${new URLSearchParams({ provider, q, topic, ...(refresh ? { refresh: "true" } : {}) })}`),
  preview: (id: string) => request<PreviewData>(`/api/datasets/${encodeURIComponent(id)}/preview`),
  files: (id: string, opts: { refresh?: boolean; offset?: number; limit?: number; q?: string } = {}) => {
    const qs = new URLSearchParams();
    if (opts.refresh) qs.set("refresh", "true");
    if (opts.offset) qs.set("offset", String(opts.offset));
    if (opts.limit) qs.set("limit", String(opts.limit));
    if (opts.q) qs.set("q", opts.q);
    return request<FileList>(`/api/datasets/${encodeURIComponent(id)}/files${qs.toString() ? `?${qs}` : ""}`);
  },
  inspect: (id: string, fileUrl: string) => request<InspectResult>(`/api/datasets/${encodeURIComponent(id)}/inspect`, json({ fileUrl })),
  analyze: (id: string, fileUrl: string, mode: "sample" | "full" = "sample", params: RunParams = {}) =>
    request<{ runId: string }>(`/api/datasets/${encodeURIComponent(id)}/analyze`, json({ fileUrl, mode, ...params })),
  cancelAnalysis: (runId: string) => request<{ cancelRequested: string }>(`/api/analyses/${runId}/cancel`, { method: "POST" }),
  retryAnalysis: (runId: string, mode?: "sample" | "full", extra: { prepare?: boolean; members?: string[] } = {}) =>
    request<{ runId: string }>(`/api/analyses/${runId}/retry`, json({ mode: mode ?? null, ...extra })),
  // accounts and provider connections (session cookie is HttpOnly; nothing is kept in browser storage)
  me: () => request<{ user: User | null }>("/api/auth/me"),
  signUp: (email: string, password: string) => request<{ user: User }>("/api/auth/signup", json({ email, password })),
  logIn: (email: string, password: string) => request<{ user: User }>("/api/auth/login", json({ email, password })),
  logOut: () => request<{ user: null }>("/api/auth/logout", { method: "POST" }),
  kaggle: () => request<KaggleStatus>("/api/connections/kaggle"),
  connectKaggle: (body: { token?: string; username?: string; key?: string; kaggleJson?: string }) =>
    request<KaggleStatus>("/api/connections/kaggle", json(body)),
  disconnectKaggle: () => request<KaggleStatus>("/api/connections/kaggle", { method: "DELETE" }),
  kaggleOAuthUrl: (returnTo: string) => `${BASE}/api/kaggle/oauth/start?returnTo=${encodeURIComponent(returnTo)}`,
  /** Upload a downloaded file. On Vercel with a Blob store the browser sends it straight to Blob (no 4.5 MB body limit). */
  analyzeUpload: async (id: string, file: File, caps?: Capabilities, onProgress?: (pct: number) => void) => {
    if (caps?.maxTransferBytes && file.size > caps.maxTransferBytes) {  // same limit in both modes; say so before sending bytes
      throw new ApiError(`${file.name} is ${sizeLabel(file.size)}, over the ${sizeLabel(caps.maxTransferBytes)} transfer limit (DSP_MAX_TRANSFER_BYTES).`, 413,
        "too_large", { limit: "transfer", limitBytes: caps.maxTransferBytes, measuredBytes: file.size, actions: ["open_source"] });
    }
    if (caps?.uploadMode === "blob") {
      const { upload } = await import("@vercel/blob/client");
      let blob;
      try {
        blob = await upload(`uploads/${id.replace(/[^A-Za-z0-9._-]+/g, "_")}/${file.name}`, file, {
          access: "private",
          handleUploadUrl: `${BASE}/api/blob/upload-token`,
          multipart: file.size > 50 * 1024 * 1024,
          onUploadProgress: (e) => onProgress?.(e.percentage),
        });
      } catch (e) {
        throw new ApiError(uploadFailure(e as Error), 502, "upload");
      }
      return request<{ runId: string }>(`/api/datasets/${encodeURIComponent(id)}/analyze/blob`, json({ url: blob.url, name: file.name }));
    }
    if (caps && file.size > caps.directUploadMaxMB * 2 ** 20) {
      throw new Error(`This deployment accepts direct uploads up to ${caps.directUploadMaxMB} MB. Connect a private Vercel Blob store to upload larger files.`);
    }
    const form = new FormData();
    form.append("file", file);
    return request<{ runId: string }>(`/api/datasets/${encodeURIComponent(id)}/analyze/upload`, { method: "POST", body: form });
  },
  analysis: (runId: string, lite = false) => request<AnalysisRun>(`/api/analyses/${runId}${lite ? "?view=lite" : ""}`),
  analysisDetails: (runId: string) => request<{ preview: unknown[][]; columns: string[] }>(`/api/analyses/${runId}/details`),
  analyses: (datasetId?: string) => request<AnalysisListItem[]>(`/api/analyses${datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : ""}`),
  // comparisons
  currentComparison: (ids: string[], criteria = "") =>
    request<{ items: ComparisonItem[] }>(`/api/comparisons/current?${new URLSearchParams({ ids: ids.join(","), criteria })}`),
  saveComparison: (ids: string[], criteria: string, name?: string) =>
    request<ComparisonReport>("/api/comparisons", json({ ids, criteria, name: name || null })),
  comparisons: () => request<ComparisonSummary[]>("/api/comparisons"),
  comparison: (id: string) => request<ComparisonReport>(`/api/comparisons/${id}`),
  deleteComparison: (id: string) => request<{ deleted: string }>(`/api/comparisons/${id}`, { method: "DELETE" }),
};

// Search results per URL, kept for the browser session so switching tabs or refreshing renders
// instantly (and the router can restore scroll position); a background request then refreshes them.
export const searchCache = new SessionCache<SearchResponse>("dsp:search");
let metaCache: DiscoverMeta | null = null;

// One /api/discover/meta request shared by every component on the page, refreshed at most once a minute
// (each component used to fetch it on mount: several identical requests per page, each a function call on Vercel).
let metaInflight: Promise<DiscoverMeta> | null = null;
let metaAt = 0;
function loadMeta(): Promise<DiscoverMeta> {
  if (metaCache && Date.now() - metaAt < 60_000) return Promise.resolve(metaCache);
  if (!metaInflight) {
    metaInflight = api.discoverMeta()
      .then((m) => { metaCache = m; metaAt = Date.now(); return m; })
      .finally(() => { metaInflight = null; });
  }
  return metaInflight;
}

export function useDiscoverMeta() {
  const [meta, setMeta] = useState<DiscoverMeta | null>(metaCache);
  useEffect(() => {
    let live = true;
    loadMeta().then((m) => { if (live) setMeta(m); }).catch(() => { });
    return () => { live = false; };
  }, []);
  return meta;
}

/** Fetch on mount + whenever deps change; exposes reload(). */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    setLoading(true);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

export const fmtBytes = (n: number) =>
  n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n > 1e3 ? `${(n / 1e3).toFixed(0)} KB` : `${n} B`;

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
