import { API_BASE } from "./config";

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

/** V1 Project Document structure. */
export interface ProjectDocumentV1 {
  schemaVersion: 1;
  stems: Record<string, {
    name: string;
    storagePath: string;
    confirmed: boolean;
  }>;
  pendingProposals: Array<{
    id: string;
    type: "fader" | "trim" | "balance" | "dimension" | "master_intent";
    payload: unknown;
    createdAt: string;
    status: "pending" | "accepted" | "rejected";
  }>;
  masterIntent: {
    presetId: "universal" | "streaming" | "club" | "cd" | "custom";
    platformTarget: "spotify" | "apple_music" | "youtube" | "tidal" | "club" | "cd" | "custom";
    format: "wav" | "mp3";
    outputBitDepth: 16 | 24 | 32;
    masterName?: string;
    parameters?: Record<string, number | boolean>;
  };
  updatedAt: string;
  updatedBy: "user" | "ai";
}

/** GET /projects/{id}/document response. */
export interface ProjectDocumentResponse {
  projectId: string;
  version: number;
  document: ProjectDocumentV1;
  updatedAt: string | null;
}

/** PUT /projects/{id}/document payload. */
export interface PutDocumentPayload {
  document: ProjectDocumentV1;
  expectedVersion: number;
}

/** Mix state payload for PATCH /projects/{id}/state. */
export interface MixStatePayload {
  state: {
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
  };
  undo_stack: Array<{
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
    timestamp: number;
  }>;
}

/** GET /projects/{id}/state response. */
export interface MixStateResponse {
  projectId: string;
  state: {
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
  };
  undo_stack: Array<{
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
    timestamp: number;
  }>;
  updatedAt: string | null;
}

/** Fetches the V1 project document (bootstrap if none). */
export async function getProjectDocument(
  projectId: string
): Promise<{
  projectId: string;
  version: number;
  document: ProjectDocumentV1;
  updatedAt: string | null;
}> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    headers: { ...licenseHeaders() },
  });
  if (!res.ok) throw new ApiError("Failed to fetch project document", res.status);
  return res.json();
}

/** Writes the V1 project document with OCC. */
export async function putProjectDocument(
  projectId: string,
  payload: { document: ProjectDocumentV1; expectedVersion: number }
): Promise<{
  projectId: string;
  version: number;
  document: ProjectDocumentV1;
  updatedAt: string | null;
}> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...licenseHeaders() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError("Failed to write project document", res.status);
  return res.json();
}

/** Deletes the project document (resets to bootstrap). */
export async function deleteProjectDocument(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    method: "DELETE",
    headers: { ...licenseHeaders() },
  });
  if (!res.ok) throw new ApiError("Failed to delete project document", res.status);
}

/** Fetches the live mix state. */
export async function getProjectMixState(
  projectId: string
): Promise<{
  projectId: string;
  state: { faders: Record<string, number>; toggles: Record<string, unknown> };
  undo_stack: Array<{
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
    timestamp: number;
  }>;
  updatedAt: string | null;
}> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/state`, {
    headers: { ...licenseHeaders() },
  });
  if (!res.ok) throw new ApiError("Failed to fetch mix state", res.status);
  return res.json();
}

/** Updates the live mix state (debounced by caller). */
export async function patchProjectMixState(
  projectId: string,
  payload: {
    state: { faders: Record<string, number>; toggles: Record<string, unknown> };
    undo_stack: Array<{
      faders: Record<string, number>;
      toggles: Record<string, unknown>;
      timestamp: number;
    }>;
  }
): Promise<{
  projectId: string;
  state: { faders: Record<string, number>; toggles: Record<string, unknown> };
  undo_stack: Array<{
    faders: Record<string, number>;
    toggles: Record<string, unknown>;
    timestamp: number;
  }>;
  updatedAt: string | null;
}> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/state`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...licenseHeaders() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError("Failed to update mix state", res.status);
  return res.json();
}

/** Submits a mix job for a project (returns job_id + poll_url). */
export async function submitProjectMixJob(
  projectId: string,
  signal?: AbortSignal
): Promise<{ job_id: string; poll_url: string }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/jobs/mix`, {
    method: "POST",
    headers: { ...licenseHeaders() },
    signal,
  });
  if (!res.ok) throw new ApiError("Failed to submit mix job", res.status);
  return res.json();
}

/** Submits a mastering job for a project (returns job_id + poll_url). */
export async function submitProjectMasterJob(
  projectId: string,
  signal?: AbortSignal
): Promise<{ job_id: string; poll_url: string }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/jobs/master`, {
    method: "POST",
    headers: { ...licenseHeaders() },
    signal,
  });
  if (!res.ok) throw new ApiError("Failed to submit mastering job", res.status);
  return res.json();
}

