import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "@/components/AuthGate";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "KnowledgeFlow AI",
  description: "Enterprise Knowledge & Research Copilot",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* sets the theme before first paint, so dark mode never flashes white */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="bg-slate-50 text-slate-900">
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}