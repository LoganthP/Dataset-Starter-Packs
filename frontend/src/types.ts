export type Mode = "sample" | "real";
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export interface Param {
  name: string;
  label: string;
  type: "number" | "select" | "date" | "text";
  default?: string | number;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  help?: string;
  modes?: Mode[];
}

export interface Source {
  name: string;
  publisher: string;
  url: string;
  dataset_page: string;
  access_method: "direct-download" | "api" | "kaggle";
  license: string;
  license_url: string;
  doi: string | null;
  citation: string;
  files: string[];
  requires_credentials: boolean;
  manual_steps?: string[];
}

export interface LatestRun {
  slug: string;
  status: RunStatus;
  mode: Mode;
  headline: string | null;
  finished_at: string | null;
}

export interface Pack {
  slug: string;
  title: string;
  tagline: string;
  provider: string;
  difficulty: string;
  task_type: string;
  skills: string[];
  accent: string;
  question: string;
  audience: string;
  prerequisites: string[];
  estimated_time: string;
  expected_runtime: { sample: string; real: string };
  source: Source;
  fixture: boolean;
  last_source_check: string;
  lesson: { title: string; summary: string };
  outputs: string[];
  parameters: Param[];
  challenges: { title: string; description: string; outcome: string }[];
  has_preview: boolean;
  latest_run?: LatestRun | null;
  has_real_data?: boolean;
  error?: string;
}

export interface DataStatus {
  cached_files: { name: string; bytes: number; modified: string }[];
  provenance: Record<string, unknown>[];
  expected_files: string[];
  has_real_data: boolean;
}

export interface PackDetail extends Pack {
  documents: { readme: string; data_dictionary: string };
  data_status: DataStatus;
  github_url: string | null;
}

export interface Metric {
  key: string;
  label: string;
  value: number;
  unit: string;
  hint: string;
  better: "lower" | "higher" | null;
}

export interface Results {
  pack: string;
  mode: Mode;
  is_sample: boolean;
  generated_at: string;
  headline: string;
  metrics: Metric[];
  tables: { title: string; columns: string[]; rows: (string | number | null)[][] }[];
  charts: { file: string; title: string; caption: string }[];
  checks: { name: string; passed: boolean; detail: string }[];
  notes: string[];
  provenance: Record<string, unknown>;
}

/** Where a queued run stands (queue mode): waiting for a worker, or in line behind others. */
export interface QueueInfo {
  state: "none" | "offline" | "online" | "busy" | "inline";
  headline: string;
  detail: string;
  ahead: number;
  waitingSeconds: number | null;
  warnings: ("database" | "blob_token" | "secret_key")[];
}

export interface Run {
  id: string;
  slug: string;
  mode: Mode;
  params: Record<string, string>;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  exit_code: number | null;
  error: string | null;
  headline: string | null;
  is_sample: boolean | null;
  results?: Results | null;
  queue?: QueueInfo | null;
  worker_available?: boolean;
}

export interface SourceCheck {
  slug: string;
  title: string;
  provider: string;
  access_method: string;
  status: "ok" | "error" | "manual";
  checked_at: string;
  probes: { kind: string; url: string; ok: boolean; status: number | null; ms: number; detail: string }[];
}

export interface Stats {
  packs: number;
  providers: string[];
  skills: string[];
  total_runs: number;
  succeeded_runs: number;
  real_runs: number;
  source_check: { checked_at: string | null; running: boolean };
}

// ---------------------------------------------------------------- discovery
export type Fit = "meets" | "needs-verification" | "does-not-meet";
export type EvidenceStatus = "verified" | "provider-reported" | "unknown";

export interface Claim {
  status: EvidenceStatus;
  evidence?: string | null;
  note?: string | null;
}

export interface Reason {
  key: string;
  label: string;
  outcome: "met" | "unverified" | "failed";
  text: string;
  evidence: string | null;
  required: boolean;
}

export interface DatasetField {
  name: string;
  type?: string | null;
  unit?: string | null;
  description: string;
  concepts: string[];
  level: "record" | "input" | "grid" | "derived";
  status: EvidenceStatus;
  evidence?: string | null;
  configs?: string[];
}

export interface CuratedInfo {
  slug: string;
  title: string;
  difficulty: string;
  estimatedMinutes: number | null;
  notebook: boolean;
  offlineSample: boolean;
  lesson: string;
  accent: string;
  hasPreview: boolean;
  expectedRuntime: { sample?: string; real?: string };
}

export interface DatasetSummary {
  id: string;
  title: string;
  description: string;
  publisher: string;
  provider: string;
  providerId: string;
  canonicalUrl: string;
  formats: Claim & { values: string[]; exhaustive?: boolean };
  access: Claim & { method: string; signInRequired: boolean | null; class: string };
  license: Claim & { name: string | null; url: string | null; commercialUse: string; class: string };
  coverage: {
    temporal: Claim & { start: string | null; end: string | null; ongoing: boolean | null; granularity: string[]; dependsOnRequest?: boolean; text: string; years: number | null };
    spatial: Claim & { scope: string; regions: string[]; description: string | null; text: string };
  };
  purposes: string[];
  characteristics: string[];
  tags: string[];
  fieldNames: string[];
  schemaStatus: "complete" | "partial" | "unknown";
  size: { rows: number | null; bytes: number | null; note?: string | null };
  curated: CuratedInfo | null;
  packId: string | null;
  origin: "pack" | "seed" | "import" | "live";
  reviewStatus: "reviewed" | "unreviewed";
  stale: boolean;
  sourceUpdatedAt: string | null;
  lastVerifiedAt: string | null;
  lastFetchedAt: string | null;
  linkCheck: { ok: boolean; http_status: number | null; detail: string; checked_at: string } | null;
  fit: Fit;
  reasons: Reason[];
  relevance?: number | null;
  liveHit?: { provider: string; rank: number; fetched_at: string; providers: string[] } | null;
  unitOfAnalysis?: string | null;
  doi?: string | null;
  configs?: string[];
  files?: DataFileInfo[];
  previewProvider?: string | null;
  verifiedImport?: { importId: string; file: string; at: string } | null;
  kind?: "dataset" | "documentation";
  analysis?: AnalysisLatest | null;
  analyzable?: boolean;
  /** What a card can offer before any job starts. */
  runnable?: "sample" | "kaggle" | "sign-in" | "unsupported" | "documentation";
  unsupportedFormats?: string[];
  readiness?: string[];
}

/** Summary of the latest successful analysis of a dataset (same id everywhere). */
export interface AnalysisLatest {
  runId: string;
  at: string;
  file: string;
  coverage: "sample" | "full";
  /** Total rows in the source table; null when only the start of a file was read. */
  rows: number | null;
  rowsAnalyzed: number;
  columns: number;
  mode?: "sample" | "full";
  sampleMethod?: string | null;
  preview?: { label: string; values: number[]; kind?: "bars" | "line" } | null;
  scope?: string;
  scopeDetail?: ReportScope | null;
  kind?: ReportKind;
  handlerLabel?: string | null;
  validCoordsPct?: number | null;
  dateCoverage: { column: string; min: string; max: string } | null;
  missingPct: number;
  duplicates: number | null;
}

export interface AnalysisColumn {
  name: string;
  type: string;
  kind: "numeric" | "datetime" | "text" | "boolean";
  missing: number;
  missing_pct: number;
  distinct: number;
  concepts: string[];
  min?: unknown;
  max?: unknown;
  mean?: number | null;
  median?: unknown;
  std?: number | null;
  top?: [string, number][];
  parsed_as?: string | null;
}

export type ReportKind = "table" | "trajectory" | "images" | "sinex" | "inspection";

/** Which limit stopped a request, the measured or estimated size, and what the person can do next. */
export interface LimitDetail {
  limit?: "transfer" | "extract" | "members" | "quick_sample" | "staging" | string;
  limitLabel?: string;
  limitEnv?: string;
  limitBytes?: number | null;
  measuredBytes?: number | null;
  estimated?: boolean;
  actions?: ("run_sample" | "prepare_archive_sample" | "full" | "date_range" | "upload" | "open_source" | "select_member" | "open_consent" | "retry")[];
  consentUrl?: string;
  detected?: string;
  count?: number;
}

export interface ArchiveMember { name: string; size: number; compressed?: number; type: string }

export interface ArchiveInfo {
  name: string;
  transferred_bytes: number;
  members_total: number;
  expanded_bytes: number;
  extracted_files: number;
  extracted_bytes: number;
  skipped: { name: string; reason: string }[];
  scores: Record<string, number>;
  candidates: ArchiveMember[];
  selected: string[];
}

export interface ImagePreview { file: string; width: number; height: number; class?: string | null; src: string; shapes: { label?: string | null; points: [number, number][] }[] }

export interface ImagesSection {
  total: number;
  analyzed: number;
  unreadable: number;
  formats: [string, number][];
  dimensions: [string, number][];
  width: { min: number; median: number; max: number } | null;
  height: { min: number; median: number; max: number } | null;
  folders: [string, number][];
  splits: [string, number][];
  annotation_format: string | null;
  annotation_format_label: string | null;
  label_source: string | null;
  annotated: number;
  annotated_pct: number;
  with_objects: number;
  objects: number;
  class_images: [string, number][];
  objects_by_class: [string, number][];
  geotagged: number;
  previews: ImagePreview[];
  unparsed_annotations: string[];
}

export interface SinexSection {
  files: string[];
  version: string | null;
  agency: string | null;
  technique: string | null;
  data_start: string | null;
  data_end: string | null;
  created: string | null;
  contents: string | null;
  reference: Record<string, string>;
  frame: string;
  estimate_types: [string, number][];
  units: [string, number][];
  stations: number;
  solutions: number;
  with_position: number;
  with_velocity: number;
  located: number;
  position_sources: string[];
  sigma_mm: { median: number; p95: number; max: number } | null;
}

export interface TrajectorySection {
  time: string;
  time_kind: "mjd" | "value";
  position: [string, string, string];
  points: [number, number, number][];
  times: string[];
  points_total: number;
  step: number;
  series: { column: string; points: [string, number][] }[];
  maneuvers: { t: string; type: number | null; label: string }[];
  maneuver_labels_source: string | null;
  units_note: string;
}

export interface InspectionSection {
  detected: string;
  types: { type: string; files: number; bytes: number }[];
  files: ArchiveMember[];
  file_count: number;
  bytes: number;
  next: string;
}

export interface AnalysisReport {
  kind?: ReportKind;
  scope?: ReportScope;
  worksheet?: { file: string; sheet: string; sheets: string[] };
  fetch?: { cache: "hit" | "miss" | "range" | "none"; transferred_bytes: number; source_bytes: number | null; requests?: number | null };
  timings?: Record<string, number>;
  source_bytes?: number | null;
  preview_deferred?: number;
  handler?: string;
  handler_label?: string;
  detected_type?: string;
  transferred_bytes?: number;
  archive?: ArchiveInfo;
  images?: ImagesSection;
  sinex?: SinexSection;
  trajectory?: TrajectorySection;
  pair?: { file: string; partner: string; values: [string, unknown][] };
  inspection?: InspectionSection;
  analyzed_file?: string;
  coverage: "sample" | "full" | "inspection";
  sample_method: string | null;
  paged_source?: boolean;
  rows_fetched?: number;
  rows_total: number | null;
  rows_analyzed: number;
  rows_skipped?: number;
  params?: RunParams;
  skip_reasons?: string[];
  columns: AnalysisColumn[];
  source_url?: string;
  duplicate_rows: number | null;
  duplicate_pct: number | null;
  missing_pct: number;
  date_coverage: { column: string; min: string; max: string } | null;
  preview: unknown[][];
  insights?: Insights;
}

export interface Insights {
  rows: number;
  scope: "sample" | "full";
  error?: string;
  time?: { column: string; grain: "month" | "year"; series: [string, number][]; missing: number; hour_column?: string; by_hour?: [number, number][]; by_month_of_year?: [number, number][]; weekday_hour?: [number, number, number][] };
  injury_outcomes?: { injured_field: string; killed_field: string; counts: [string, number][] };
  categories?: { column: string; values: [string, number][]; other: number; unknown: number; distinct: number }[];
  numbers?: { column: string; kind: "counts" | "histogram"; missing: number; values?: [number | string, number][]; bins?: [number, number, number][] }[];
  coordinates?: {
    lat: string; lon: string; rows: number; both_present: number; valid: number; zero_pairs: number; out_of_range: number;
    missing_either: number; valid_pct: number; bbox: { min_lat: number; max_lat: number; min_lon: number; max_lon: number } | null;
    points: [number, number][];
  };
  findings: { level: "info" | "warn"; text: string }[];
  preview?: { label: string; values: number[]; kind?: "bars" | "line" } | null;
  trends?: { time: string; bucket: string; series: { column: string; points: [string, number][] }[]; by_hour?: { column: string; values: [number, number | null][] } };
  seasonal?: { column: string; years: number[]; series: { year: number; values: [number, number][] }[] };
  target?: { column: string; reason: string; unit: string | null };
  relationships?: {
    target: string; rows: number; min_rows: number; enough: boolean; tested: number;
    items: { column: string; n: number; pearson: number; spearman: number | null; unit: string | null }[]
  };
  scatter?: { x: string; y: string; points: [number, number][]; total: number; shown: number; x_unit: string | null; y_unit: string | null };
}

export interface ReportScope { kind: "sample" | "dataset" | "date_range" | "worksheet" | "file" | "upload" | "inspection"; label: string; file?: string; sheet?: string; sheets?: string[] }

export interface AnalysisRun {
  id: string;
  dataset_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  created_at: string;
  finished_at: string | null;
  file_name: string;
  file_url: string | null;
  file_format: string | null;
  file_bytes: number | null;
  file_sha256: string | null;
  source: { title: string; provider: string; canonicalUrl: string; license: string | null; licenseUrl: string | null; commercialUse: string | null; version: string | null; doi: string | null };
  log: string;
  error: string | null;
  report: AnalysisReport | null;
  mode?: "sample" | "full";
  stage?: "resolving" | "downloading" | "extracting" | "profiling" | "charting" | "saving" | "done" | null;
  error_kind?: string | null;
  error_detail?: LimitDetail | null;
  progress?: {
    bytes?: number; total?: number | null; rows?: number; row_total?: number; phase?: string; done?: number; total_items?: number | null;
    unit?: string; bytes_total?: number
  } | null;
  params?: RunParams | null;
  owner?: string | null;
  queue?: QueueInfo | null;
  worker?: string | null;
  worker_available?: boolean;
  dataset: { id: string; title: string; exists: boolean };
  isLatest: boolean;
}

export type AnalysisListItem = Omit<AnalysisRun, "report" | "log" | "dataset" | "isLatest"> & {
  dataset_title: string; rows: number | null; coverage: string | null;
  kind?: ReportKind | null; scope?: string | null
};

export interface ComparisonAnalysis {
  runId: string;
  at: string;
  file: string;
  coverage: "sample" | "full";
  sampleMethod: string | null;
  rowsTotal: number | null;
  rowsAnalyzed: number;
  missingPct: number;
  duplicateRows: number | null;
  dateCoverage: { column: string; min: string; max: string } | null;
  schema: { name: string; type: string; missingPct: number }[];
}

export type ComparisonItem = DatasetDetail & { analysis: ComparisonAnalysis | null };

export interface ComparisonSummary {
  id: string;
  name: string;
  created_at: string;
  dataset_ids: string[];
  analysis_run_ids: Record<string, string | null>;
  criteria: string;
  dataset_titles: string[];
}

export interface ComparisonReport extends Omit<ComparisonSummary, "dataset_titles"> {
  snapshot: ComparisonItem[];
}

export interface RunParams {
  sheet?: string;
  dateField?: string;
  dateFrom?: string;
  dateTo?: string;
  prepare?: boolean;
  members?: string[];
  handler?: string;
  pairUrl?: string;
}

export interface DataFileInfo {
  url: string;
  label?: string;
  group?: "pairs" | "unpaired" | "converted" | "whole";
  prefix?: string;
  pair_url?: string;
  pair_name?: string;
  pair_bytes?: number | null;
  name?: string | null;
  format?: string | null;
  bytes?: number | null;
  supported?: boolean;
  date_fields?: string[];
  sample_url?: string;
  config?: string | null;
  split?: string | null;
}

/** GET /api/datasets/{id}/files: files resolved from the provider on demand. */
export interface FileList {
  files: DataFileInfo[];
  total: number;
  via: string | null;
  signInRequired: boolean;
  note: string | null;
  errors: string[];
  maxMB: number;
  maxBytes?: number;
  quickSampleBytes?: number;
  unsupportedFormats?: string[];
  matched?: number;
  offset?: number;
  limit?: number;
  pairs?: number;
  connect?: "kaggle" | null;
  consentUrl?: string | null;
  kaggle?: KaggleStatus | null;
}

export interface KaggleStatus {
  provider: "kaggle";
  connected: boolean;
  account: string | null;
  method: string | null;
  verifiedAt: string | null;
  lastError: string | null;
  oauthAvailable: boolean;
  signedIn: boolean;
}

export interface User { id: string; email: string }

export interface InspectResult {
  file: { name: string; url: string; format: string; bytes: number | null };
  detected: string;
  bytes: number | null;
  rangeReads: boolean;
  members: ArchiveMember[] | null;
  memberCount?: number;
  expandedBytes?: number;
  skipped?: { name: string; reason: string }[];
  types?: { type: string; files: number; bytes: number }[];
  suggested?: {
    handler: string; label: string; scores: Record<string, number>; sampleFiles: number; sampleBytes: number; fullFiles: number; fullBytes: number;
    sampleTransfer?: number; fullTransfer?: number
  };
  note?: string;
  source?: "remote" | "cache";
  transferredBytes?: number;
  fullDownloadRequired?: boolean;
  membersCached?: boolean;
  cached?: boolean;
}

export interface Capabilities {
  packRuns: boolean;
  workerAvailable?: boolean;
  storage: "sqlite" | "postgres";
  uploadMode: "direct" | "blob";
  maxUploadMB: number;
  directUploadMaxMB: number;
  maxTransferBytes?: number;
  maxExtractBytes?: number;
  quickSampleBytes?: number;
  runMode?: "thread" | "queue";
  worker?: { state: QueueInfo["state"]; message: string };
  kaggleOAuth?: boolean;
  formats?: { key: string; label: string; description: string }[];
}

export interface LiveProvider {
  key: string;
  label: string;
  configured: boolean;
  note: string | null;
}

export interface LiveResult {
  provider: string;
  label: string;
  status: "ok" | "cached" | "error" | "not-configured" | "skipped";
  detail: string;
  count: number;
  ms?: number;
  fetched_at?: string;
  ids: string[];
  stale?: boolean;
}

export interface PreviewData {
  kind: string;
  columns: { name: string; type: string | null }[];
  rows: unknown[][];
  source: string;
  config?: string;
  split?: string;
  configs?: string[];
  file?: string;
}

export interface Facet {
  value: string;
  count: number;
}

export interface SearchCriteria {
  topic: string;
  fields: string[];
  min_years: number | null;
  formats: string[];
  region: string | null;
  granularity: string | null;
  commercial: boolean;
  soft: string[];
  purposes: string[];
  difficulty: string[];
  offline: boolean;
  notebook: boolean;
  period_from: string | null;
  period_to: string | null;
}

export interface SearchResponse {
  criteria: SearchCriteria;
  terms: string[];
  scope: string;
  sort: string;
  page: number;
  page_size: number;
  total: number;
  counts: { meets: number; "needs-verification": number; "does-not-meet": number; candidates: number };
  facets: Record<string, Facet[]>;
  items: DatasetSummary[];
  catalogSize: number;
}

export interface StatusTile {
  state: "ok" | "error" | "pending" | "unchecked" | "not-applicable";
  detail: string;
  at?: string | null;
  run_id?: string | null;
  http?: number | null;
}

export interface DatasetDetail extends DatasetSummary {
  fields: DatasetField[];
  sourceLinks: { label: string; url: string }[];
  limitations: string[];
  statuses: { sourceResponded: StatusTile; metadataReviewed: StatusTile; sampleRan: StatusTile };
}

export interface SourceStatusRow {
  source: string;
  label: string;
  status: "ok" | "error" | "skipped" | "never";
  detail: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  records: number;
}

export interface DiscoverMeta {
  total: number;
  curated: number;
  reviewed: number;
  providers: Record<string, number>;
  imports: { running: boolean; last: unknown; sources: SourceStatusRow[]; configured: Record<string, string[]> };
  concepts: Record<string, string>;
  regions: Record<string, string>;
  examples: string[];
  catalogHealth: { recordsDir?: string; packsDir?: string; recordsDirExists?: boolean; seedFiles?: number; packsFound?: number; loaded?: number; fallbackPacks?: string[]; errors?: string[]; loadedAt: string | null };
  liveProviders: LiveProvider[];
  capabilities?: Capabilities;
}
