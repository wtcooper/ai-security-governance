import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a minimal server bundle so the container image stays small.
  output: "standalone",
  // `next dev` otherwise writes AGENTS.md and CLAUDE.md into this directory and re-creates
  // them whenever they are deleted. Repository guidance for this project lives at the root,
  // not per-service.
  agentRules: false,
};

export default nextConfig;
