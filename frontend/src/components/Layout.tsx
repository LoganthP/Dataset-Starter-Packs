import { Monitor, Moon, Settings, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, ScrollRestoration, useLocation } from "react-router-dom";
import { useAccount } from "../lib/account";
import { rememberSectionUrl, sectionHref } from "../lib/session";
import { useShortlist } from "../lib/shortlist";
import { type ThemePref, useTheme } from "../lib/theme";
import ShortlistTray from "./discover/ShortlistTray";

function Logo() {
  return (
    <svg width="34" height="34" viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="18" fill="#7C83FD" />
      <rect x="12" y="12" width="18" height="18" rx="5" fill="#fff" />
      <rect x="34" y="12" width="18" height="18" rx="5" fill="#FFD166" />
      <rect x="12" y="34" width="18" height="18" rx="5" fill="#3DD6D0" />
      <rect x="34" y="34" width="18" height="18" rx="5" fill="#FF7AA2" />
    </svg>
  );
}

const THEMES: { v: ThemePref; t: string; icon: typeof Sun }[] = [
  { v: "light", t: "Light", icon: Sun },
  { v: "dark", t: "Dark", icon: Moon },
  { v: "system", t: "System", icon: Monitor },
];

function ThemeMenu() {
  const { pref, set } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  const Current = THEMES.find((x) => x.v === pref)!.icon;
  return (
    <div ref={ref} className="relative">
      <button className="rounded-xl p-2 text-ink-soft hover:bg-white" onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu" aria-expanded={open} aria-label={`Theme: ${pref}`} title="Theme">
        <Current size={18} />
      </button>
      {open && (
        <div role="menu" className="glass-strong absolute right-0 top-11 z-50 w-36 rounded-2xl p-1">
          {THEMES.map(({ v, t, icon: Icon }) => (
            <button key={v} role="menuitemradio" aria-checked={pref === v} onClick={() => { set(v); setOpen(false); }}
              className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold ${pref === v ? "bg-peri/15 text-peri-ink" : "hover:bg-white"}`}>
              <Icon size={15} /> {t}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AccountLink() {
  const { user, kaggle } = useAccount();
  const location = useLocation();
  const active = location.pathname.startsWith("/settings");
  return (
    <Link to="/settings" aria-current={active ? "page" : undefined} title={user ? `Settings: signed in as ${user.email}` : "Settings: log in, connect Kaggle"}
      className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-2.5 py-2 text-sm font-semibold ${active ? "bg-ink text-on-accent" : "text-ink-soft hover:bg-white"}`}>
      <Settings size={16} aria-hidden />
      <span className="hidden lg:inline">{user ? user.email.split("@")[0] : "Log in"}</span>
      {kaggle?.connected && <span className="h-2 w-2 rounded-full bg-ok" aria-label="Kaggle connected" />}
    </Link>
  );
}

export default function Layout() {
  const shortlist = useShortlist();
  const location = useLocation();

  // Remember the last Discover / Curated Packs URL for this browser session.
  useEffect(() => {
    if (location.pathname === "/discover") rememberSectionUrl("discover", location.search);
    if (location.pathname === "/packs") rememberSectionUrl("packs", location.search);
  }, [location.pathname, location.search]);

  const links = [
    { to: sectionHref("discover"), label: "Discover", active: location.pathname === "/discover" || location.pathname.startsWith("/datasets") },
    { to: sectionHref("packs"), label: "Curated packs", active: location.pathname.startsWith("/packs") },
    { to: "/compare", label: shortlist.ids.length ? `Compare (${shortlist.ids.length})` : "Compare", active: location.pathname.startsWith("/compare") },
    { to: "/runs", label: "Run history", active: location.pathname.startsWith("/runs") || location.pathname.startsWith("/analyses") },
    { to: "/sources", label: "Sources", active: location.pathname.startsWith("/sources") },
  ];

  return (
    <>
      <div className="backdrop" aria-hidden />
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 btn-ghost">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 px-3 pt-3 sm:px-6">
        <nav className="glass-strong mx-auto flex max-w-7xl items-center gap-2 rounded-2xl px-3 py-2 sm:gap-4 sm:px-4">
          <Link to="/" className="flex items-center gap-2.5 rounded-xl pr-2">
            <Logo />
            <span className="hidden font-display text-lg font-bold md:inline">Dataset Starter Packs</span>
          </Link>
          <div className="ml-auto flex items-center gap-0.5 overflow-x-auto">
            {links.map((l) => (
              <Link key={l.label.split(" (")[0]} to={l.to} aria-current={l.active ? "page" : undefined}
                className={`whitespace-nowrap rounded-xl px-2.5 py-2 text-sm font-semibold transition-colors sm:px-3 ${
                  l.active ? "bg-ink text-on-accent" : "text-ink-soft hover:bg-white"
                }`}>
                {l.label}
              </Link>
            ))}
          </div>
          <AccountLink />
          <ThemeMenu />
        </nav>
      </header>
      <main id="main" className="mx-auto max-w-7xl px-3 pb-28 pt-6 sm:px-6">
        <Outlet />
      </main>
      <ShortlistTray />
      {/* Discover and Curated Packs restore scroll by URL, so returning to a search lands where you left it. */}
      <ScrollRestoration getKey={(loc) => (loc.pathname === "/discover" || loc.pathname === "/packs" ? loc.pathname + loc.search : loc.key)} />
      <footer className="mx-auto max-w-7xl px-6 pb-10 text-sm text-ink-soft">
        Code is MIT-licensed. Each dataset keeps its own license and citation, shown on its dataset page.
      </footer>
    </>
  );
}
