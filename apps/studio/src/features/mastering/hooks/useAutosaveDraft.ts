"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { saveTrackDraft } from "@/features/tracks";
import type { MasteringParameters } from "@/lib/api";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error";

interface UseAutosaveDraftProps {
  trackId: string | null;
  params: MasteringParameters;
  activePresetId: string | null;
  enabled?: boolean;
  debounceMs?: number;
}

export function useAutosaveDraft({
  trackId,
  params,
  activePresetId,
  enabled = true,
  debounceMs = 800,
}: UseAutosaveDraftProps) {
  const [autosaveStatus, setAutosaveStatus] = useState<AutosaveStatus>("idle");
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);

  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const idleTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastSerializedRef = useRef<string>("");

  const forceSave = useCallback(async () => {
    if (!trackId || !enabled) return;
    try {
      setAutosaveStatus("saving");
      await saveTrackDraft(trackId, params, activePresetId);
      lastSerializedRef.current = JSON.stringify({ params, activePresetId });
      setAutosaveStatus("saved");
      setLastSavedAt(new Date());

      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      idleTimerRef.current = setTimeout(() => {
        setAutosaveStatus("idle");
      }, 2500);
    } catch {
      setAutosaveStatus("error");
    }
  }, [trackId, enabled, params, activePresetId]);

  const currentTrackIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!trackId || !enabled) {
      currentTrackIdRef.current = null;
      lastSerializedRef.current = "";
      setAutosaveStatus("idle");
      return;
    }

    const currentSerialized = JSON.stringify({ params, activePresetId });

    // When track changes, update baseline so we don't overwrite restored draft with defaults
    if (currentTrackIdRef.current !== trackId) {
      currentTrackIdRef.current = trackId;
      lastSerializedRef.current = currentSerialized;
      if (timerRef.current) clearTimeout(timerRef.current);
      setAutosaveStatus("idle");
      return;
    }

    // Initial baseline on track load
    if (!lastSerializedRef.current) {
      lastSerializedRef.current = currentSerialized;
      return;
    }

    // If identical to last saved, do nothing
    if (lastSerializedRef.current === currentSerialized) {
      return;
    }

    setAutosaveStatus("saving");

    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    timerRef.current = setTimeout(async () => {
      try {
        await saveTrackDraft(trackId, params, activePresetId);
        lastSerializedRef.current = currentSerialized;
        setAutosaveStatus("saved");
        setLastSavedAt(new Date());

        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
        idleTimerRef.current = setTimeout(() => {
          setAutosaveStatus("idle");
        }, 2500);
      } catch (err) {
        console.error("Autosave draft failed:", err);
        setAutosaveStatus("error");
      }
    }, debounceMs);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [trackId, enabled, params, activePresetId, debounceMs]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    };
  }, []);

  return {
    autosaveStatus,
    lastSavedAt,
    forceSave,
  };
}
