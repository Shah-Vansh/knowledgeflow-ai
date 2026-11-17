/**
 * Light / dark / system theme. The choice is stored per browser; "system" follows
 * the OS setting live. The same logic runs before first paint (THEME_INIT_SCRIPT in
 * layout.tsx) so the page never flashes the wrong theme.
 */
export type ThemeChoice = "light" | "dark" | "system";

export const THEME_KEY = "kf_theme";
const CHOICES: ThemeChoice[] = ["light", "dark", "system"];

export function getThemeChoice(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    return CHOICES.includes(stored as ThemeChoice) ? (stored as ThemeChoice) : "system";
  } catch {
    return "system";
  }
}

export function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function resolveTheme(choice: ThemeChoice, prefersDark: boolean): "light" | "dark" {
  return choice === "system" ? (prefersDark ? "dark" : "light") : choice;
}

export function applyTheme(choice: ThemeChoice = getThemeChoice()): "light" | "dark" {
  const resolved = resolveTheme(choice, systemPrefersDark());
  document.documentElement.classList.toggle("dark", resolved === "dark");
  return resolved;
}

export function setThemeChoice(choice: ThemeChoice): "light" | "dark" {
  try {
    window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // storage blocked: the theme still applies for this page view
  }
  return applyTheme(choice);
}

export function nextThemeChoice(choice: ThemeChoice): ThemeChoice {
  return CHOICES[(CHOICES.indexOf(choice) + 1) % CHOICES.length];
}

/** Inline in <head>: sets html.dark before the first paint. Kept tiny and dependency-free. */
export const THEME_INIT_SCRIPT = `(function(){try{var c=localStorage.getItem("${THEME_KEY}");var d=c==="dark"||((c!=="light")&&window.matchMedia("(prefers-color-scheme: dark)").matches);if(d)document.documentElement.classList.add("dark")}catch(e){}})();`;
