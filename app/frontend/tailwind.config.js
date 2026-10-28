/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  safelist: [
    "text-status-err", "text-status-warn", "text-status-ok", "text-status-info", "text-status-mute", "text-text",
  ],
  theme: {
    extend: {
      colors: {
        // Paleta Databricks — tokens temáticos via CSS vars (dark/light), ver index.css
        lava:   { DEFAULT: "#FF3621", soft: "rgba(255,54,33,0.12)", ring: "rgba(255,54,33,0.35)" },
        navy: {
          DEFAULT: "rgb(var(--navy) / <alpha-value>)",
          900: "rgb(var(--navy-900) / <alpha-value>)",
          800: "rgb(var(--navy-800) / <alpha-value>)",
          700: "rgb(var(--navy-700) / <alpha-value>)",
          600: "rgb(var(--navy-600) / <alpha-value>)",
        },
        oat:    { DEFAULT: "rgb(var(--oat) / <alpha-value>)", dim: "rgb(var(--oat-dim) / <alpha-value>)" },
        bg:     { DEFAULT: "rgb(var(--bg) / <alpha-value>)", soft: "rgb(var(--bg-soft) / <alpha-value>)" },
        surface:{ DEFAULT: "rgb(var(--surface) / <alpha-value>)", 2: "rgb(var(--surface-2) / <alpha-value>)" },
        border: { DEFAULT: "rgb(var(--border) / <alpha-value>)" },
        text:   { DEFAULT: "rgb(var(--text) / <alpha-value>)", dim: "rgb(var(--text-dim) / <alpha-value>)" },
        status: { ok: "#00A972", warn: "#F2A900", err: "#FF3621", info: "#2272B4", mute: "#8FA6A9" },
      },
      borderRadius: { xl2: "14px" },
      boxShadow: {
        card: "0 4px 24px rgba(0,0,0,0.35)",
        glow: "0 0 0 3px rgba(255,54,33,0.18)",
      },
    },
  },
  plugins: [],
};
