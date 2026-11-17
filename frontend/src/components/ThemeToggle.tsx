"use client";

import { useEffect, useState } from "react";
import { applyTheme, getThemeChoice, nextThemeChoice, setThemeChoice, ThemeChoice } from "@/lib/theme";
import { cx } from "@/components/ui";

const LABEL: Record<ThemeChoice, string> = { light: "Light", dark: "Dark", system: "System" };

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}
function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
    </svg>
  );
}
function MonitorIcon() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

/** Cycles Light → Dark → System. "System" follows the OS setting as it changes. */
export default function ThemeToggle({ className, showLabel = true }: { className?: string; showLabel?: boolean }) {
  const [choice, setChoice] = useState<ThemeChoice>("system");

  useEffect(() => {
    setChoice(getThemeChoice());
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (getThemeChoice() === "system") applyTheme("system");
    };
    media?.addEventListener?.("change", onChange);
    return () => media?.removeEventListener?.("change", onChange);
  }, []);

  const next = nextThemeChoice(choice);
  return (
    <button
      type="button"
      onClick={() => {
        setThemeChoice(next);
        setChoice(next);
      }}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-900",
        className
      )}
      title={`Theme: ${LABEL[choice]} (switch to ${LABEL[next]})`}
      aria-label={`Theme: ${LABEL[choice]}. Switch to ${LABEL[next]}`}
      data-theme-choice={choice}
    >
      {choice === "light" ? <SunIcon /> : choice === "dark" ? <MoonIcon /> : <MonitorIcon />}
      {showLabel && LABEL[choice]}
    </button>
  );
}
