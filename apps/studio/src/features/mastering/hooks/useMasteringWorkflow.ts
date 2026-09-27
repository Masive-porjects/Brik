"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type SessionData,
  type MasteringParameters,
  type MixStatus,
  DEFAULT_PARAMS,
  type VocalChainParams,
  uploadAudio,
  processAudio,
  downloadMastered,
  splitStems,
  processVocalChain,
  resetSession,
  getSession,
  ApiError,
} from "@/lib/api";
import { PLATFORM_DEFAULTS } from "@/components/DeliveryPanel";
import { type StemSplitterState, createDefaultStemState } from "@/components/StemSplitter";
import { genreToParams, getMixGate, hasCompletedMix } from "@/lib/audioUtils";
import { useProcessingProgress } from "./useProcessingProgress";
import { useTranslation } from "@/i18n/useTranslation";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  extractAudioMetadata,
  uploadOriginalAudio,
  createTrackRecord,
  updateTrackStatus,
  uploadMasterAudio,
  createMasterRecord,
  clearTrackDraft,
  getOriginalSignedUrl,
  logTrackEvent,
  type Track,
  type MasterRecord,
} from "@/features/tracks";
import { useAutosaveDraft, type AutosaveStatus } from "./useAutosaveDraft";


export const ANALYSIS_TIMEOUT_MS = 180_000;
export const PROCESS_TIMEOUT_MS = 600_000;


export async function waitForAnalysis(
  sessionId: string,
  timeoutMs: number,
): Promise<SessionData | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const s = await getSession(sessionId);
      if (s.analysis) return s;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

interface UseMasteringWorkflowOptions {
  onSessionLoaded?: (s: SessionData) => void;
}

export function useMasteringWorkflow(
  optionsOrCallback?: UseMasteringWorkflowOptions | ((s: SessionData) => void),
) {
  const onSessionLoaded =
    typeof optionsOrCallback === "function"
      ? optionsOrCallback
      : optionsOrCallback?.onSessionLoaded;

  const { t } = useTranslation();
  const { user } = useAuth();

  const [session, setSession] = useState<SessionData | null>(null);
  const [currentTrack, setCurrentTrack] = useState<Track | null>(null);
  const [isUploadingToCloud, setIsUploadingToCloud] = useState(false);
  const currentTrackIdRef = useRef<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadBurst, setUploadBurst] = useState(0);
  const [masterBurst, setMasterBurst] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorModal, setErrorModal] = useState<{ title: string; message: string } | null>(null);
  const [overMasterWarning, setOverMasterWarning] = useState<{
    open: boolean;
    confidence: number;
    analyzedSession: SessionData;
    mappedParams: MasteringParameters;
  } | null>(null);

  const [params, setParams] = useState<MasteringParameters>(DEFAULT_PARAMS);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);

  // Non-destructive realtime autosave for drafts
  const { autosaveStatus, forceSave } = useAutosaveDraft({
    trackId: currentTrack?.id ?? null,
    params,
    activePresetId,
    enabled: !!user && !!currentTrack,
  });

  // Stem splitter state

  const [stemState, setStemState] = useState<StemSplitterState>(createDefaultStemState());

  // Vocal chain state
  const [vocalProcessing, setVocalProcessing] = useState(false);
  const [vocalProcessed, setVocalProcessed] = useState(false);

  // Abort controller for in-flight processing requests
  const abortRef = useRef<AbortController | null>(null);
  const presetCacheRef = useRef<Map<string, SessionData>>(new Map());

  /* ── Mix state (T2/T3) ───────────────────────────────
     ``hasMix`` is DERIVED from the backend-owned ``session.mix_status``,
     never from a local mix blob: the master tab and the mix tab read the
     same boolean, and the next tasks (mix/original toggle, gating the
     download) can branch on it. */
  const hasMix = hasCompletedMix(session);

  /** Re-read the session so the client sees the backend mix lifecycle
   *  (``mix_status``) that POST /mix just published. Called by the mix tab
   *  when a run settles — the mix response itself is a WAV blob + header,
   *  never the session state. */
  const handleMixSettled = useCallback(async () => {
    const current = session;
    if (!current) return;
    try {
      setSession(await getSession(current.session_id));
    } catch {
      // Backend best-effort: a lost refresh only means the tab keeps
      // rendering the mix it already has; the next poll corrects it.
    }
  }, [session]);

  /* ── Mix gate (T4) ───────────────────────────────────────
     Gate NO-bloqueante hacia el master: nunca mezcló (`none`) o la
     mezcla se entregó (`completed`) → el master está libre. Si el
     usuario inició una mezcla y no hay audio mezclado entregado
     (`processing` / `failed`) → el master NO arranca: se muestra el
     aviso y el CTA lleva al tab de mezcla. El veredicto viene de
     `getMixGate` (función pura, testeada en audioUtils.test.ts), nunca
     de un flag local de la UI. */
  const mixGate = getMixGate(session);
  const mixStatus: MixStatus = mixGate.mixStatus;
  const isMixGateBlocked: boolean = mixGate.blocked;

  /* Último intento de master con el gate bloqueado. Se guarda la sesión y
     el estado para que el aviso solo se "acredite" mientras sigue vigente:
     al cambiar de estado (o de sesión) el énfasis se limpia solo, sin
     efectos. */
  const [mixGateAttempt, setMixGateAttempt] = useState<{
    sessionId: string;
    status: MixStatus;
  } | null>(null);
  const mixGateAttempted =
    isMixGateBlocked &&
    mixGateAttempt?.sessionId === session?.session_id &&
    mixGateAttempt?.status === mixStatus;

  /** Aviso i18n del bloqueo (null = master libre). */
  const mixGateNotice: string | null = !isMixGateBlocked
    ? null
    : mixStatus === "processing"
      ? t("mezcla.gateProcessingNotice", "Termina tu mezcla antes de masterizar.")
      : t(
          "mezcla.gateFailedNotice",
          "Tu mezcla falló. Reintenta la mezcla para continuar al master.",
        );

  /** CTA del aviso: en ambos casos lleva al tab de mezcla; cambia el verbo
   *  porque `failed` es una mezcla entregable que hay que reintentar. */
  const mixGateCtaLabel: string | null = !isMixGateBlocked
    ? null
    : mixStatus === "processing"
      ? t("mezcla.gateProcessingCta", "Ir a la mezcla")
      : t("mezcla.gateFailedCta", "Reintentar la mezcla");

  /** Guarda el intento bloqueado. Se usa como guarda al inicio de todo
   *  trigger que masteriza (procesar con parámetros y aplicar preset). */
  const blockMasterRun = useCallback(() => {
    if (!session) return;
    setMixGateAttempt({ sessionId: session.session_id, status: mixStatus });
  }, [session, mixStatus]);

  // Real progress polled from the backend for the ProcessingOverlay
  const { progress, completeProgress } = useProcessingProgress({
    enabled: processing,
    sessionId: session?.session_id ?? null,
    onComplete: () => setProcessing(false),
    onError: () => {
      setProcessing(false);
      setErrorModal({
        title: t("errors.serverRestartTitle", "El servidor se reinició"),
        message: t(
          "errors.serverRestartMessage",
          "La sesión se perdió mientras se procesaba. Recarga la página: si la sesión no se recupera sola, sube el audio de nuevo.",
        ),
      });
    },
  });

  // Burst on master landed
  const wasProcessingRef = useRef(false);
  useEffect(() => {
    if (wasProcessingRef.current && !processing && session?.mastered_path) {
      setMasterBurst((n) => n + 1);
    }
    wasProcessingRef.current = processing;
  }, [processing, session?.mastered_path]);

  // Persist session association across page reloads
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (session?.session_id) {
      const trackId = currentTrack?.id || currentTrackIdRef.current;
      if (trackId) {
        sessionStorage.setItem(`waveai-track-session-${trackId}`, session.session_id);
        localStorage.setItem(`waveai-track-session-${trackId}`, session.session_id);
      }
      sessionStorage.setItem("waveai-active-session", session.session_id);
      if (!user) {
        localStorage.setItem("waveai-session", session.session_id);
      }
    }
  }, [session?.session_id, currentTrack?.id, user]);

  // Restore saved session on mount for guest users or fallback active session
  useEffect(() => {
    if (typeof window === "undefined" || session) return;
    if (user) return; // Authenticated users restore via handleLoadTrackProject

    const savedId = localStorage.getItem("waveai-session") || sessionStorage.getItem("waveai-active-session");
    if (!savedId) return;
    getSession(savedId)
      .then((s) => {
        setSession(s);
        onSessionLoaded?.(s);
      })
      .catch(() => {
        localStorage.removeItem("waveai-session");
        sessionStorage.removeItem("waveai-active-session");
      });
  }, [onSessionLoaded, session, user]);

  /* ── Upload Handler ────────────────────────────────── */
  const handleFileSelected = useCallback(
    async (file: File) => {
      abortRef.current?.abort();
      abortRef.current = null;

      setLoading(true);
      setUploadProgress(0);
      setError(null);

      // 1. Initiate Supabase Storage upload & track record in parallel (non-blocking for audio engine)
      const cloudUploadPromise = (async () => {
        if (!user) {
          currentTrackIdRef.current = null;
          setCurrentTrack(null);
          return null;
        }
        setIsUploadingToCloud(true);
        try {
          const trackId = crypto.randomUUID();
          currentTrackIdRef.current = trackId;
          const meta = await extractAudioMetadata(file);
          const { storagePath } = await uploadOriginalAudio(user.id, file, trackId);
          const savedTrack = await createTrackRecord(user.id, {
            id: trackId,
            title: file.name.replace(/\.[^/.]+$/, ""),
            original_filename: file.name,
            storage_path: storagePath,
            file_size_bytes: file.size,
            duration_seconds: meta.duration || null,
            sample_rate: meta.sampleRate || null,
            channels: meta.channels || null,
            format: meta.format || null,
            status: "analyzing",
          });
          setCurrentTrack(savedTrack);
          // Log audit event
          logTrackEvent(user.id, trackId, "uploaded", {
            filename: file.name,
            size_bytes: file.size,
            duration: meta.duration,
          });
          return savedTrack;
        } catch (storageErr) {
          console.error("Cloud storage upload error:", storageErr);
          return null;
        } finally {
          setIsUploadingToCloud(false);
        }
      })();

      // 2. Upload to AudioMind engine & process
      try {
        const result = await uploadAudio(file, setUploadProgress);
        setUploadBurst((n) => n + 1);
        if (currentTrackIdRef.current && typeof window !== "undefined") {
          sessionStorage.setItem(`waveai-track-session-${currentTrackIdRef.current}`, result.session_id);
          localStorage.setItem(`waveai-track-session-${currentTrackIdRef.current}`, result.session_id);
        }
        setSession(result);
        onSessionLoaded?.(result);
        presetCacheRef.current.clear();

        // Audio uploaded to engine successfully: transition from upload to processing phase
        setLoading(false);
        setProcessing(true);

        // Await cloud storage completion in background
        await cloudUploadPromise;

        await new Promise((r) => setTimeout(r, 400));

        const analyzed = await waitForAnalysis(result.session_id, ANALYSIS_TIMEOUT_MS);
        if (!analyzed?.analysis) {
          setProcessing(false);
          if (currentTrackIdRef.current) {
            updateTrackStatus(currentTrackIdRef.current, "error").catch(() => {});
          }
          const timeoutMsg = t(
            "errors.analysisTimeout",
            "El análisis del audio tardó demasiado. Reintentá subiendo el track de nuevo.",
          );
          setError(timeoutMsg);
          setErrorModal({
            title: t("common.error", "Error"),
            message: timeoutMsg,
          });
          return;
        }
        setSession(analyzed);

        if (currentTrackIdRef.current) {
          updateTrackStatus(currentTrackIdRef.current, "ready").catch(() => {});
          if (user) {
            logTrackEvent(user.id, currentTrackIdRef.current, "analyzed", {
              detected_genre: analyzed.analysis.detected_genre,
              confidence: analyzed.analysis.mastering_confidence,
              is_already_mastered: analyzed.analysis.is_already_mastered,
            });
          }
        }

        const genre = analyzed.analysis.detected_genre ?? null;
        const mapped = genreToParams(genre);

        if (analyzed.analysis.is_already_mastered) {
          setProcessing(false);
          setOverMasterWarning({
            open: true,
            confidence: analyzed.analysis.mastering_confidence ?? 0.8,
            analyzedSession: analyzed,
            mappedParams: mapped,
          });
          return;
        }

        setParams(mapped);
        completeProgress();
        setProcessing(false);
        if (currentTrackIdRef.current) {
          updateTrackStatus(currentTrackIdRef.current, "ready").catch(() => {});
        }
        onSessionLoaded?.(analyzed);
      } catch (err) {
        if (currentTrackIdRef.current) {
          updateTrackStatus(currentTrackIdRef.current, "error").catch(() => {});
        }
        let errMsg = t("errors.uploadFailed", "Upload failed");
        if (err instanceof ApiError && err.status === 413) {
          if (err.message.includes("AUDIO_TOO_LONG")) {
            errMsg = t(
              "errors.audioTooLong",
              "El audio es demasiado largo. El límite para masterizar es de 10 minutos por track.",
            );
          } else {
            errMsg = t(
              "errors.fileTooLarge",
              "El archivo es demasiado grande (máximo 50MB). Probá comprimirlo o exportar en WAV 16-bit / MP3 320kbps.",
            );
          }
        } else if (err instanceof Error) {
          errMsg = err.message;
        }
        setError(errMsg);
        setErrorModal({
          title: t("common.error", "Error"),
          message: errMsg,
        });
      } finally {
        setLoading(false);
        setProcessing(false);
      }

    },
    [completeProgress, onSessionLoaded, t, user],
  );



  /* ── Reprocess ─────────────────────────────────────── */
  const handleProcess = useCallback(async () => {
    if (!session) return;

    // Gate de mezcla (T4): con una mezcla iniciada y NO entregada no se
    // masteriza. Se registra el intento (el aviso se acredita) y se
    // retorna SIN llamar a processAudio: ni source=mix (400 del backend)
    // ni un master silencioso del original por detrás de la pantalla.
    if (isMixGateBlocked) {
      blockMasterRun();
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setProcessing(true);
    setError(null);
    if (currentTrackIdRef.current) {
      updateTrackStatus(currentTrackIdRef.current, "mastering").catch(() => {});
    }
    const watchdog = setTimeout(() => controller.abort(), PROCESS_TIMEOUT_MS);

    try {
      // Explicit source (T2/T3): a delivered mix IS the input to master.
      // Sending it instead of relying on the backend's smart default makes
      // the client's intent auditable in the request and keeps the neutral
      // parameters bit-exact against the SELECTED file (bypass unchanged).
      // The preset path (handlePresetSelect) keeps the smart default, which
      // resolves to the same file.
      const result = await processAudio(
        session.session_id,
        params,
        controller.signal,
        activePresetId ?? undefined,
        hasMix ? "mix" : "original",
      );
      completeProgress();
      await new Promise((r) => setTimeout(r, 600));
      setSession(result);
      if (currentTrackIdRef.current) {
        updateTrackStatus(currentTrackIdRef.current, "completed").catch(() => {});
        if (user) {
          logTrackEvent(user.id, currentTrackIdRef.current, "reprocessed", {
            params,
            preset_id: activePresetId,
          });
        }
      }
    } catch (err) {
      if (currentTrackIdRef.current) {
        updateTrackStatus(currentTrackIdRef.current, "error").catch(() => {});
      }
      if (err instanceof DOMException && err.name === "AbortError") {
        setError(
          t(
            "errors.processTimeout",
            "El procesamiento tardó demasiado y se canceló. Prueba de nuevo.",
          ),
        );
        return;
      }
      setError(err instanceof Error ? err.message : t("common.error", "Processing failed"));
    } finally {
      clearTimeout(watchdog);
      setProcessing(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [session, params, activePresetId, completeProgress, t, hasMix, isMixGateBlocked, blockMasterRun]);


  /* ── Preset Select ─────────────────────────────────── */
  const handlePresetSelect = useCallback(
    async (presetParams: MasteringParameters, presetId?: string) => {
      if (!session) return;

      // Mismo gate (T4) que `handleProcess`: aplicar un preset TAMBIÉN es una
      // corrida de master. Sin audio mezclado entregado, el backend resolvería
      // el original por su cuenta — el usuario masterizaría en silencio lo
      // equivocado mientras su mezcla sigue viva.
      if (isMixGateBlocked) {
        blockMasterRun();
        return;
      }

      const platform = params.platform_target;
      const platformDelivery =
        platform && platform !== "custom" ? PLATFORM_DEFAULTS[platform] : undefined;

      const merged: MasteringParameters = {
        ...presetParams,
        processing_mode: params.processing_mode,
        output_sr: params.output_sr,
        strict_mode: params.strict_mode,
        ...(platform !== undefined ? { platform_target: platform } : {}),
        ...(platformDelivery
          ? {
              target_lufs_db: platformDelivery.lufs,
              limiter_ceiling_db: platformDelivery.ceiling,
            }
          : {}),
      };

      setParams(merged);
      setActivePresetId(presetId ?? null);
      setError(null);

      const cached =
        presetId && params.processing_mode !== "transparent"
          ? presetCacheRef.current.get(presetId)
          : undefined;
      if (cached) {
        abortRef.current?.abort();
        abortRef.current = null;
        setSession(cached);
        return;
      }

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setProcessing(true);
      const watchdog = setTimeout(() => controller.abort(), PROCESS_TIMEOUT_MS);

      try {
        const result = await processAudio(
          session.session_id,
          merged,
          controller.signal,
          presetId,
        );
        completeProgress();
        if (presetId && params.processing_mode !== "transparent") {
          presetCacheRef.current.set(presetId, result);
        }
        await new Promise((r) => setTimeout(r, 600));
        setSession(result);
        if (user && currentTrackIdRef.current) {
          logTrackEvent(user.id, currentTrackIdRef.current, "preset_applied", {
            preset_id: presetId,
            params: merged,
          });
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setError(
            t(
              "errors.processTimeoutPreset",
              "El procesamiento del preset tardó demasiado y se canceló.",
            ),
          );
          return;
        }
        setError(err instanceof Error ? err.message : t("common.error", "Processing failed"));
      } finally {
        clearTimeout(watchdog);
        setProcessing(false);
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [session, params, completeProgress, t, isMixGateBlocked, blockMasterRun],
  );

  /* ── Reset to Original ─────────────────────────────── */
  const handleReset = useCallback(async () => {
    if (!session) return;
    try {
      const reset = await resetSession(session.session_id);
      // The reset response is the backend truth for the mix lifecycle
      // (mix_status goes back to "none"), so `hasMix` must follow it —
      // otherwise a later run would ask for source=mix and get a 400.
      // Only the mix field is adopted: the local session keeps its master
      // pointers until the next process replaces them (unchanged behavior).
      setSession((prev) =>
        prev ? { ...prev, mix_status: reset.mix_status ?? "none" } : prev,
      );
    } catch {
      // Backend best-effort
    }
    setParams(DEFAULT_PARAMS);
    setActivePresetId(null);
  }, [session]);

  /* ── Reset Workflow / Back to Upload ───────────────── */
  const handleBackToUpload = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (typeof window !== "undefined") {
      localStorage.removeItem("waveai-session");
      sessionStorage.removeItem("waveai-active-session");
    }
    setSession(null);
    setCurrentTrack(null);
    currentTrackIdRef.current = null;
    setProcessing(false);
    setError(null);
    setOverMasterWarning(null);
    setParams(DEFAULT_PARAMS);
    setStemState(createDefaultStemState());
    presetCacheRef.current.clear();
  }, []);


  /* ── Stem split ────────────────────────────────────── */
  const handleStemSplit = useCallback(async () => {
    if (!session) throw new Error("No session");
    return await splitStems(session.session_id);
  }, [session]);

  /* ── Vocal process ──────────────────────────────────── */
  const handleVocalProcess = useCallback(
    async (vocalParams: VocalChainParams) => {
      if (!session) return;
      setVocalProcessing(true);
      setError(null);
      try {
        await processVocalChain(session.session_id, vocalParams);
        setVocalProcessed(true);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Vocal processing failed";
        setError(msg);
      } finally {
        setVocalProcessing(false);
      }
    },
    [session],
  );

  /* ── Download ──────────────────────────────────────── */
  const handleDownload = useCallback(
    async (format: "wav" | "mp3") => {
      if (!session) return;
      try {
        const blob = await downloadMastered(
          session.session_id,
          format,
          activePresetId ?? undefined,
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const stem = session.original_path?.split("/").pop()?.replace(/\.[^/.]+$/, "") ?? "master";
        const suffix = activePresetId ? `_${activePresetId}` : "_master";
        a.download = `${stem}${suffix}.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        // Background consolidation into Supabase Masters if authenticated
        if (user && currentTrack) {
          logTrackEvent(user.id, currentTrack.id, "master_downloaded", { format });
          uploadMasterAudio(user.id, currentTrack.id, blob, format)
            .then(({ storagePath }) => {
              logTrackEvent(user.id, currentTrack.id, "master_consolidated", {
                format,
                storage_path: storagePath,
                preset_name: activePresetId ?? null,
              });
              return createMasterRecord(user.id, {
                track_id: currentTrack.id,
                storage_path: storagePath,
                format,
                file_size_bytes: blob.size,
                preset_name: activePresetId ?? null,
                parameters_applied: params,
              });
            })
            .then(() => {
              updateTrackStatus(currentTrack.id, "completed").catch(() => {});
            })
            .catch((storageErr) => {
              console.warn("Background master cloud save notice:", storageErr);
            });
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Download failed");
      }
    },
    [session, activePresetId, user, currentTrack, params],
  );

  /* ── Master Consolidation (Explicit) ────────────────── */
  const [isConsolidating, setIsConsolidating] = useState(false);

  const handleConsolidateMaster = useCallback(
    async (options?: { name?: string; format?: "wav" | "mp3" }): Promise<MasterRecord | null> => {
      if (!session || !user || !currentTrack) return null;
      const format = options?.format ?? "wav";
      const masterName = options?.name?.trim() || `${currentTrack.title} - Master`;
      setIsConsolidating(true);
      setError(null);
      try {
        const blob = await downloadMastered(
          session.session_id,
          format,
          activePresetId ?? undefined,
        );

        const { storagePath } = await uploadMasterAudio(
          user.id,
          currentTrack.id,
          blob,
          format,
        );

        const masterRecord = await createMasterRecord(user.id, {
          track_id: currentTrack.id,
          name: masterName,
          storage_path: storagePath,
          format,
          file_size_bytes: blob.size,
          preset_name: activePresetId ?? null,
          parameters_applied: params,
        });

        await clearTrackDraft(currentTrack.id, true);
        setCurrentTrack((prev) =>
          prev ? { ...prev, draft_parameters: null, status: "completed" } : null
        );

        logTrackEvent(user.id, currentTrack.id, "master_consolidated", {
          name: masterName,
          format,
          preset_name: activePresetId ?? null,
          storage_path: storagePath,
          size_bytes: blob.size,
        });

        // Trigger local browser download as well
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const stem = masterName.replace(/[^a-zA-Z0-9_\-\s]/g, "").trim().replace(/\s+/g, "_");
        a.download = `${stem}.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        return masterRecord;
      } catch (err) {
        const rawMsg = err instanceof Error ? err.message : "Error al consolidar master";
        console.error("[Mastering Consolidation Error]", rawMsg);
        let userMsg = t(
          "mastering.consolidateError",
          "No se pudo guardar la mezcla en la nube de Supabase. Revisa tu conexión o intenta nuevamente."
        );
        if (rawMsg.toLowerCase().includes("row-level security") || rawMsg.toLowerCase().includes("rls")) {
          userMsg = t(
            "mastering.storagePermissionError",
            "Permiso de almacenamiento restringido en Supabase. Se recomienda revisar las políticas RLS del bucket."
          );
        }
        setError(userMsg);
        throw new Error(userMsg);
      } finally {
        setIsConsolidating(false);
      }
    },
    [session, user, currentTrack, activePresetId, params, t],
  );

  /* ── Load Track from Library / History ─────────────── */
  const [isLoadingTrackProject, setIsLoadingTrackProject] = useState(false);

  const handleLoadTrackProject = useCallback(
    async (track: Track) => {
      abortRef.current?.abort();
      abortRef.current = null;
      setLoading(true);
      setIsLoadingTrackProject(true);
      setError(null);

      try {
        currentTrackIdRef.current = track.id;
        setCurrentTrack(track);

        // 1. Restore draft parameters or active preset
        const hasCustomDraft = Boolean(
          track.draft_parameters && Object.keys(track.draft_parameters).length > 0
        );
        const restoredParams: MasteringParameters = hasCustomDraft
          ? ({ ...DEFAULT_PARAMS, ...track.draft_parameters } as MasteringParameters)
          : DEFAULT_PARAMS;
        setParams(restoredParams);
        setActivePresetId(track.active_preset ?? null);

        // Check if an existing session in AudioMind is still alive and ready (prevents redundant DSP on reload)
        const cachedSessionId =
          typeof window !== "undefined"
            ? sessionStorage.getItem(`waveai-track-session-${track.id}`) ||
              localStorage.getItem(`waveai-track-session-${track.id}`)
            : null;

        if (cachedSessionId) {
          try {
            const existing = await getSession(cachedSessionId);
            if (existing && existing.status === "completed" && existing.mastered_path) {
              setSession(existing);
              onSessionLoaded?.(existing);
              setLoading(false);
              setIsLoadingTrackProject(false);
              return;
            } else if (existing && existing.analysis) {
              setSession(existing);
              const targetParams: MasteringParameters = hasCustomDraft
                ? restoredParams
                : (existing.analysis?.detected_genre ? genreToParams(existing.analysis.detected_genre) : DEFAULT_PARAMS);
              setParams(targetParams);
              setLoading(false);
              setProcessing(true);

              const controller = new AbortController();
              abortRef.current = controller;
              const processed = await processAudio(
                existing.session_id,
                targetParams,
                controller.signal,
                track.active_preset ?? undefined,
              );
              completeProgress();
              setSession(processed);
              onSessionLoaded?.(processed);
              setIsLoadingTrackProject(false);
              return;
            }
          } catch (cachedErr) {
            console.warn("[Project Restore] Cached audio engine session expired or unavailable:", cachedErr);
            if (typeof window !== "undefined") {
              sessionStorage.removeItem(`waveai-track-session-${track.id}`);
              localStorage.removeItem(`waveai-track-session-${track.id}`);
            }
          }
        }

        // 2. Get signed URL for original audio from Supabase
        const signedUrl = await getOriginalSignedUrl(track.storage_path);
        const res = await fetch(signedUrl);
        if (!res.ok) throw new Error("No se pudo descargar el audio original del proyecto.");
        const blob = await res.blob();
        const file = new File([blob], track.original_filename || `${track.title}.wav`, {
          type: blob.type || "audio/wav",
        });

        // 3. Upload to AudioMind engine
        const sessionResult = await uploadAudio(file, setUploadProgress);
        if (typeof window !== "undefined") {
          sessionStorage.setItem(`waveai-track-session-${track.id}`, sessionResult.session_id);
          localStorage.setItem(`waveai-track-session-${track.id}`, sessionResult.session_id);
        }
        setSession(sessionResult);
        onSessionLoaded?.(sessionResult);

        setLoading(false);
        setProcessing(true);

        const analyzed = await waitForAnalysis(sessionResult.session_id, ANALYSIS_TIMEOUT_MS);
        if (!analyzed?.analysis) {
          throw new Error("El análisis del audio tardó demasiado al restaurar el proyecto.");
        }
        setSession(analyzed);

// 4. Decide: auto-resume ONLY a master interrupted mid-flight; never
        //    auto-master on open. Opening a track restores its draft params
        //    (or neutral defaults) and keeps the original as the preview
        //    source until the user explicitly masters.
        if (track.status === "mastering") {
          const targetParams: MasteringParameters = track.draft_parameters
            ? ({ ...DEFAULT_PARAMS, ...track.draft_parameters } as MasteringParameters)
            : genreToParams(analyzed.analysis.detected_genre ?? null);
          setParams(targetParams);

          const controller = new AbortController();
          abortRef.current = controller;
          const watchdog = setTimeout(() => controller.abort(), PROCESS_TIMEOUT_MS);
          try {
            const processed = await processAudio(
              analyzed.session_id,
              targetParams,
              controller.signal,
              track.active_preset ?? undefined,
            );
            completeProgress();
            setSession(processed);
            onSessionLoaded?.(processed);
            await updateTrackStatus(track.id, "completed");
            if (user) {
              logTrackEvent(user.id, track.id, "reprocessed", {
                params: targetParams,
                preset_id: track.active_preset ?? null,
                resumed: true,
              });
            }
          } catch (err) {
            if (err instanceof DOMException && err.name === "AbortError") {
              throw new Error(
                t(
                  "errors.processTimeout",
                  "El procesamiento tardó demasiado y se canceló. Prueba de nuevo.",
                ),
              );
            }
            throw err;
          } finally {
            clearTimeout(watchdog);
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Error al cargar proyecto";
        setError(msg);
        setErrorModal({
          title: t("common.error", "Error"),
          message: msg,
        });
      } finally {
        setLoading(false);
        setProcessing(false);
        setIsLoadingTrackProject(false);
      }
    },
    [completeProgress, onSessionLoaded, t, user],
  );

  /* ── Over-master confirmations ─────────────────────── */
  const handleOverMasterConfirm = useCallback(async () => {
    if (!overMasterWarning) return;
    const { analyzedSession, mappedParams } = overMasterWarning;
    setOverMasterWarning(null);

    setProcessing(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const watchdog = setTimeout(() => controller.abort(), PROCESS_TIMEOUT_MS);

    try {
      const processed = await processAudio(
        analyzedSession.session_id,
        mappedParams,
        controller.signal,
      );
      completeProgress();
      await new Promise((r) => setTimeout(r, 300));
      setSession(processed);
      onSessionLoaded?.(processed);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError(
          t(
            "errors.processTimeoutRetry",
            'El procesamiento tardó demasiado y se canceló. Apretá "Procesar con estos parámetros" para reintentar.',
          ),
        );
        return;
      }
      setError(err instanceof Error ? err.message : "Processing failed");
    } finally {
      clearTimeout(watchdog);
      setProcessing(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [overMasterWarning, completeProgress, onSessionLoaded, t]);

  const handleOverMasterCancel = useCallback(() => {
    setOverMasterWarning(null);
  }, []);

  return {
    session,
    setSession,
    hasMix,
    handleMixSettled,
    /* ── Mix gate (T4) ── */
    mixStatus,
    isMixGateBlocked,
    mixGateAttempted,
    mixGateNotice,
    mixGateCtaLabel,
    currentTrack,
    setCurrentTrack,
    isUploadingToCloud,
    loading,
    uploadProgress,
    uploadBurst,
    masterBurst,
    processing,
    progress,
    error,
    setError,
    errorModal,
    setErrorModal,
    overMasterWarning,
    params,
    setParams,
    activePresetId,
    setActivePresetId,
    autosaveStatus,
    forceSave,
    stemState,
    setStemState,
    vocalProcessing,
    vocalProcessed,
    isConsolidating,
    isLoadingTrackProject,
    handleFileSelected,
    handleProcess,
    handlePresetSelect,
    handleReset,
    handleBackToUpload,
    handleStemSplit,
    handleVocalProcess,
    handleDownload,
    handleConsolidateMaster,
    handleLoadTrackProject,
    handleOverMasterConfirm,
    handleOverMasterCancel,
  };
}

