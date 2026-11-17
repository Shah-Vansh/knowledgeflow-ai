import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  esbuild: { jsx: "automatic" }, // React 17+ JSX transform, as Next.js uses
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
});
