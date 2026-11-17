import type { Metadata } from "next";
import "./globals.css";
import AuthGate from "@/components/AuthGate";

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
    <html lang="en">
      <body className="bg-gray-50 text-gray-900">
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}