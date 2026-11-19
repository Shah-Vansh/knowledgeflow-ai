const fs = require("fs");
const path = require("path");

// The project keeps ONE .env file, at the repository root, shared with the backend.
// Next.js only reads .env files inside frontend/, so the public (NEXT_PUBLIC_*) keys
// are copied from the root file here. Only NEXT_PUBLIC_* keys are taken: backend
// secrets in the same file never enter the frontend process. A variable that is
// already set in the real environment (CI, hosting) wins over the file.
function loadPublicEnvFromRoot() {
  const file = path.resolve(__dirname, "..", ".env");
  if (!fs.existsSync(file)) return;
  for (const raw of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    if (!key.startsWith("NEXT_PUBLIC_") || process.env[key] !== undefined) continue;
    let value = line.slice(eq + 1).trim();
    const quoted = value.match(/^(["'])(.*)\1$/);
    if (quoted) value = quoted[2];
    else value = value.replace(/\s+#.*$/, "");
    process.env[key] = value;
  }
}

loadPublicEnvFromRoot();

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

module.exports = nextConfig;
