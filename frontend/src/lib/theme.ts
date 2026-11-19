import { useEffect, useState } from "react";

export type ThemePref = "light" | "dark" | "system";
const KEY = "dsp:theme";
const EVENT = "dsp-theme";

export function readTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

const media = () => window.matchMedia("(prefers-color-scheme: dark)");

export function applyTheme(pref: ThemePref) {
  const dark = pref === "dark" || (pref === "system" && media().matches);
  document.documentElement.classList.toggle("dark", dark);
}

/** Light / Dark / System, saved in localStorage; System follows the OS live. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readTheme);
  useEffect(() => {
    applyTheme(pref);
    if (pref !== "system") return;
    const m = media();
    const onChange = () => applyTheme("system");
    m.addEventListener("change", onChange);
    return () => m.removeEventListener("change", onChange);
  }, [pref]);
  useEffect(() => {
    const sync = () => setPref(readTheme());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const set = (p: ThemePref) => {
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* storage unavailable: applies to this page only */
    }
    setPref(p);
    window.dispatchEvent(new Event(EVENT));
  };
  return { pref, set };
}
