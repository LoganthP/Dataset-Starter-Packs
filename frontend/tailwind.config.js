/** @type {import('tailwindcss').Config} */
// Colors are CSS variables (RGB channels) defined in src/index.css for light and dark themes,
// so every `text-ink`, `bg-white/70`, `bg-peri/15` etc. follows the active theme.
const v = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        white: v("white"), // the surface color: white in light mode, slate in dark mode
        paper: "#ffffff", // always white: frames for PNG charts
        ink: { DEFAULT: v("ink"), soft: v("ink-soft"), faint: v("ink-faint") },
        sky: { wash: v("sky-wash"), deep: v("sky-deep") },
        peri: { DEFAULT: v("peri"), ink: v("peri-ink") },
        aqua: { DEFAULT: v("aqua"), ink: v("aqua-ink") },
        sun: v("sun"),
        rose: v("rose"),
        ok: v("ok"),
        bad: v("bad"),
        warn: { DEFAULT: v("warn"), ink: v("warn-ink") },
        link: v("link"),
        "on-accent": v("on-accent"),
      },
      fontFamily: {
        display: ['"Bricolage Grotesque Variable"', "system-ui", "sans-serif"],
        body: ['"Figtree Variable"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        glass: "var(--shadow-glass)",
        lift: "var(--shadow-lift)",
        clay: "inset -4px -5px 10px rgba(0,0,0,.14), inset 4px 5px 10px rgba(255,255,255,.45), 0 10px 22px -8px rgba(40,50,120,.45)",
        "clay-press": "inset 4px 5px 12px rgba(0,0,0,.2), inset -3px -3px 8px rgba(255,255,255,.35)",
        neu: "var(--shadow-neu)",
        "neu-in": "var(--shadow-neu-in)",
      },
      borderRadius: { "4xl": "2rem" },
    },
  },
  plugins: [],
};
