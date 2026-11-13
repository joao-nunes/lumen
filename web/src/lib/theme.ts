/**
 * Light or dark, chosen by the person and remembered in this browser only. Light unless they
 * chose dark. Storage can be blocked or cleared, so every access is guarded and light is the
 * fallback.
 */
export type Theme = "light" | "dark";

const KEY = "lumen-theme";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Blocked storage: the choice still applies until the page is reloaded.
  }
}

/** Sets `data-theme` on <html>, which global.css turns into the matching `color-scheme`. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}
