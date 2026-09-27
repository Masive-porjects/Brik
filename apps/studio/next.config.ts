import path from "node:path";
import type { NextConfig } from "next";

// The demo architecture (docs/runbooks/DEMO_DEPLOYMENT_PLAN.md) FORBIDS proxying the
// mastering backend through Next.js: the browser talks to Railway FastAPI
// directly via the absolute NEXT_PUBLIC_API_URL read in
// src/adapters/api/config.ts. There are deliberately NO rewrites here.
const nextConfig: NextConfig = {
  // Deploy under a subpath (NEXT_PUBLIC_BASE_PATH=/waveai) or at root ("").
  basePath: process.env.NEXT_PUBLIC_BASE_PATH ?? "",
  // Imagen Docker (apps/studio/Dockerfile): standalone recorta el runtime a lo
  // que el tracing detecta. En monorepo el tracing debe partir de la raíz o
  // pierde los node_modules del workspace. `next start` sigue funcionando.
  output: "standalone",
  outputFileTracingRoot: path.resolve(__dirname, "../.."),
};

export default nextConfig;
