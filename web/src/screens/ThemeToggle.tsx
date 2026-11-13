import { useState } from "react";
import { applyTheme, saveTheme, type Theme } from "../lib/theme";
import styles from "./ThemeToggle.module.css";

/** A switch between light and dark, on every page. main.tsx applies the stored choice first. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );

  return (
    <button
      type="button"
      className={styles.toggle}
      aria-pressed={theme === "dark"}
      onClick={() => {
        const next = theme === "dark" ? "light" : "dark";
        applyTheme(next);
        saveTheme(next);
        setTheme(next);
      }}
    >
      Dark mode
    </button>
  );
}
