import { useEffect, useState } from "react";

export type Theme = "dark" | "light";

function initial(): Theme {
  try {
    const s = localStorage.getItem("lakeguard-theme");
    if (s === "light" || s === "dark") return s;
  } catch { /* ignore */ }
  return "dark";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initial);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("lakeguard-theme", theme);
    } catch { /* ignore */ }
  }, [theme]);

  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}
