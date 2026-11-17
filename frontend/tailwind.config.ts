import type { Config } from "tailwindcss";

/** Colour scales read CSS variables (set in globals.css) so one class works in light AND dark mode. */
const v = (name: string) => `rgb(var(--kf-${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        slate: { 50: v("slate-50"), 100: v("slate-100"), 200: v("slate-200"), 300: v("slate-300"), 400: v("slate-400"), 500: v("slate-500"), 600: v("slate-600"), 700: v("slate-700"), 800: v("slate-800"), 900: v("slate-900"), 950: v("slate-950") },
        brand: { 50: v("brand-50"), 100: v("brand-100"), 200: v("brand-200"), 300: v("brand-300"), 400: v("brand-400"), 500: v("brand-500"), 600: v("brand-600"), 700: v("brand-700"), 800: v("brand-800"), 900: v("brand-900") },
        emerald: { 50: v("emerald-50"), 100: v("emerald-100"), 200: v("emerald-200"), 500: v("emerald-500"), 600: v("emerald-600"), 700: v("emerald-700"), 800: v("emerald-800") },
        red: { 50: v("red-50"), 100: v("red-100"), 200: v("red-200"), 500: v("red-500"), 600: v("red-600"), 700: v("red-700"), 800: v("red-800") },
        amber: { 50: v("amber-50"), 100: v("amber-100"), 200: v("amber-200"), 500: v("amber-500"), 600: v("amber-600"), 700: v("amber-700"), 800: v("amber-800") },
        gray: { 50: v("slate-50"), 900: v("slate-900") },
        surface: v("surface"),
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Cascadia Code", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
