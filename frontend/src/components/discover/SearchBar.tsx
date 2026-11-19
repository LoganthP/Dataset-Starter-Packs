import { Loader2, Search } from "lucide-react";
import { useEffect, useState } from "react";

export default function SearchBar({ value, onSubmit, examples, busy, placeholder, compact = false }: {
  value: string;
  onSubmit: (q: string) => void;
  examples?: string[];
  busy?: boolean;
  placeholder?: string;
  compact?: boolean;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <div>
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(text.trim());
        }}
        className={`glass-strong flex items-center gap-2 rounded-3xl p-2 ${compact ? "" : "sm:p-2.5"}`}
      >
        <label className="relative flex-1">
          <span className="sr-only">Describe your project or search by keyword</span>
          <Search size={20} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={placeholder ?? "Describe your project: “traffic incidents with latitude, longitude and timestamps, at least one year, CSV”"}
            className={`w-full rounded-2xl bg-transparent pl-12 pr-3 text-ink placeholder:text-ink-faint focus:outline-none ${compact ? "py-2.5 text-base" : "py-3.5 text-lg"}`}
          />
        </label>
        <button type="submit" className="btn-clay bg-peri px-5" disabled={busy}>
          {busy ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
          <span className="hidden sm:inline">Search</span>
        </button>
      </form>
      {examples && examples.length > 0 && !value && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-sm text-ink-soft">Try:</span>
          {examples.map((ex) => (
            <button key={ex} type="button" onClick={() => onSubmit(ex)}
              className="rounded-full border border-white bg-white/70 px-3 py-1 text-left text-sm font-medium text-ink-soft hover:bg-white hover:text-ink">
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
