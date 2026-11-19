import { X } from "lucide-react";
import type { SearchCriteria } from "../../types";
import { criterionLabel, list, toggleInList, withParam } from "../../lib/searchState";

/** The editable requirements parsed from the query. Each can be removed or downgraded to "preferred". */
export function criteriaKeys(c: SearchCriteria): string[] {
  const keys = c.fields.map((f) => `field:${f}`);
  if (c.min_years) keys.push("min_years");
  if (c.period_from || c.period_to) keys.push("period");
  if (c.formats.length) keys.push("formats");
  if (c.region) keys.push("region");
  if (c.granularity) keys.push("granularity");
  if (c.commercial) keys.push("commercial");
  return keys;
}

export function removeCriterion(sp: URLSearchParams, key: string): URLSearchParams {
  let next = new URLSearchParams(sp);
  if (key.startsWith("field:")) next = toggleInList(next, "fields", key.slice(6));
  else if (key === "period") next = withParam(withParam(next, "period_from", null), "period_to", null);
  else next = withParam(next, key, null);
  const soft = list(next, "soft").filter((k) => k !== key);
  return withParam(next, "soft", soft.join(","));
}

export default function CriteriaBar({ criteria, sp, setSp, concepts, regions }: {
  criteria: SearchCriteria;
  sp: URLSearchParams;
  setSp: (next: URLSearchParams) => void;
  concepts: Record<string, string>;
  regions: Record<string, string>;
}) {
  const keys = criteriaKeys(criteria);
  const soft = new Set(criteria.soft);
  if (!keys.length && !criteria.topic) {
    return (
      <p className="text-sm text-ink-soft">
        No requirements yet. Describe your project above, or add required fields, coverage and format from the filters.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Search requirements">
      {criteria.topic && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/85 py-1 pl-3 pr-1 text-sm">
          <span className="text-ink-soft">Topic</span>
          <span className="font-semibold">{criteria.topic}</span>
          <button className="rounded-full p-1 hover:bg-sky-deep" aria-label="Clear topic" onClick={() => setSp(withParam(sp, "topic", ""))}>
            <X size={14} />
          </button>
        </span>
      )}
      {keys.map((key) => {
        const required = !soft.has(key);
        return (
          <span key={key}
            className={`inline-flex items-center gap-1 rounded-full border py-1 pl-3 pr-1 text-sm ${required ? "border-peri/40 bg-white" : "border-dashed border-ink-faint/50 bg-white/60"}`}>
            <span className="font-semibold">{criterionLabel(key, criteria, concepts, regions)}</span>
            <button
              className={`ml-1 rounded-full px-2 py-0.5 text-xs font-bold ${required ? "bg-peri text-paper" : "bg-sky-deep text-ink-soft"}`}
              onClick={() => setSp(toggleInList(sp, "soft", key))}
              aria-label={`${criterionLabel(key, criteria, concepts, regions)} is ${required ? "required" : "preferred"}. Switch to ${required ? "preferred" : "required"}`}
              title="Required criteria decide which group a dataset lands in. Preferred ones only affect ranking."
            >
              {required ? "Required" : "Preferred"}
            </button>
            <button className="rounded-full p-1 hover:bg-sky-deep" aria-label={`Remove ${criterionLabel(key, criteria, concepts, regions)}`}
              onClick={() => setSp(removeCriterion(sp, key))}>
              <X size={14} />
            </button>
          </span>
        );
      })}
    </div>
  );
}
