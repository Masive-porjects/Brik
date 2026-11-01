/**
 * Bindings and secrets the orchestrator Worker sees.
 *
 * The Worker holds these as encrypted secrets (wrangler secret bulk). They are
 * NOT inherited by container instances: `Container.envVars` defaults to `{}`,
 * so `src/container.ts` forwards every key below explicitly at start time.
 */
export interface Env {
  DSP: DurableObjectNamespace;

  // Supabase (service role: the DSP worker writes sessions/jobs server-side).
  AUDIOMIND_SUPABASE_URL?: string;
  AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY?: string;

  // Cloudflare R2 (mastered/mixed audio destination).
  AUDIOMIND_R2_ENDPOINT?: string;
  AUDIOMIND_R2_ACCESS_KEY_ID?: string;
  AUDIOMIND_R2_SECRET_ACCESS_KEY?: string;
  AUDIOMIND_R2_BUCKET?: string;

  // LLM panel inside the container.
  GEMINI_API_KEY?: string;

  // Operational config (plain "vars", not secrets).
  AUDIOMIND_PRERENDER_MODE?: string;
  AUDIOMIND_MAX_CONCURRENT_DSP?: string;
  AUDIOMIND_DEMO_MAX_DURATION_SECONDS?: string;
  AUDIOMIND_MAX_FILE_SIZE_MB?: string;
  AUDIOMIND_SESSION_TTL_MINUTES?: string;
  AUDIOMIND_DEBUG?: string;
}
