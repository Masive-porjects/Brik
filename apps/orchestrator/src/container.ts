import { Container } from "@cloudflare/containers";

import type { Env } from "./env";

/**
 * Every environment value the FastAPI image needs at runtime, in the canonical
 * AUDIOMIND_* naming that `audiomind/config.py` uses via `env_prefix`.
 * A value that is absent or empty is skipped rather than forwarded as "".
 */
const FORWARDED_ENV_KEYS = [
  // Secrets (wrangler secret bulk).
  "AUDIOMIND_SUPABASE_URL",
  "AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY",
  "AUDIOMIND_R2_ENDPOINT",
  "AUDIOMIND_R2_ACCESS_KEY_ID",
  "AUDIOMIND_R2_SECRET_ACCESS_KEY",
  "AUDIOMIND_R2_BUCKET",
  "GEMINI_API_KEY",
  // Operational config (wrangler.jsonc "vars").
  "AUDIOMIND_PRERENDER_MODE",
  "AUDIOMIND_MAX_CONCURRENT_DSP",
  "AUDIOMIND_DEMO_MAX_DURATION_SECONDS",
  "AUDIOMIND_MAX_FILE_SIZE_MB",
  "AUDIOMIND_SESSION_TTL_MINUTES",
  "AUDIOMIND_DEBUG",
] as const satisfies readonly (keyof Env)[];

/**
 * AudioMind DSP container: the existing FastAPI image (apps/audiomind/Dockerfile).
 *
 * One keyed instance per job/session keeps the backend's in-memory DSP state
 * coherent (AUDIOMIND_MAX_CONCURRENT_DSP=1). The spike uses the single key
 * "dsp-smoke"; phase 3 will key instances per job id once Queues arrive.
 */
export class DSPContainer extends Container<Env> {
  // Must match the Dockerfile: ENV PORT=8000 and the uvicorn CMD default.
  override defaultPort = 8000;

  // Idle lifetime before stop(): the cost lever for standard-4 activity.
  override sleepAfter = "10m";

  // Container instances start with an empty environment. `Container.envVars`
  // defaults to {} in @cloudflare/containers, so Worker secrets never reach
  // the image unless they are copied here before start().
  override envVars: Record<string, string> = Object.fromEntries(
    FORWARDED_ENV_KEYS.flatMap((key) => {
      const value = this.env[key];
      return typeof value === "string" && value.length > 0 ? [[key, value]] : [];
    }),
  );

  override onStart(): void {
    console.log(
      `dsp container started with ${Object.keys(this.envVars).length} forwarded env vars`,
    );
  }

  override onStop(): void {
    console.log("dsp container stopped");
  }

  override onError(error: unknown): void {
    console.error("dsp container error:", error);
  }

  // Spike phase: pass every request straight to the FastAPI app.
  override async fetch(request: Request): Promise<Response> {
    return this.containerFetch(request);
  }
}
