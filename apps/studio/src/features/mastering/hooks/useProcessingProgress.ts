"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getProcessingProgress, ApiError } from "@/lib/api";
import { progressPct } from "@/lib/audioUtils";

interface UseProcessingProgressOptions {
  enabled: boolean;
  sessionId: string | null;
  onComplete?: () => void;
  onError?: () => void;
}

/**
 * Hook para monitorear el progreso del procesamiento en segundo plano desde FastAPI.
 * Incluye temporizador de sondeo, watchdog contra bloqueos y control de expiración de sesión.
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
    pollIntervalRef.current = 500; // Reset backoff
    setProgress(0);

    const tick = async () => {
      if (!sessionId) return;
      if (pollingRef.current) {
        // Reschedule with current interval
        intervalRef.current = setTimeout(tick, pollIntervalRef.current);
        return;
      }
      pollingRef.current = true;
      try {
        const p = await getProcessingProgress(sessionId);
        const pct = progressPct(p.progress * 100);
        progressRef.current = pct;
        setProgress(pct);

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
          completedRef.current = true;
          clearTimers();
          onErrorRef.current?.();
          return;
        }
      } finally {
        pollingRef.current = false;
        // Exponential backoff: increase interval up to max
        pollIntervalRef.current = Math.min(
          pollIntervalRef.current * 1.5,
          MAX_POLL_INTERVAL
        );
        // Schedule next tick
        intervalRef.current = setTimeout(tick, pollIntervalRef.current);
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
