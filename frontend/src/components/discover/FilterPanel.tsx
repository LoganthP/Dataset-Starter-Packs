import type { ReactNode } from "react";
import { label, list, toggleInList, withParam } from "../../lib/searchState";
import type { Facet, SearchCriteria } from "../../types";

function Group({ title, hint, children, open = true }: { title: string; hint?: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="group border-b border-white/80 py-3 last:border-0" open={open}>
      <summary className="flex cursor-pointer select-none items-center gap-1.5 font-display text-[15px] font-bold">
        {title}
        {hint && (
          <span tabIndex={0} role="note" aria-label={hint} data-tip={hint}
            className="tip inline-flex h-4 w-4 items-center justify-center rounded-full bg-sky-deep text-[10px] font-bold text-ink-soft"
            onClick={(e) => e.preventDefault()}>?</span>
        )}
        <span className="ml-auto text-ink-faint transition-transform group-open:rotate-90" aria-hidden>›</span>
      </summary>
      <div className="mt-2 space-y-1">{children}</div>
    </details>
  );
}

function Check({ checked, onChange, children, count }: { checked: boolean; onChange: () => void; children: ReactNode; count?: number }) {
  const empty = count === 0 && !checked;
  return (
    <label className={`flex cursor-pointer items-center gap-2.5 rounded-xl px-2 py-1.5 text-sm hover:bg-white/70 ${empty ? "opacity-45" : ""}`}>
      <input type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 rounded accent-peri" />
      <span className="flex-1">{children}</span>
      {count !== undefined && <span className="tabular-nums text-xs text-ink-faint">{count}</span>}
    </label>
  );
}

function FacetGroup({ title, group, facets, sp, setSp, hint, open }: {
  title: string; group: string; facets?: Facet[]; sp: URLSearchParams; setSp: (n: URLSearchParams) => void; hint?: string; open?: boolean;
}) {
  if (!facets?.length) return null;
  const selected = list(sp, group);
  return (
    <Group title={title} hint={hint} open={open ?? selected.length > 0}>
      {facets.map((f) => (
        <Check key={f.value} checked={selected.includes(f.value)} count={f.count} onChange={() => setSp(toggleInList(sp, group, f.value))}>
          {label(group, f.value)}
        </Check>
      ))}
    </Group>
  );
}

export default function FilterPanel({ facets, criteria, sp, setSp, concepts, regions, variant = "discover" }: {
  facets: Record<string, Facet[]>;
  criteria: SearchCriteria;
  sp: URLSearchParams;
  setSp: (next: URLSearchParams) => void;
  concepts: Record<string, string>;
  regions: Record<string, string>;
  variant?: "discover" | "curated";
}) {
  const fields = list(sp, "fields");
  const formats = list(sp, "formats");
  const readiness = (
    <>
      <FacetGroup title="Readiness" group="ready" facets={facets.ready} sp={sp} setSp={setSp} open={variant === "curated" || undefined} />
      <FacetGroup title="Difficulty" group="difficulty" facets={facets.difficulty} sp={sp} setSp={setSp} open={variant === "curated" || undefined} />
      <Group title="Estimated time" open={variant === "curated" || !!sp.get("max_minutes")}>
        <select className="field" value={sp.get("max_minutes") ?? ""} onChange={(e) => setSp(withParam(sp, "max_minutes", e.target.value))} aria-label="Maximum estimated time">
          <option value="">Any length</option>
          <option value="40">40 minutes or less</option>
          <option value="45">45 minutes or less</option>
          <option value="60">An hour or less</option>
        </select>
      </Group>
    </>
  );

  return (
    <div className="text-ink">
      <p className="flex items-center gap-1.5 pb-1 font-display text-base font-bold">Filters
        <span tabIndex={0} role="note" aria-label="How filters combine" data-tip="Groups combine with AND; options inside a group combine with OR. Required fields must all be present."
          className="tip inline-flex h-4 w-4 items-center justify-center rounded-full bg-sky-deep text-[10px] font-bold text-ink-soft">?</span>
      </p>
      {variant === "curated" && readiness}

      <Group title="Required fields" hint="Checked against each dataset's documented schema.">
        {Object.entries(concepts).map(([key, text]) => (
          <Check key={key} checked={fields.includes(key)} onChange={() => setSp(toggleInList(sp, "fields", key))}>{text}</Check>
        ))}
      </Group>

      <Group title="Coverage" open={!!(criteria.min_years || criteria.region || criteria.period_from || criteria.period_to || criteria.granularity)}>
        <label className="block text-sm">
          <span className="font-semibold">Minimum duration</span>
          <select className="field mt-1" value={sp.get("min_years") ?? ""} onChange={(e) => setSp(withParam(sp, "min_years", e.target.value))}>
            <option value="">Any</option>
            {[1, 2, 5, 10, 20].map((y) => <option key={y} value={y}>At least {y} year{y > 1 ? "s" : ""}</option>)}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <label className="block">
            <span className="font-semibold">Observations from</span>
            <input type="date" className="field mt-1" value={sp.get("period_from") ?? ""} onChange={(e) => setSp(withParam(sp, "period_from", e.target.value))} />
          </label>
          <label className="block">
            <span className="font-semibold">to</span>
            <input type="date" className="field mt-1" value={sp.get("period_to") ?? ""} onChange={(e) => setSp(withParam(sp, "period_to", e.target.value))} />
          </label>
        </div>
        <label className="block text-sm">
          <span className="font-semibold">Country or region</span>
          <select className="field mt-1" value={sp.get("region") ?? ""} onChange={(e) => setSp(withParam(sp, "region", e.target.value))}>
            <option value="">Any region</option>
            {Object.entries(regions).filter(([k]) => k !== "global").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-semibold">Time resolution</span>
          <select className="field mt-1" value={sp.get("granularity") ?? ""} onChange={(e) => setSp(withParam(sp, "granularity", e.target.value))}>
            <option value="">Any</option>
            {["minute", "hourly", "daily", "monthly"].map((g) => <option key={g} value={g}>{label("granularity", g)}</option>)}
          </select>
        </label>
      </Group>

      <Group title="File format" open={formats.length > 0}>
        {["csv", "json", "parquet", "xlsx", "netcdf"].map((f) => (
          <Check key={f} checked={formats.includes(f)} onChange={() => setSp(toggleInList(sp, "formats", f))}>{label("formats", f)}</Check>
        ))}
      </Group>

      <Group title="Access and reuse" open={!!(sp.get("commercial") || sp.get("access") || sp.get("license"))}>
        <Check checked={sp.get("commercial") === "1"} onChange={() => setSp(withParam(sp, "commercial", sp.get("commercial") === "1" ? null : "1"))}>
          Must allow commercial reuse
        </Check>
        <div className="pt-1" />
        {(facets.access ?? []).map((f) => (
          <Check key={f.value} checked={list(sp, "access").includes(f.value)} count={f.count} onChange={() => setSp(toggleInList(sp, "access", f.value))}>
            {label("access", f.value)}
          </Check>
        ))}
        <div className="pt-1" />
        {(facets.license ?? []).map((f) => (
          <Check key={f.value} checked={list(sp, "license").includes(f.value)} count={f.count} onChange={() => setSp(toggleInList(sp, "license", f.value))}>
            {label("license", f.value)}
          </Check>
        ))}
      </Group>

      <FacetGroup title="Analysis purpose" group="purpose" facets={facets.purpose} sp={sp} setSp={setSp} open />
      <FacetGroup title="Data characteristics" group="kind" facets={facets.kind} sp={sp} setSp={setSp} />
      <FacetGroup title="Provider" group="provider" facets={facets.provider} sp={sp} setSp={setSp} />
      {variant === "discover" && readiness}
    </div>
  );
}
