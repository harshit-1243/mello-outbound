import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin the workspace root (a stray package-lock.json in the home dir confuses auto-detection).
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
