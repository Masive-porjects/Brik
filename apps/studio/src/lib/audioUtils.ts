/**
 * lib/audioUtils.ts
 *
 * Funciones puras extraídas del Home() component.
 * Estas funciones son testeables en aislamiento y reutilizables.
 */

import type { MixStatus, SessionData, MasteringParameters } from "@/lib/api";
import { DEFAULT_PARAMS } from "@/lib/api";
import { useSyncExternalStore } from "react";

/* ── Genre to mastering params mapping ───────────────────── */

export function genreToParams(genre: string | null): MasteringParameters {
  const p: MasteringParameters = { ...DEFAULT_PARAMS };
  if (!genre) return p;

  switch (genre.toLowerCase()) {
    case "urban":
    case "hip_hop": // id emitido por _detect_genre (underscore)
    case "hip-hop":
    case "reggaeton":
      p.compression_ratio = 4.0;
      p.limiter_ceiling_db = -1.0;
      p.transient_boost_db = 2.0;
      p.haas_delay_ms = 5;
      p.stereo_width = 1.2;
      p.target_lufs_db = -12;
      break;
    case "rock":
    case "indie":
      p.compression_ratio = 2.5;
      p.transient_boost_db = 1.0;
      p.saturation_drive_db = 3.0;
      p.saturation_warmth_db = 2.0;
      p.stereo_width = 1.2;
      break;
    case "pop":
    case "electronic":
    case "electrónica":
      p.clarity_brightness_db = 2.0;
      p.compression_ratio = 3.0;
      p.stereo_width = 1.4;
      p.haas_delay_ms = 8;
      break;
    case "jazz":
    case "classical":
    case "clásica":
      p.compression_ratio = 1.5;
      p.limiter_ceiling_db = -2.0;
      p.clarity_wet = 0.25;
      break;
    case "latin":
    case "latino":
    case "fusion":
      p.compression_ratio = 3.0;
      p.transient_boost_db = 1.5;
      p.saturation_drive_db = 2.0;
      p.stereo_width = 1.1;
      break;
  }
  return p;
}

/* ── Check if preset's master is ready to be fetched ───────── */

/** Etiqueta de display para un género detectado. El backend emite ids con
 *  underscore (``hip_hop``); null / "other" se normalizan a "Otro". */
export function genreDisplayLabel(genre: string | null): string {
  if (!genre || genre === "other") return "Otro";
  if (genre === "hip_hop") return "Rap / Hip-Hop";
  return genre.replace("_", " ");
}

export function isPresetCompleted(
  session: SessionData,
  presetId: string | null | undefined,
): boolean {
  if (!presetId) {
    return Boolean(session.mastered_path);
  }
  return session.preset_masters?.[presetId]?.status === "completed" || Boolean(session.mastered_path);
}

/* ── Mix Engine state (T2) ─────────────────────────────── */

/**
 * ``hasMix``: the session holds a DELIVERED mix the master can consume.
 *
 * Source of truth is the backend-owned ``session.mix_status`` (T2) — the UI
 * never infers it from the presence of a local mix blob. Only
 * ``mix_status === "completed"`` counts: ``processing``/``failed``/absent all
 * mean "no masterable mix" (the backend rejects ``source=mix`` with a 400 in
 * those states), so the caller can safely branch on this single boolean.
 */
export function hasCompletedMix(
  session: SessionData | null | undefined,
): boolean {
  return session?.mix_status === "completed";
}

/* ── Mix gate (T4) ─────────────────────────────────────── */

/**
 * ``mix_status`` normalizado. Un campo ausente (sesión guardada antes del
 * contrato T2) equivale a ``"none"``: nunca mezcló → el master está libre.
 */
export function resolveMixStatus(
  raw: MixStatus | null | undefined,
): MixStatus {
  return raw ?? "none";
}

/** Resultado del gate de mezcla que gobierna el avance al master (T4). */
export interface MixGate {
  /** Estado de mezcla tal como lo publica el backend (nunca ``undefined``). */
  mixStatus: MixStatus;
  /**
   * ``true`` cuando el usuario INICIÓ una mezcla y todavía no entregó el
   * audio mezclado (``processing`` o ``failed``). El master queda bloqueado:
   * no hay archivo mezclado que masterizar, así que el camino correcto es
   * terminar la mezcla. ``none`` y ``completed`` dejan el master libre.
   */
  blocked: boolean;
}

/**
 * ``getMixGate``: la única fuente de verdad del gate NO-bloqueante hacia el
 * master (T4).
 *
 * - ``none``      → master libre (camino solo-master).
 * - ``completed`` → master libre, y el master consume el MIX (``source=mix``).
 * - ``processing``→ BLOQUEADO: la mezcla está en curso.
 * - ``failed``    → BLOQUEADO: la mezcla se intentó y no se entregó.
 *
 * Función pura y testeable en aislamiento: recibe la sesión y devuelve el
 * veredicto, sin side effects ni dependencias del DOM.
 */
export function getMixGate(
  session: SessionData | null | undefined,
): MixGate {
  const mixStatus = resolveMixStatus(session?.mix_status);
  return {
    mixStatus,
    blocked: mixStatus === "processing" || mixStatus === "failed",
  };
}

/* ── Client detection helper ──────────────────────────── */

export function useIsClient(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}

/* ── Progress utilities ───────────────────────────────── */

export function clampProgress(value: number): number {
  return Math.max(0, Math.min(100, value));
}

export function percentString(value: number): string {
  return `${clampProgress(value)}%`;
}

/* ── Progress percentage with rounding ─────────────────── */

export function progressPct(value: number): number {
  return Math.round(clampProgress(value));
}