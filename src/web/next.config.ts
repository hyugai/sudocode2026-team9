import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // BTC data lives at the repository root; keep the source records read-only.
  turbopack: { root: path.resolve(__dirname, "../..") },
};

export default nextConfig;
