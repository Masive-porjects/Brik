"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type MasterJobPayload,
  type AsyncJobStatus,
  type MasterJobResult,
  submitMasterJob,
  getMasterJobStatus,
  MasterJobResult,
} from "@/lib/api";
import { useTranslation } from "@/i18n/useTranslation";
import { useAuth } from "@/features/auth/hooks/useAuth";

/** Estados del ciclo de vida de un trabajo de mastering asíncrono. */
export type MasteringJobState =
  | "idle"
  | "submitting"
  | "processing"
  | "completed"
  | "error";

/** Resultado que el hook devuelve al componente consumidor. */
export interface UseMasteringJobResult {
  /** Estado actual del trabajo. */
  state: MasteringJobState;
  /** ID del trabajo (único por sesión). */
  jobId: string | null;
  /** Datos completos devueltos cuando el trabajo terminó. */
  result: MasterJobResult | null;
  /** Mensaje de error si el trabajo falló. */
  error: string | null;
  /** Progreso estimado 0-100 (solo informativo). */
  progress: number;
  /** ¿El trabajo terminó (completed o error)? */
  isTerminal: boolean;
  /** ¿El trabajo está completo y listo para consumir? */
  isComplete: boolean;
  /** Funcula para submeter un nuevo trabajo asíncrono. */
  submit: (payload: MasterJobPayload) => Promise<void>;
  /** Funcula para reiniciar/limpiar el trabajo actual. */
  reset: () => void;
  /** Callback invocado cuando el trabajo llega a estado terminal. */
  onComplete?: (result: MasterJobResult) => void;
  /** Callback invocado cuando el trabajo falla. */
  onError?: (error: string) => void;
}

/**
 * Hook para submeter y hacer polling de un mastering job asíncrono.
 *
 * Flujo:
 *  1. Llama submitMasterJob(payload { is_async: true }) → retorna { jobId, status: 'processing' }
 *  2. Inicia intervalo de polling a GET /api/jobs/master/{jobId} cada 2.5 s
 *  3. Actualiza el estado local según la respuesta del backend:
 *     - 'processing' → state = 'processing'
 *     - 'completed' → state = 'completed', invoca onComplete con el resultado
 *     - 'error' → state = 'error', invoca onError con el mensaje
 *     - Job no encontrado / stale lease → state = 'error'
 * 4. Detiene el polling al llegar a estado terminal.
 *
 * NOTAS:
 * - El hook es independiente de useMasteringWorkflow; no interfiere en el
 *   flujo sincrónico upload→analysis→processAudio. Se usa cuando el usuario
 *   quiere encolar el job en el background queue (Fase 6).
 * - El backend refresca el lease cada ~300 s (job_lease_seconds / 3). El hook
 *   puede opcionalmenteheartbeatear para evitar que el lease expire mientras
 *   el job permanece processing.
 * - Soporta tanto modo demo (sin Supabase) como producción (con tabla dsp_jobs).
 */
export function useMasteringJob(
  options: {
    /** Payload para submeter el job. Se ignora si ya hay un job activo. */
    payload: MasterJobPayload;
    /** Callback opcional al completar el trabajo. */
    onComplete?: (result: MasterJobResult) => void;
    /** Callback opcional al fallar el trabajo. */
    onError?: (error: string) => void;
  },
  deps?: unknown[],
) {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [state, setState] = useState<MasteringJobState>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<MasterJobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [isTerminal, setIsTerminal] = useState(false);
  const [isComplete, setIsComplete] = useState(false);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const submitPromiseRef = useRef<Promise<void> | null>(null);

  // Evitar submeter dos jobs simultáneos
  const isSubmittingRef = useRef(false);

  // Sync callbacks from options
  const onCompleteRef = useRef(options.onComplete);
  const onErrorRef = useRef(options.onError);
  onCompleteRef.current = options.onComplete;
  onErrorRef.current = options.onError;

  /** Submeter el job asíncrono. */
  const submit = useCallback(
    async (payload: MasterJobPayload) => {
      // Prevent concurrent submissions
      if (isSubmittingRef.current) {
        console.warn("[useMasteringJob] Ya hay un job en proceso de submisión.");
        return;
      }
      isSubmittingRef.current = true;
      setState("submitting");
      setJobId(null);
      setResult(null);
      setError(null);
      setProgress(0);
      setIsTerminal(false);
      setIsComplete(false);

      try {
        const response = await submitMasterJob(payload);
        // El response shape depends on implementation; accept both shapes:
        // { job_id, status, track_id, ... } or the full MasterJobResult
        const jobIdVal = response.job_id || response.id;
        const statusVal = response.status || "processing";

        if (jobIdVal) {
          setJobId(jobIdVal as string);
          setState("processing");
        } else {
          setState("error");
          setError(t("errors.masteringJobSubmit", "No se recibió job_id del servidor"));
          return;
        }

        // Iniciar polling interval
        startPolling();
      } catch (err: any) {
        console.error("[useMasteringJob] Error submitting master job:", err);
        setState("error");
        setError(
          err instanceof Error
            ? err.message
            : t("errors.masteringJobSubmit", "Error al submeter el job de mastering"),
        );
        isSubmittingRef.current = false;
      }
    },
    [t],
  );

  /** Iniciar el intervalo de polling. */
  const startPolling = useCallback(() => {
    // Clear any existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    setProgress(0);
    setError(null);
    isTerminalRef.current = false;
    isCompleteRef.current = false;

    intervalRef.current = setInterval(async () => {
      if (!jobId) {
        clearInterval(intervalRef.current!);
        intervalRef.current = null;
        setState("error");
        setError(t("errors.masteringJobNoId", "ID de job inexistente"));
        return;
      }

      try {
        const status: AsyncJobStatus = await getMasterJobStatus(jobId);

        // Actualizar progreso y estado según el response
        setProgress(status.progress ?? 0);

        switch (status.status) {
          case "processing":
            setState("processing");
            // Reset error if was previously errored and now running again
            setError(null);
            break;

          case "completed":
            clearInterval(intervalRef.current!);
            intervalRef.current = null;
            setState("completed");
            setIsTerminal(true);
            setIsComplete(true);
            setProgress(100);
            const resultData: MasterJobResult = status.result
              ? {
                  success: true,
                  job_id: status.job_id,
                  track_id: status.track_id,
                  master_id: status.result.master_id || status.job_id,
                  status: "completed",
                  storage_path: status.result.storage_path,
                  download_url: status.result.download_url,
                  file_size_bytes: status.result.file_size_bytes || 0,
                  format: status.result.format || "wav",
                  metrics: status.result.metrics
                    ? {
                        integrated_lufs: status.result.metrics.integrated_lufs,
                        true_peak_db: status.result.metrics.true_peak_db,
                        crest_factor_db: status.result.metrics.crest_factor_db,
                        limiter_ceiling_db: status.result.metrics.limiter_ceiling_db,
                        duration_seconds: status.result.metrics.duration_seconds,
                        sample_rate: status.result.metrics.sample_rate,
                        output_bit_depth: status.result.metrics.output_bit_depth,
                        stereo_correlation: status.result.metrics.stereo_correlation,
                        lra: status.result.metrics.lra,
                      }
                    : undefined,
                  validation: status.result.validation
                    ? {
                        status: status.result.validation.status,
                        issues: status.result.validation.issues,
                        retry_recommended: status.result.validation.retry_recommended,
                        suggested_preset_id: status.result.validation.suggested_preset_id,
                        note: status.result.validation.note,
                      }
                    : undefined,
                  error: null,
                }
              : MasterJobResult.success;
            setResult(resultData);
            setError(null);
            onCompleteRef.current?.(resultData);
            setIsComplete(true);
            break;

          case "error":
            clearInterval(intervalRef.current!);
            intervalRef.current = null;
            setState("error");
            setIsTerminal(true);
            const errMsg =
              status.error ||
              t("errors.masteringJobFailed", "El job de mastering falló");
            setError(errMsg);
            onErrorRef.current?.(errMsg);
            break;

          default:
            // Estado desconocido, continuar polling
            break;
        }
      } catch (pollErr: any) {
        console.error(
          `[useMasteringJob] Error polling job ${jobId}:`,
          pollErr,
        );
        // Si el job desaparece (404), tratar como error de lease expirado
        if (pollErr instanceof Error && pollErr.message.includes("404")) {
          clearInterval(intervalRef.current!);
          intervalRef.current = null;
          setState("error");
          setError(
            t(
              "errors.masteringJobStale",
              "El job expiró (el worker pudo detenerse). Recarga y sube el audio de nuevo.",
            ),
          );
        } else {
          setError(
            t("errors.masteringJobPoll", "Error al consultar el estado del job"),
          );
        }
      }
    }, 2500); // 2.5 segundos: balance entre responsividad y carga de API
  }, [jobId, t]);

  /** Detener polling y limpiar. */
  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  /** Reiniciar el hook (limpiar job actual y volver a idle). */
  const reset = useCallback(() => {
    stopPolling();
    setState("idle");
    setJobId(null);
    setResult(null);
    setError(null);
    setProgress(0);
    setIsTerminal(false);
    setIsComplete(false);
    isSubmittingRef.current = false;
  }, [stopPolling]);

  // Efecto: iniciar polling cuando el jobId cambia y ya estamos en processing
  useEffect(() => {
    if (state === "processing" && jobId && !intervalRef.current) {
      startPolling();
    }
    return () => {
      stopPolling();
    };
  }, [state, jobId, startPolling, stopPolling]);

  // Efecto: limpiar al desmontar
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  return {
    state,
    jobId,
    result,
    error,
    progress,
    isTerminal,
    isComplete,
    submit,
    reset,
    onComplete,
    onError,
  } as UseMasteringJobResult;
}

/** Hook listo para usar en el contexto de mastering. */
export { useMasteringJob };