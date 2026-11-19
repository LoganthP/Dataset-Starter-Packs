import { AnimatePresence, motion } from "framer-motion";
import { Columns3, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { SHORTLIST_MAX, titleOf, useShortlist } from "../../lib/shortlist";

/** Floating tray: the comparison queue follows you across Discover, Curated Packs and dataset pages. */
export default function ShortlistTray() {
  const { ids, clear } = useShortlist();
  const location = useLocation();
  if (location.pathname.startsWith("/compare")) return null;
  return (
    <AnimatePresence>
      {ids.length > 0 && (
        <motion.aside
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 80, opacity: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 26 }}
          className="glass-strong fixed bottom-3 right-3 z-40 flex items-center gap-2 rounded-2xl p-2 sm:right-6"
          aria-label="Comparison queue"
        >
          <span className="px-2 text-sm font-bold" title={ids.map(titleOf).join("\n")}>Compare {ids.length}/{SHORTLIST_MAX}</span>
          <button className="rounded-lg p-1.5 text-ink-faint hover:bg-white hover:text-ink" onClick={clear} aria-label="Clear queue" title="Clear queue"><X size={15} /></button>
          <Link to="/compare" className="btn-clay bg-peri px-3.5 py-2 text-sm">
            <Columns3 size={16} /> Open comparison
          </Link>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
