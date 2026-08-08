import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a minimal server bundle so the container image stays small.
  output: "standalone",
};

export default nextConfig;
