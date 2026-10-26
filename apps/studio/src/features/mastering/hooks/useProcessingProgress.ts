"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getProcessingProgress, ApiError } from "@/lib/api";
import { progressPct } from "@/lib/audioUtils";

/** Por qué se cortó el sondeo. Cada motivo merece un mensaje distinto:
 *  una sesión perdida se arregla recargando, una falla del motor no. */
export type ProcessingFailureKind =
  | "session_lost"
  | "processing_failed"
  | "poll_failed";

export interface ProcessingFailure {
  kind: ProcessingFailureKind;
  /** Motivo reportado por el backend, si lo hay. */
  message: string | null;
}

interface UseProcessingProgressOptions {
  enabled: boolean;
  sessionId: string | null;
  onComplete?: () => void;
  onError?: (failure: ProcessingFailure) => void;
}

/** Fallas de red/HTTP consecutivas toleradas antes de darse por vencido.
 *  Una sola falla aislada (un 502 de gateway durante un reinicio) no debe
 *  cerrar el overlay: se reintenta y el siguiente tick se recupera. */
const MAX_CONSECUTIVE_FAILURES = 3;

/**
 * Hook para monitorear el progreso del procesamiento en segundo plano desde FastAPI.
 * Incluye temporizador de sondeo, watchdog contra bloqueos y control de expiración de sesión.
 *
 * El sondeo SIEMPRE termina: completa, sesión perdida (404), el motor reporta
 * `status: "error"`, o se agotan los reintentos. Nunca queda girando en 0%.
 */
export function useProcessingProgress({
  enabled,
  sessionId,
  onComplete,
  onError,
}: UseProcessingProgressOptions) {
  const [progress, setProgress] = useState(0);
  const progressRef = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef(false);
  const completedRef = useRef(false);
  const failuresRef = useRef(0);
  const pollIntervalRef = useRef(500); // Exponential backoff: starts at 500ms
  const MAX_POLL_INTERVAL = 10000; // Cap at 10s
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const clearTimers = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    pollIntervalRef.current = 500; // Reset backoff on clear
  }, []);

  const completeProgress = useCallback(() => {
    clearTimers();
    progressRef.current = 100;
    setProgress(100);
  }, [clearTimers]);

  const startProgress = useCallback(() => {
    clearTimers();
    progressRef.current = 0;
    completedRef.current = false;
    failuresRef.current = 0;
    pollIntervalRef.current = 500; // Reset backoff
    setProgress(0);

    /** Corta el sondeo y avisa por qué. Deja ``completedRef`` en true para
     *  que el ``finally`` no reprograme el tick: sin esto, el `return` no
     *  alcanzaba y el hook seguía sondeando después de cerrar el overlay. */
    const stopWithFailure = (
      kind: ProcessingFailureKind,
      message: string | null,
    ) => {
      completedRef.current = true;
      clearTimers();
      onErrorRef.current?.({ kind, message });
    };

    const tick = async () => {
      if (!sessionId || completedRef.current) return;
      if (pollingRef.current) {
        // Reschedule with current interval
        intervalRef.current = setTimeout(tick, pollIntervalRef.current);
        return;
      }
      pollingRef.current = true;
      try {
        const p = await getProcessingProgress(sessionId);
        failuresRef.current = 0;
        const pct = progressPct(p.progress * 100);
        progressRef.current = pct;
        setProgress(pct);

        // El motor falló: el backend ya cerró la corrida, no hay progreso que
        // esperar. Sin esta rama el overlay se quedaba clavado en el último
        // porcentaje (típicamente 0%) para siempre.
        if (p.status === "error") {
          stopWithFailure("processing_failed", p.error ?? null);
          return;
        }

        if (!completedRef.current && (p.status === "completed" || pct >= 100)) {
          completedRef.current = true;
          clearTimers();
          progressRef.current = 100;
          setProgress(100);
          closeTimerRef.current = setTimeout(() => {
            onCompleteRef.current?.();
          }, 1200);
          return;
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          stopWithFailure("session_lost", null);
          return;
        }
        failuresRef.current += 1;
        if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
          stopWithFailure(
            "poll_failed",
            err instanceof Error ? err.message : null,
          );
          return;
        }
      } finally {
        pollingRef.current = false;
        // Solo reprogramar si el sondeo sigue vivo. El `return` de arriba no
        // cancela el finally: sin esta guarda, cerrar el overlay no frenaba
        // el polling y `onError` volvía a dispararse cada 10s.
        if (!completedRef.current) {
          // Exponential backoff: increase interval up to max
          pollIntervalRef.current = Math.min(
            pollIntervalRef.current * 1.5,
            MAX_POLL_INTERVAL
          );
          // Schedule next tick
          intervalRef.current = setTimeout(tick, pollIntervalRef.current);
        }
      }
    };

    // Start first tick
    intervalRef.current = setTimeout(tick, pollIntervalRef.current);
  }, [sessionId, clearTimers]);

  const resetProgress = useCallback(() => {
    clearTimers();
    progressRef.current = 0;
    setProgress(0);
  }, [clearTimers]);

  useEffect(() => {
    const t = setTimeout(() => {
      if (enabled && sessionId) startProgress();
      else resetProgress();
    }, 0);
    return () => {
      clearTimeout(t);
      clearTimers();
    };
  }, [enabled, sessionId, startProgress, resetProgress, clearTimers]);

  return { progress, completeProgress };
}
