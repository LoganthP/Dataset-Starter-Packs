/** Shared wording for analysis coverage, so cards, reports and comparisons say the same thing. */
export function rowsLabel(analyzed: number, total: number | null | undefined, coverage: string | null | undefined): string {
  if (coverage === "full") return `${analyzed.toLocaleString()} rows (full file)`;
  if (total == null) return `${analyzed.toLocaleString()} rows sampled (total unknown)`;
  return `${analyzed.toLocaleString()} of ${total.toLocaleString()} rows (sample)`;
}

/** Run stages as shown to people: resolving + downloading are "Fetching", extracting is "Inspecting",
 * profiling + charting are "Analyzing". */
export const STAGES = [
  { key: "resolving", label: "Fetching" },
  { key: "extracting", label: "Inspecting" },
  { key: "profiling", label: "Analyzing" },
  { key: "charting", label: "Building insights" },
  { key: "saving", label: "Saving" },
] as const;

export function stageIndex(stage: string | null | undefined): number {
  if (!stage || stage === "resolving" || stage === "downloading") return 0;
  if (stage === "extracting") return 1;
  if (stage === "profiling") return 2;
  if (stage === "charting") return 3;
  if (stage === "saving") return 4;
  if (stage === "done") return STAGES.length;
  return 0;
}

/** Retry only makes sense for temporary failures. */
export const RETRYABLE = new Set(["timeout", "network", "interrupted", "cancelled", "error"]);

export const FAILURE_LABEL: Record<string, string> = {
  timeout: "Timed out",
  auth: "Needs sign-in",
  not_found: "File not found",
  too_large: "Too large",
  format: "Unreadable file",
  network: "Source unreachable",
  interrupted: "Interrupted",
  cancelled: "Stopped",
  not_data: "Not a data file",
  consent: "Terms not accepted",
};

/** Plain words for the next actions the API suggests with a limit or access failure. */
export const ACTION_LABEL: Record<string, string> = {
  prepare_archive_sample: "Prepare archive and run sample",
  full: "Run full analysis",
  run_sample: "Run sample instead",
  date_range: "Choose a date range",
  select_member: "Choose files in the archive",
  open_source: "Open source",
  upload: "Upload a file",
  open_consent: "Accept terms on Kaggle",
  retry: "I've accepted. Retry",
};

export function failureLabel(kind: string | null | undefined, stage?: string | null): string {
  const base = FAILURE_LABEL[kind ?? ""] ?? "Failed";
  const st = STAGES[Math.min(stageIndex(stage), STAGES.length - 1)]?.label.toLowerCase();
  return st && kind === "timeout" ? `${base} while ${st}` : base;
}
