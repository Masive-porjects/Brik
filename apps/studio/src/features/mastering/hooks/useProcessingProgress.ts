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
    setProgress(0);

    intervalRef.current = setInterval(async () => {
      if (!sessionId) return;
      if (pollingRef.current) return;
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
      }
    }, 500);
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
