import type { IntentProfile } from "@midimastering/agent";

import { API_BASE } from "./config";
import { createClient } from "@/lib/supabase/client";

/** Thrown when an API call fails. Carries the HTTP status code. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Measured metrics of the final master (nulls: cache-hit path measures best-effort). */
export interface MasterResultMetrics {
  integrated_lufs: number | null;
  true_peak_db: number | null;
  crest_factor_db: number | null;
  limiter_ceiling_db: number | null;
  duration_seconds: number | null;
  sample_rate: number | null;
  output_bit_depth: number | null;
}

/** Single out-of-tolerance metric found by the Layer 2 gate. */
export interface ValidationIssue {
  metric: "lufs" | "crest" | "true_peak";
  measured: number;
  expected: string;
  message_es: string;
}

/** Post-master validation verdict (null when nothing to validate). */
export interface ValidationReport {
  status: "ok" | "warning";
  issues: ValidationIssue[];
  retry_recommended: boolean;
  retry_applied?: boolean;
  suggested_preset_id?: string | null;
  note?: string | null;
}

/** Delivery compliance report (Compliance Phase 1) — what the engine
 *  actually did to the delivered file. Nullable metrics stay null when
 *  they were never measured (pure passthrough, pre-built cache hits). */
export interface MasteringReport {
  input_sr: number | null; // SR del archivo subido
  output_sr: number | null; // SR entregado (después de SRC)
  output_bit_depth: number | null;
  lufs_i: number | null; // loudness integrada medida del entregado
  true_peak_dbtp: number | null;
  lra: number | null;
  crest_factor_db: number | null;
  target_lufs: number | null; // target REAL usado (null = no se aplicó loudness)
  warnings: string[]; // en español neutro latinoamericano
}

/**
 * Lifecycle of the Mix Engine output of a session (backend contract, T2).
 * ``completed`` is the ONLY value that makes ``mix_path`` masterable, so it
 * is also the client-side meaning of ``hasMix`` (see ``hasCompletedMix``).
 * Optional here so sessions saved before the field existed keep typing.
 */
export type MixStatus = "none" | "processing" | "completed" | "failed";

/** Which audio file a mastering run consumes: the uploaded original or the
 *  delivered Mix Engine output (``POST /process?source=``). */
export type MasterSource = "original" | "mix";

export interface SessionData {
  session_id: string;
  status: "uploaded" | "analyzing" | "processing" | "completed" | "error";
  progress: number;
  original_path: string | null;
  original_filename: string | null;
  mastered_path: string | null;
  analysis: AnalysisResult | null;
  parameters: MasteringParameters;
  master_result?: MasterResultMetrics | null;
  validation?: ValidationReport | null;
  mastering_report?: MasteringReport | null;
  /* ── Mix Engine ── the mix is NOT the master: it lives on its own
     pointer/analysis pair so the mastering pipeline is never affected. */
  mix_path?: string | null;
  mix_analysis?: MixResult | null;
  /* Live state of the mix, owned by the backend (T2): ``processing`` while
     the pipeline runs, ``completed`` when the WAV was delivered, ``failed``
     on error (the last DELIVERED mix_path survives). Kept out of
     ``mix_analysis`` because that one is the snapshot of the last SUCCESSFUL
     mix. Absent = "none" (session predates the field). */
  mix_status?: MixStatus;
  preset_masters?: Record<
    string,
    {
      preset_id: string;
      output_path?: string | null;
      status?: string;
      progress?: number;
      master_result?: MasterResultMetrics | null;
    }
  >;
  error: string | null;
}

export interface AnalysisResult {
  integrated_lufs: number;
  true_peak_db: number;
  dynamic_range_db: number;
  spectral_centroid: number;
  tempo_bpm: number;
  duration_seconds: number;
  sample_rate: number;
  channels: number;
  detected_genre: string;
  genre_confidence: number;
  crest_factor_db?: number;
  is_already_mastered?: boolean;
  mastering_confidence?: number;
}

/** Module-based mastering controls (replaces old fixed presets). */
export interface MasteringParameters {
  clarity_wet: number;
  clarity_brightness_db: number;
  compression_ratio: number;
  limiter_ceiling_db: number;
  transient_boost_db: number;
  saturation_drive_db: number;
  saturation_warmth_db: number;
  stereo_width: number;
  haas_delay_ms: number;
  output_bit_depth: number;
  target_lufs_db?: number;
  /* ── Delivery / Compliance (Phase 1) ── defaults mirror the backend
     (models/audio.py) so an untouched form stays byte-identical neutral. */
  processing_mode: "master" | "transparent";
  platform_target?: "spotify" | "apple_music" | "youtube" | "tidal" | "custom";
  output_sr: "same_as_input" | "44100" | "48000" | "96000";
  strict_mode: boolean;
}

export const DEFAULT_PARAMS: MasteringParameters = {
  clarity_wet: 0.15,
  clarity_brightness_db: 1.0,
  compression_ratio: 2.0,
  limiter_ceiling_db: -1.0,
  transient_boost_db: 0.0,
  saturation_drive_db: 0.0,
  saturation_warmth_db: 0.0,
  stereo_width: 1.0,
  haas_delay_ms: 0.0,
  output_bit_depth: 24,
  processing_mode: "master",
  output_sr: "same_as_input",
  strict_mode: false,
};

export async function uploadAudio(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<SessionData> {
  const formData = new FormData();
  formData.append("file", file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    // Real upload progress (bytes sent vs total file size).
    xhr.upload.onprogress = (e: ProgressEvent) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.open("POST", `${API_BASE}/upload`, true);

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        try {
          resolve(xhr.response as SessionData);
        } catch {
          reject(new ApiError("Upload failed parsing response", xhr.status));
        }
      } else {
        let detail = "Upload failed";
        try {
          detail = JSON.parse(xhr.responseText)?.detail || detail;
        } catch {}
        reject(new ApiError(detail, xhr.status));
      }
    };

    xhr.onerror = () => reject(new ApiError("Upload failed", 0));
    xhr.responseType = "json";
    xhr.send(formData);
  });
}

export async function getSession(sessionId: string): Promise<SessionData> {
  const res = await fetch(`${API_BASE}/session/${sessionId}`);
  if (!res.ok) throw new ApiError("Session not found", res.status);
  return res.json();
}

export interface ProcessingProgress {
  progress: number; // 0.0 - 1.0 from the backend
  status: string;
}

export async function getProcessingProgress(sessionId: string): Promise<ProcessingProgress> {
  const res = await fetch(`${API_BASE}/session/${sessionId}`);
  if (!res.ok) throw new ApiError(`Progress fetch failed: ${res.status}`, res.status);
  const data = (await res.json()) as SessionData;
  return { progress: data.progress ?? 0, status: data.status ?? "" };
}

export async function processAudio(
  sessionId: string,
  parameters: MasteringParameters,
  signal?: AbortSignal,
  presetId?: string,
  source?: MasterSource,
): Promise<SessionData> {
  const url = new URL(`${API_BASE}/session/${sessionId}/process`);
  if (presetId) {
    url.searchParams.set("preset_id", presetId);
  }
  // Explicit source (T2): the client decides WHICH file the run consumes
  // instead of relying on the backend's smart default. Omitting it keeps the
  // historic smart resolution (mix only when it is completed and on disk).
  if (source) {
    url.searchParams.set("source", source);
  }
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...licenseHeaders() },
    body: JSON.stringify(parameters),
    signal,
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .catch(() => ({ detail: undefined }))
      .then((b) => (b as { detail?: unknown }).detail);
    // Surfacing strategy for transient/infrastructure failures on /process:
    // the backend raw detail for a 502 (gateway/timeout) or 404 (in-memory
    // session lost to a restart) is not actionable — the fix is to re-upload
    // the file. Detect those and show a clear retry prompt instead of a raw
    // backend string, so the app never dies silently mid-master.
    const retryUpload = (reason: string) =>
      new Error(
        `${reason} El servidor no pudo completar el procesamiento. Reintentá la subida del archivo para volver a empezar.`,
      );
    switch (res.status) {
      case 502:
        throw retryUpload("El servidor de audio no respondió (502).");
      case 404:
        throw retryUpload("La sesión expiró (404).");
      default:
        // Surface the backend's detail (e.g. strict_mode 422 rejection) the
        // same way uploadAudio does — never swallow the message.
        throw new Error(
          (detail as string | undefined) || "Processing failed",
        );
    }
  }
  return res.json();
}

export async function resetSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionData> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...licenseHeaders() },
    signal,
  });
  if (!res.ok) throw new Error("Reset failed");
  return res.json();
}

export function getAudioUrl(
  sessionId: string,
  type: "original" | "mastered",
  presetId?: string,
): string {
  let url = `${API_BASE}/session/${sessionId}/audio/${type}`;
  if (type === "mastered" && presetId) {
    url += `?preset_id=${encodeURIComponent(presetId)}`;
  }
  return url;
}

export function getDownloadUrl(
  sessionId: string,
  format: "wav" | "mp3",
  presetId?: string,
): string {
  let url = `${API_BASE}/session/${sessionId}/download/${format}`;
  if (presetId) {
    url += `?preset_id=${encodeURIComponent(presetId)}`;
  }
  return url;
}

/* ── Crudo Reference (Layer 3 fair A/B) ─────────────── */

/** Result of the on-demand neutral (Crudo) reference render. */
export interface ReferenceResult {
  reference_path: string;
  target_lufs: number;
  source_preset_id: string;
}

/**
 * Render the neutral reference loudness-matched to the preset master:
 * natural chain character + the preset's target_lufs/limiter ceiling.
 * Cached server-side per session+preset.
 */
export async function renderReference(
  sessionId: string,
  presetId: string,
): Promise<ReferenceResult> {
  const res = await fetch(
    `${API_BASE}/session/${sessionId}/reference/${encodeURIComponent(presetId)}`,
    { method: "POST", headers: { ...licenseHeaders() } },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Reference render failed" }));
    throw new Error(err.detail || "Reference render failed");
  }
  return res.json();
}

export function getReferenceAudioUrl(sessionId: string, presetId: string): string {
  return `${API_BASE}/session/${sessionId}/audio/reference/${encodeURIComponent(presetId)}`;
}

/* ── License ──────────────────────────────────────────── */

export function getStoredLicenseKey(): string | null {
  if (typeof window === "undefined") return null;
  // sessionStorage se borra al cerrar la pestaña — así cada sesión pide la clave
  return sessionStorage.getItem("waveai_license_key");
}

export function licenseHeaders(): Record<string, string> {
  const key = getStoredLicenseKey();
  return key ? { "X-License-Key": key } : {};
}

/**
 * Headers for the authenticated `/projects/*` endpoints.
 *
 * Extends {@link licenseHeaders} with the Supabase bearer token the backend
 * requires (`api/auth.py` `get_user_context`); in production the token is what
 * resolves the caller to a user, and without it every `/projects/*` call is a
 * 401. `getSession()` reads the stored session and works outside React.
 *
 * Never throws: when Supabase is not configured (local dev) or there is no
 * session, it returns only the license headers so the call still reaches the
 * backend and the dev fallback applies.
 */
export async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...licenseHeaders() };
  try {
    const {
      data: { session },
    } = await createClient().auth.getSession();
    if (session?.access_token) {
      headers.Authorization = `Bearer ${session.access_token}`;
    }
  } catch {
    // No browser client (env missing) or getSession failed: proceed without
    // auth rather than breaking the call, matching the dev/no-session path.
  }
  return headers;
}

export interface LicenseStatus {
  licensed: boolean;
  message: string;
}

export async function checkLicense(): Promise<LicenseStatus> {
  const res = await fetch(`${API_BASE}/license/status`);
  if (!res.ok) return { licensed: false, message: "Error al verificar licencia" };
  return res.json();
}

export async function activateLicense(
  key: string,
): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/license/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Activación fallida" }));
    throw new Error(err.detail || "Activación fallida");
  }
  return res.json();
}

/* ── Stem Splitter ───────────────────────────────────── */

export interface StemSplitResult {
  session_id: string;
  status: string;
  stems: Record<string, string>;
  sample_rate: number;
  duration_seconds: number;
}

export async function splitStems(
  sessionId: string,
  model: string = "htdemucs",
): Promise<StemSplitResult> {
  const res = await fetch(
    `${API_BASE}/session/${sessionId}/split?model=${model}`,
    {
      method: "POST",
      headers: { ...licenseHeaders() },
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Stem split failed" }));
    throw new Error(err.detail || "Stem split failed");
  }
  return res.json();
}

export async function listStems(sessionId: string): Promise<StemSplitResult> {
  const res = await fetch(`${API_BASE}/session/${sessionId}/stems`);
  if (!res.ok) throw new Error("Failed to list stems");
  return res.json();
}

export function getStemUrl(sessionId: string, stemName: string): string {
  return `${API_BASE}/session/${sessionId}/stem/${stemName}`;
}

export async function downloadStem(
  sessionId: string,
  stemName: string,
): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/session/${sessionId}/stem/${stemName}`,
    { headers: { ...licenseHeaders() } },
  );
  if (!res.ok) throw new Error("Failed to download stem");
  return res.blob();
}

/* ── Mix Engine ─────────────────────────────────────── */

/**
 * JSON payload served in the ``X-Mix-Result`` header by
 * POST /session/{id}/mix (and mirrored on the session as
 * ``mix_analysis``). Every field is optional on purpose: the backend
 * includes or omits each report depending on which DSP steps ran, so
 * parsing never breaks when a key is missing.
 */
export interface MixResult {
  analysis?: Record<string, unknown>;
  /** Real per-stem presence measured by the backend (per-stem RMS ≥
   *  −50 dBFS on the source stems). Optional/backward-compatible: older
   *  mixes without the key simply show no stem chips. */
  stem_presence?: Record<string, boolean>;
  tempo_bpm?: number | null;
  genre?: string | null;
  genre_confidence?: number | null;
  sample_rate?: number | null;
  duration_seconds?: number | null;
  pan_report?: unknown;
  dimension_report?: unknown;
  compressor_report?: unknown;
  emphasis_report?: unknown;
  qc_report?: unknown;
  versions?: Record<string, unknown> | null;
  /** T4 — stem auto-balance report (backend, only when auto_balance=true).
   *  Shape: { genre, genre_confidence, status, stem_lufs,
   *  groove_level_lufs, vocal_target_lufs, d, gains, applied }. */
  balance_report?: unknown;
  /** T5 — manual stem faders report (backend, only when a trim ≠ 0 is
   *  sent). Shape: { gains: {*_db}, applied }. */
  trim_report?: unknown;
  /** P5 — character stage report (backend, only when character ran).
   *  Shape: { profile, seed, ... }. */
  character_report?: unknown;
}

/**
 * Run the Mix Engine (8-step DSP build) for a session and return the
 * mixed WAV as a blob objectURL plus the analysis JSON parsed from the
 * ``X-Mix-Result`` response header. The optional JSON body toggles the
 * spatial dimension stage (Paso 04: tempo delay + reverb per stem):
 * ``dimensionEnabled`` defaults to ``true`` (current behaviour);
 * ``false`` routes the stems exactly like Paso 03 — the backend omits
 * ``dimension_report`` from the payload. The same body accepts the stem
 * balance options (T5/T6): ``autoBalance`` sends ``auto_balance: true``
 * (the engine measures and corrects the voice toward the genre target,
 * reporting ``balance_report``) and ``stemTrims`` sends the manual
 * faders as ``stem_trims`` (only keys ≠ 0; all-zero/absent keeps the
 * previous payload exactly — no ``trim_report``).
 */
export async function mixTracks(
  sessionId: string,
  options?: {
    signal?: AbortSignal;
    dimensionEnabled?: boolean;
    autoBalance?: boolean;
    stemTrims?: Record<string, number>;
    character?: string | null;
  },
): Promise<{ audioUrl: string; audioBlob: Blob; result: MixResult | null }> {
  const body: Record<string, unknown> = {
    dimension_enabled: options?.dimensionEnabled ?? true,
  };
  if (options?.autoBalance) body.auto_balance = true;
  const stemTrims = Object.fromEntries(
    Object.entries(options?.stemTrims ?? {}).filter(([, db]) => db !== 0),
  );
  if (Object.keys(stemTrims).length > 0) body.stem_trims = stemTrims;
  if (options?.character) body.character = options.character;
  const res = await fetch(`${API_BASE}/session/${sessionId}/mix`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...licenseHeaders() },
    body: JSON.stringify(body),
    ...(options?.signal ? { signal: options.signal } : {}),
  });
  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Mix failed" }));
    throw new Error(
      (err as { detail?: string }).detail || "Mix failed",
    );
  }
  const audioBlob = await res.blob();
  let result: MixResult | null = null;
  // HTTP headers are case-insensitive; read both spellings defensively.
  const raw =
    res.headers.get("X-Mix-Result") ?? res.headers.get("x-mix-result");
  if (raw) {
    try {
      result = JSON.parse(raw) as MixResult;
    } catch {
      result = null; // header malformed → analysis unavailable, audio still works
    }
  }
  return { audioUrl: URL.createObjectURL(audioBlob), audioBlob, result };
}

/** Stable URL of the persisted mix WAV (survives session reload). */
export function getMixAudioUrl(sessionId: string): string {
  return `${API_BASE}/session/${sessionId}/audio/mix`;
}

/* ── Async mix jobs ────────────────────────────────────────── */

/** Job state of a submitted mix. Same vocabulary as the mastering jobs in
 *  this file on purpose: one polling client and one UI state machine for
 *  every job kind, instead of two incompatible job systems. */
export type MixJobStatus = "processing" | "completed" | "error";

export interface MixJobAccepted {
  job_id: string;
  session_id: string;
  status: MixJobStatus;
  poll_url: string;
}

export interface MixJobState {
  job_id: string;
  kind: string;
  status: MixJobStatus;
  /** 0..100 as reported by the backend. 0 until the mix is really in R2. */
  progress: number;
  stage: string | null;
  session_id: string | null;
  /** Present once completed: R2 key, presigned download URL and analysis. */
  result?: {
    r2_key?: string;
    download_url?: string;
    content_type?: string;
    analysis?: MixResult | null;
    mix_status?: string;
  };
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Queue the Mix Engine for a session and return immediately.
 *
 * The blocking `mixTracks` holds the HTTP connection for the whole DSP chain,
 * which is what an edge proxy answers with 502/504 once the mix outlasts the
 * proxy timeout. This returns in milliseconds with a job id to poll.
 *
 * The options mirror the blocking endpoint exactly, so the same mix can be
 * requested either way.
 */
export async function submitMixJob(
  sessionId: string,
  options?: {
    dimensionEnabled?: boolean;
    autoBalance?: boolean;
    stemTrims?: Record<string, number>;
    character?: string | null;
  },
  signal?: AbortSignal,
): Promise<MixJobAccepted> {
  const body: Record<string, unknown> = {
    dimension_enabled: options?.dimensionEnabled ?? true,
  };
  if (options?.autoBalance) body.auto_balance = true;
  const stemTrims = Object.fromEntries(
    Object.entries(options?.stemTrims ?? {}).filter(([, db]) => db !== 0),
  );
  if (Object.keys(stemTrims).length > 0) body.stem_trims = stemTrims;
  if (options?.character) body.character = options.character;

  const res = await fetch(`${API_BASE}/jobs/mix/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...licenseHeaders() },
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
  });
  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Mix job could not be submitted" }));
    throw new ApiError(
      (err as { detail?: string }).detail || "Mix job could not be submitted",
      res.status,
    );
  }
  return res.json();
}

/** Read the current state of a submitted mix job. */
export async function getMixJobState(
  jobId: string,
  signal?: AbortSignal,
): Promise<MixJobState> {
  const res = await fetch(`${API_BASE}/jobs/mix/${encodeURIComponent(jobId)}`, {
    headers: { ...licenseHeaders() },
    ...(signal ? { signal } : {}),
  });
  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Mix job status check failed" }));
    throw new ApiError(
      (err as { detail?: string }).detail || "Mix job status check failed",
      res.status,
    );
  }
  return res.json();
}

/* ── Agentic producer jobs (Productor IA) ─────────────────── */

/** Job state of a submitted agent run. Same vocabulary as the mix and
 *  mastering jobs in this file on purpose: one polling client and one UI
 *  state machine for every job kind. */
export type AgentJobStatus = "processing" | "completed" | "error";

export interface AgentJobAccepted {
  job_id: string;
  session_id: string;
  status: AgentJobStatus;
  /** Backend-relative path to poll. Kept for parity with the mix job. */
  poll_url: string;
}

/** One tool the loop really executed, in order.
 *
 *  Recorded at dispatch time by the backend, never reconstructed from the
 *  state the run left behind: "it separated stems" is a fact only because the
 *  tool ran, not because a stem exists. */
export interface AgentToolExecution {
  tool: string;
  ok: boolean;
  detail: string;
  /** Raw tool payload. Includes the file paths the tool used, which the
   *  curated `mix_metrics` / `master_metrics` deliberately drop. */
  payload: Record<string, unknown>;
  error: string | null;
}

/** Bus metrics of the last render (backend: `agentic_loop.bus_metrics`).
 *
 *  The same field list the `analyze_mix_bus` tool returns, so the UI cannot
 *  read a metric the agent never measured. Null when the run never rendered. */
export interface AgentMixMetrics {
  qc_report: Record<string, unknown>;
  balance_report: Record<string, unknown> | null;
  trim_report: Record<string, unknown> | null;
  stem_presence: Record<string, boolean> | null;
  stem_lufs: Record<string, number> | null;
  tempo_bpm: number | null;
  genre: string | null;
  /** How many mix/analyze iterations the loop needed. */
  iteration: number;
}

/** Measured numbers of the delivered master.
 *
 *  The ephemeral `master_path` / `source_path` are stripped by the backend, so
 *  only measurements travel here. They remain in `tools_executed[].payload`,
 *  which is raw evidence. */
export interface AgentMasterMetrics {
  source?: "mix" | "original";
  target_lufs_db?: number | null;
  output_bit_depth?: number | null;
  integrated_lufs?: number | null;
  true_peak_db?: number | null;
  crest_factor_db?: number | null;
  lra?: number | null;
  duration_seconds?: number | null;
  /** Wall-clock seconds the mastering chain took. */
  seconds?: number;
  [key: string]: unknown;
}

/** Where one agent output can be fetched from.
 *
 *  `durable: false` means R2 was unconfigured when the job ran: `url` is null
 *  and `local_path` points at the backend filesystem, which does not survive a
 *  redeploy. Render the note, do not hide it. */
export interface AgentAudioAsset {
  r2_key: string | null;
  url: string | null;
  local_path: string | null;
  durable: boolean;
  note: string | null;
}

/** One band that sits away from the genre target (mirrors backend `Deficiency`). */
export interface Deficiency {
  band_hz: number;
  delta_db: number;
  direction: "lacks" | "excess";
}

/** A processing path Brik proposes (mirrors backend `Route`). */
export interface Route {
  id: "mix_then_master" | "master_only";
  label_es: string;
  description_es: string;
  recommended: boolean;
}

/** Brik's routing verdict for one track (mirrors backend `AudioVerdict`). */
export interface AudioVerdict {
  needs_mix: boolean;
  confidence: number;
  recommended_path: "mix_then_master" | "master_only";
  reasoning_key:
    | "raw_mix_detected"
    | "finished_mix_detected"
    | "already_mastered"
    | "unmeasurable";
  deficiencies: Deficiency[];
  routes: Route[];
}

/** Decision the user (or Brik in auto mode) picked (mirrors backend `DecisionRecord`). */
export interface DecisionRecord {
  requested: "auto" | "mix_then_master" | "master_only";
  applied: "mix_then_master" | "master_only";
}

/** Payload of a completed agent job: what the agent decided, did, measured
 *  and left behind. Every field comes from recorded evidence. */
export interface AgentRunResult {
  session_id: string;
  /** The model's own diagnosis, in its own words. Null when the run never got
   *  past the first turn. */
  diagnosis: string | null;
  iterations: number;
  /** The 9 semantic axes the mapper turned into DSP knobs. */
  intent: IntentProfile;
  analysis: AnalysisResult | null;
  /** The verdict (analysis phase only). Null for legacy runs. */
  verdict: AudioVerdict | null;
  /** The decision that was applied (after user choice or auto). */
  decision: DecisionRecord | null;
  /** Null when the run never rendered a mix. */
  mix_metrics: AgentMixMetrics | null;
  /** Null when the run never mastered. */
  master_metrics: AgentMasterMetrics | null;
  tools_executed: AgentToolExecution[];
  audio: {
    mix: AgentAudioAsset | null;
    master: AgentAudioAsset | null;
  };
}

export interface AgentJobState {
  job_id: string;
  kind: string;
  status: AgentJobStatus;
  /** 0..100 as reported by the backend. The loop exposes no phase callback
   *  yet, so this stays 0 until the job finishes: show an indeterminate
   *  spinner, not a progress bar. */
  progress: number;
  stage: string | null;
  session_id: string | null;
  /** Present once completed. The audio URLs inside are re-signed per read. */
  result?: AgentRunResult;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Queue the Productor IA ANALYSIS JOB for a session and return immediately.
 *
 * This runs ONLY phase 1 (diagnosis + verdict) — no Demucs, no mix, no master.
 * Returns in ~3s vs minutes for the full job. The result contains the verdict
 * so the UI can show Brik's recommendation and let the user choose a route.
 */
export async function submitAgentAnalyzeJob(
  sessionId: string,
  prompt?: string,
  signal?: AbortSignal,
): Promise<AgentJobAccepted> {
  const body: Record<string, unknown> = {};
  const clean = prompt?.trim();
  if (clean) body.prompt = clean;

  const res = await fetch(
    `${API_BASE}/jobs/agent/${encodeURIComponent(sessionId)}/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...licenseHeaders() },
      body: JSON.stringify(body),
      ...(signal ? { signal } : {}),
    },
  );
  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Agent analyze job could not be submitted" }));
    throw new ApiError(
      (err as { detail?: string }).detail ||
        "Agent analyze job could not be submitted",
      res.status,
    );
  }
  return res.json();
}

/**
 * Queue the Productor IA for a session and return immediately.
 *
 * There is no blocking counterpart: a full run is Demucs plus the mix chain
 * plus N LLM turns, which an edge proxy answers with 502/504 once it outlasts
 * the proxy timeout. This returns in milliseconds with a job id to poll.
 *
 * `prompt` is the user's own words ("make the vocal sit forward"). It rides on
 * the loop's first turn, so both the diagnosis and the mix see it. Omitted or
 * blank keeps the loop's default directive.
 *
 * `decision` tells the backend which route to take: "auto" (default, Brik
 * follows the verdict), "mix_then_master" (force full chain), or
 * "master_only" (skip separation, master the original directly).
 *
 * A deployment with no usable LLM credential answers 503 here, at submit time,
 * instead of starting a job that dies minutes later.
 */
export async function submitAgentJob(
  sessionId: string,
  prompt?: string,
  decision?: "auto" | "mix_then_master" | "master_only",
  signal?: AbortSignal,
): Promise<AgentJobAccepted> {
  const body: Record<string, unknown> = {};
  const clean = prompt?.trim();
  if (clean) body.prompt = clean;
  if (decision) body.decision = decision;

  const res = await fetch(
    `${API_BASE}/jobs/agent/${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...licenseHeaders() },
      body: JSON.stringify(body),
      ...(signal ? { signal } : {}),
    },
  );
  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Agent job could not be submitted" }));
    throw new ApiError(
      (err as { detail?: string }).detail || "Agent job could not be submitted",
      res.status,
    );
  }
  return res.json();
}

/**
 * Read the current state of a submitted agent job.
 *
 * Poll this for the player instead of caching a URL from an earlier response:
 * the backend re-mints each audio URL on every read, so a stored one 403s once
 * it expires.
 *
 * A job whose worker died mid-run reports `error` with an interruption
 * message, so a dead worker never leaves the UI polling forever.
 */
export async function getAgentJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<AgentJobState> {
  const res = await fetch(`${API_BASE}/jobs/agent/${encodeURIComponent(jobId)}`, {
    headers: { ...licenseHeaders() },
    ...(signal ? { signal } : {}),
  });
  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Agent job status check failed" }));
    throw new ApiError(
      (err as { detail?: string }).detail || "Agent job status check failed",
      res.status,
    );
  }
  return res.json();
}

/* ── SongStarter ──────────────────────────────────── */

export interface BeatParams {
  bpm: number;
  scale: string;
  root_note: string;
  swing_amount?: number;
}

export interface BeatResponse {
  beat_id: string;
  bpm: number;
  scale: string;
  root_note: string;
  swing_amount: number;
  duration: number;
  output_path: string;
  stems: Record<string, string>;
}

export interface SavedBeat {
  id: string;
  name?: string;
  bpm: number;
  scale: string;
  root_note: string;
  swing_amount: number;
  duration: number;
  created_at: string;
}

export async function generateBeat(
  sessionId: string,
  params: BeatParams,
): Promise<BeatResponse> {
  const res = await fetch(
    `${API_BASE}/session/${sessionId}/beat/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Beat generation failed" }));
    throw new Error(err.detail || "Beat generation failed");
  }
  return res.json();
}

export async function saveBeat(
  sessionId: string,
  beatId: string,
  name?: string,
  params?: BeatParams,
): Promise<{ message: string; beat_id: string }> {
  const body: Record<string, unknown> = { session_id: sessionId, beat_id: beatId };
  if (name) body.name = name;
  if (params) {
    body.bpm = params.bpm;
    body.scale = params.scale;
    body.root_note = params.root_note;
    body.swing_amount = params.swing_amount ?? 0.3;
  }
  const res = await fetch(`${API_BASE}/beat/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Save failed" }));
    throw new Error(err.detail || "Save failed");
  }
  return res.json();
}

export async function listBeats(): Promise<SavedBeat[]> {
  const res = await fetch(`${API_BASE}/beats`);
  if (!res.ok) throw new Error("Failed to list beats");
  return res.json();
}

export async function getBeat(beatId: string): Promise<SavedBeat> {
  const res = await fetch(`${API_BASE}/beat/${beatId}`);
  if (!res.ok) throw new Error("Beat not found");
  return res.json();
}

export async function deleteBeat(beatId: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/beat/${beatId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete beat");
  return res.json();
}

export function getBeatAudioUrl(sessionId: string, beatId: string, stem?: string): string {
  let url = `${API_BASE}/session/${sessionId}/beat/${beatId}/audio`;
  if (stem) url += `?stem=${encodeURIComponent(stem)}`;
  return url;
}

export function getSavedBeatAudioUrl(beatId: string, stem?: string): string {
  let url = `${API_BASE}/beat/${beatId}/audio`;
  if (stem) url += `?stem=${encodeURIComponent(stem)}`;
  return url;
}

export async function downloadMastered(
  sessionId: string,
  format: "wav" | "mp3",
  presetId?: string,
): Promise<Blob> {
  let url = `${API_BASE}/session/${sessionId}/download/${format}`;
  if (presetId) {
    url += `?preset_id=${encodeURIComponent(presetId)}`;
  }
  const res = await fetch(url, { headers: { ...licenseHeaders() } });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Descarga fallida" }));
    throw new Error(err.detail || "Descarga fallida");
  }
  return res.blob();
}

/** Payload for submitting a cloud DSP mastering job (Fase 6). */
export interface MasterJobPayload {
  track_id: string;
  user_id?: string;
  version_id?: string;
  input_audio_url?: string;
  input_storage_path?: string;
  preset_id?: string;
  parameters?: Partial<MasteringParameters>;
  platform_target?: "spotify" | "apple_music" | "youtube" | "tidal" | "club" | "cd" | "custom";
  format?: "wav" | "mp3";
  output_bit_depth?: number;
  master_name?: string;
  is_async?: boolean;
}

/** Result from a synchronous or completed mastering worker job. */
export interface MasterJobResult {
  success: boolean;
  job_id: string;
  track_id: string;
  master_id: string;
  status: string;
  storage_path?: string;
  download_url?: string;
  file_size_bytes: number;
  format: "wav" | "mp3";
  metrics?: MasterResultMetrics;
  validation?: ValidationReport;
  report?: MasteringReport;
  error?: string;
}

/** Async job status returned when polling background jobs. */
export interface AsyncJobStatus {
  job_id: string;
  track_id: string;
  status: "processing" | "completed" | "error";
  progress?: number;
  result?: MasterJobResult;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

/**
 * Submits a stateless DSP mastering job to AudioMind.
 * Can execute synchronously or enqueued in the background.
 */
export async function submitMasterJob(
  payload: MasterJobPayload,
): Promise<MasterJobResult> {
  const res = await fetch(`${API_BASE}/jobs/master`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...licenseHeaders(),
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Mastering job failed" }));
    throw new ApiError(err.detail || "Mastering job failed", res.status);
  }

  return res.json();
}

/**
 * Polls the current status of an asynchronous mastering job.
 */
export async function getMasterJobStatus(jobId: string): Promise<AsyncJobStatus> {
  const res = await fetch(`${API_BASE}/jobs/master/${encodeURIComponent(jobId)}`, {
    headers: { ...licenseHeaders() },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Job status check failed" }));
    throw new ApiError(err.detail || "Job status check failed", res.status);
  }

  return res.json();
}

/* ── Project Document & State (WU3) ───────────────────────────────── */

/**
 * The four Demucs stems, in the engine's order. Mirrors the backend
 * `StemName` literal (`models/project_document.py`).
 */
export type StemName = "drums" | "bass" | "other" | "vocals";

/** Identity/presentation of one stem (no audio, no gain). Mirrors backend `StemNode`. */
export interface StemNode {
  display_name: string;
  /** 0..3, mirrors the engine order. */
  order: number;
  group_id?: string | null;
  color_token?: string | null;
  hidden: boolean;
}

/** A UI grouping of stems. Mirrors backend `Group`. */
export interface Group {
  id: string;
  display_name: string;
  order: number;
  color_token?: string | null;
}

/**
 * A pending intent change proposed by the Intelligence. Never audible on its
 * own: it becomes sound only when applied to `project_states` by the user.
 * Mirrors backend `Proposal`.
 */
export interface Proposal {
  /** UUID. */
  id: string;
  kind: "fader" | "toggle" | "master";
  payload: Record<string, unknown>;
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  rationale?: string | null;
  decided_at?: string | null;
}

/** The musical intent of the mix. Mirrors backend `MixIntent`. */
export interface MixIntent {
  genre?: string | null;
  character?: string | null;
  proposals: Proposal[];
}

/** Delivery intent for the master job. Mirrors backend `MasterIntent`. */
export interface MasterIntent {
  preset_id:
    | "universal"
    | "fuego"
    | "claridad"
    | "cinta"
    | "natural"
    | "espacial"
    | "cinematico"
    | "empuje"
    | null;
  /** 7-value payload set (NOT the 5-value `MasteringParameters.platform_target`). */
  platform_target:
    | "spotify"
    | "apple_music"
    | "youtube"
    | "tidal"
    | "club"
    | "cd"
    | "custom"
    | null;
  format: "wav" | "mp3";
  /** 16..32. */
  output_bit_depth: number;
  master_name?: string | null;
  parameters?: Record<string, unknown> | null;
}

/**
 * V1 project document: intention + structure of one project. Mirrors the
 * backend `ProjectDocument` and the JSON Schema in
 * `docs/reference/specs/project_document_v1_spec.md` §3, field for field.
 */
export interface ProjectDocumentV1 {
  schema_version: 1;
  structure: {
    stems: Record<StemName, StemNode>;
    groups: Group[];
  };
  mix_intent: MixIntent;
  master_intent: MasterIntent;
  updated_by: "user" | "intelligence" | "system";
  updated_at: string | null;
}

/** GET/PUT /projects/{id}/document response, normalized to camelCase. */
export interface ProjectDocumentResponse {
  projectId: string;
  version: number;
  document: ProjectDocumentV1;
  updatedAt: string | null;
}

/** PUT /projects/{id}/document payload. `expected_version` is snake_case
 *  because the backend `DocumentPut` model has `extra="forbid"`. */
export interface PutDocumentPayload {
  document: ProjectDocumentV1;
  expected_version: number;
}

/** A single snapshot of the live mix for undo/redo. */
export interface MixSnapshot {
  faders: Record<string, number>;
  toggles: Record<string, unknown>;
  timestamp: number;
}

/** PATCH /projects/{id}/state request body (snake_case, backend contract). */
export interface MixStatePayload {
  state: {
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
  };
  undo_stack: MixSnapshot[];
}

/** GET/PATCH /projects/{id}/state response, normalized to camelCase. */
export interface MixStateResponse {
  projectId: string;
  state: {
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
  };
  undoStack: MixSnapshot[];
  updatedAt: string | null;
}

/** POST /projects/{id}/jobs/{mix,master} response, normalized to camelCase. */
export interface ProjectJobAccepted {
  jobId: string;
  pollUrl: string;
}

/** Raw wire shape of a project document row (snake_case from the backend). */
interface RawProjectDocumentResponse {
  project_id: string;
  version: number;
  document: ProjectDocumentV1;
  updated_at: string | null;
}

/** Raw wire shape of the mix state (snake_case from the backend). */
interface RawMixStateResponse {
  project_id: string;
  state: MixStateResponse["state"];
  undo_stack: MixSnapshot[];
  updated_at: string | null;
}

/** Raw wire shape of a project job submit (snake_case from the backend). */
interface RawProjectJobResponse {
  job_id: string;
  poll_url: string;
}

/** Normalizes a raw project document row to camelCase (B2). */
function toProjectDocumentResponse(
  raw: RawProjectDocumentResponse,
): ProjectDocumentResponse {
  return {
    projectId: raw.project_id,
    version: raw.version,
    document: raw.document,
    updatedAt: raw.updated_at,
  };
}

/** Normalizes a raw mix state row to camelCase (B2). */
function toMixStateResponse(raw: RawMixStateResponse): MixStateResponse {
  return {
    projectId: raw.project_id,
    state: raw.state,
    undoStack: raw.undo_stack ?? [],
    updatedAt: raw.updated_at,
  };
}

/** Fetches the V1 project document (bootstrap if none). */
export async function getProjectDocument(
  projectId: string
): Promise<ProjectDocumentResponse> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new ApiError("Failed to fetch project document", res.status);
  return toProjectDocumentResponse(await res.json());
}

/** Writes the V1 project document with OCC. */
export async function putProjectDocument(
  projectId: string,
  payload: PutDocumentPayload
): Promise<ProjectDocumentResponse> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError("Failed to write project document", res.status);
  return toProjectDocumentResponse(await res.json());
}

/** Deletes the project document (resets to bootstrap). */
export async function deleteProjectDocument(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    method: "DELETE",
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new ApiError("Failed to delete project document", res.status);
}

/** Fetches the live mix state. */
export async function getProjectMixState(
  projectId: string
): Promise<MixStateResponse> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/state`, {
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new ApiError("Failed to fetch mix state", res.status);
  return toMixStateResponse(await res.json());
}

/** Updates the live mix state (debounced by caller). The request body stays
 *  snake_case (`{ state, undo_stack }`) because the backend requires it. */
export async function patchProjectMixState(
  projectId: string,
  payload: MixStatePayload
): Promise<MixStateResponse> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/state`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError("Failed to update mix state", res.status);
  return toMixStateResponse(await res.json());
}

/** Submits a mix job for a project (returns job id + poll URL). */
export async function submitProjectMixJob(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectJobAccepted> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/jobs/mix`, {
    method: "POST",
    headers: { ...(await authHeaders()) },
    signal,
  });
  if (!res.ok) throw new ApiError("Failed to submit mix job", res.status);
  const raw = (await res.json()) as RawProjectJobResponse;
  return { jobId: raw.job_id, pollUrl: raw.poll_url };
}

/** Submits a mastering job for a project (returns job id + poll URL). */
export async function submitProjectMasterJob(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectJobAccepted> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/jobs/master`, {
    method: "POST",
    headers: { ...(await authHeaders()) },
    signal,
  });
  if (!res.ok) throw new ApiError("Failed to submit mastering job", res.status);
  const raw = (await res.json()) as RawProjectJobResponse;
  return { jobId: raw.job_id, pollUrl: raw.poll_url };
}

/* ── Project assets (subida directa a R2) ─────────────────────────────── */

/** Tipos de asset aceptados por el backend (literal `AssetKind`). */
export type AssetKind = "original" | "stem" | "master";

/** Una fila de `projects`, normalizada a camelCase. Espeja `ProjectOut`. */
export interface ProjectOut {
  id: string;
  userId: string;
  name: string;
  bpm: number | null;
  musicalKey: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/** Cuerpo de `POST /projects/{id}/assets/presign` (snake_case en el cable). */
export interface PresignAssetInput {
  kind: AssetKind;
  stemName?: string;
  originalFilename?: string;
  contentType?: string;
}

/** Respuesta de `POST /projects/{id}/assets/presign`, normalizada. */
export interface PresignedAsset {
  assetId: string;
  projectId: string;
  r2Key: string;
  putUrl: string;
  contentType: string;
  expiresIn: number;
}

/** Cuerpo de `PATCH /projects/{id}/assets/{asset_id}` (snake_case). */
export interface AssetCompleteInput {
  durationSeconds?: number;
  sampleRate?: number;
  channels?: number;
  format?: string;
  sizeBytes?: number;
  mediaHash?: string;
}

/** Una fila de `audio_assets`, normalizada. Espeja `AssetOut`. */
export interface ProjectAsset {
  id: string;
  projectId: string;
  userId: string;
  kind: string;
  stemName: string | null;
  r2Key: string;
  mediaHash: string | null;
  originalFilename: string | null;
  durationSeconds: number | null;
  sampleRate: number | null;
  channels: number | null;
  format: string | null;
  sizeBytes: number | null;
  createdAt: string | null;
}

/** Respuesta de `GET /projects/{id}/assets/{asset_id}/download`, camelCase. */
export interface AssetDownload {
  projectId: string;
  assetId: string;
  r2Key: string;
  originalFilename: string | null;
  downloadUrl: string;
  expiresIn: number;
}

/** Forma cruda (snake_case) de un proyecto. */
interface RawProjectOut {
  id: string;
  user_id: string;
  name: string;
  bpm: number | null;
  musical_key: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Forma cruda (snake_case) de la respuesta de presign. */
interface RawPresignedAsset {
  asset_id: string;
  project_id: string;
  r2_key: string;
  put_url: string;
  content_type: string;
  expires_in: number;
}

/** Forma cruda (snake_case) de un asset. */
interface RawProjectAsset {
  id: string;
  project_id: string;
  user_id: string;
  kind: string;
  stem_name: string | null;
  r2_key: string;
  media_hash: string | null;
  original_filename: string | null;
  duration_seconds: number | null;
  sample_rate: number | null;
  channels: number | null;
  format: string | null;
  size_bytes: number | null;
  created_at: string | null;
}

/** Forma cruda (snake_case) de la respuesta de descarga. */
interface RawAssetDownload {
  project_id: string;
  asset_id: string;
  r2_key: string;
  original_filename: string | null;
  download_url: string;
  expires_in: number;
}

function toProjectOut(raw: RawProjectOut): ProjectOut {
  return {
    id: raw.id,
    userId: raw.user_id,
    name: raw.name,
    bpm: raw.bpm,
    musicalKey: raw.musical_key,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function toPresignedAsset(raw: RawPresignedAsset): PresignedAsset {
  return {
    assetId: raw.asset_id,
    projectId: raw.project_id,
    r2Key: raw.r2_key,
    putUrl: raw.put_url,
    contentType: raw.content_type,
    expiresIn: raw.expires_in,
  };
}

function toProjectAsset(raw: RawProjectAsset): ProjectAsset {
  return {
    id: raw.id,
    projectId: raw.project_id,
    userId: raw.user_id,
    kind: raw.kind,
    stemName: raw.stem_name,
    r2Key: raw.r2_key,
    mediaHash: raw.media_hash,
    originalFilename: raw.original_filename,
    durationSeconds: raw.duration_seconds,
    sampleRate: raw.sample_rate,
    channels: raw.channels,
    format: raw.format,
    sizeBytes: raw.size_bytes,
    createdAt: raw.created_at,
  };
}

function toAssetDownload(raw: RawAssetDownload): AssetDownload {
  return {
    projectId: raw.project_id,
    assetId: raw.asset_id,
    r2Key: raw.r2_key,
    originalFilename: raw.original_filename,
    downloadUrl: raw.download_url,
    expiresIn: raw.expires_in,
  };
}

/** Crea un proyecto del llamador. */
export async function createProject(
  name: string,
  opts?: { bpm?: number; musicalKey?: string }
): Promise<ProjectOut> {
  const body: Record<string, unknown> = { name };
  if (opts?.bpm !== undefined) body.bpm = opts.bpm;
  if (opts?.musicalKey !== undefined) body.musical_key = opts.musicalKey;
  const res = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError("No se pudo crear el proyecto", res.status);
  return toProjectOut(await res.json());
}

/** Lista los proyectos del llamador, más recientes primero. */
export async function listProjects(): Promise<ProjectOut[]> {
  const res = await fetch(`${API_BASE}/projects`, {
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new ApiError("No se pudieron listar los proyectos", res.status);
  const raw = (await res.json()) as RawProjectOut[];
  return raw.map(toProjectOut);
}

/** Registra el asset y devuelve la URL firmada de subida a R2. */
export async function presignAsset(
  projectId: string,
  input: PresignAssetInput
): Promise<PresignedAsset> {
  const body: Record<string, unknown> = { kind: input.kind };
  if (input.stemName !== undefined) body.stem_name = input.stemName;
  if (input.originalFilename !== undefined) {
    body.original_filename = input.originalFilename;
  }
  if (input.contentType !== undefined) body.content_type = input.contentType;
  const res = await fetch(`${API_BASE}/projects/${projectId}/assets/presign`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError("No se pudo firmar la subida del archivo", res.status);
  return toPresignedAsset(await res.json());
}

/** Registra los metadatos del asset después del PUT directo a R2. */
export async function completeAsset(
  projectId: string,
  assetId: string,
  input: AssetCompleteInput
): Promise<ProjectAsset> {
  const body: Record<string, unknown> = {};
  if (input.durationSeconds !== undefined) body.duration_seconds = input.durationSeconds;
  if (input.sampleRate !== undefined) body.sample_rate = input.sampleRate;
  if (input.channels !== undefined) body.channels = input.channels;
  if (input.format !== undefined) body.format = input.format;
  if (input.sizeBytes !== undefined) body.size_bytes = input.sizeBytes;
  if (input.mediaHash !== undefined) body.media_hash = input.mediaHash;
  const res = await fetch(`${API_BASE}/projects/${projectId}/assets/${assetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError("No se pudieron registrar los metadatos", res.status);
  return toProjectAsset(await res.json());
}

/** Lista los archivos de un proyecto (original, stems, masters). */
export async function listAssets(projectId: string): Promise<ProjectAsset[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/assets`, {
    headers: { ...(await authHeaders()) },
  });
  if (!res.ok) throw new ApiError("No se pudieron listar los archivos", res.status);
  const raw = (await res.json()) as RawProjectAsset[];
  return raw.map(toProjectAsset);
}

/** Pide una URL firmada de descarga para reproducir un asset desde la librería. */
export async function getAssetDownloadUrl(
  projectId: string,
  assetId: string
): Promise<AssetDownload> {
  const res = await fetch(
    `${API_BASE}/projects/${projectId}/assets/${assetId}/download`,
    { headers: { ...(await authHeaders()) } }
  );
  if (!res.ok) throw new ApiError("No se pudo obtener el enlace de descarga", res.status);
  return toAssetDownload(await res.json());
}

