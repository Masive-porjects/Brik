/**
 * PresetHeader — cabecera del Live Meter Deck.
 *
 * Estado LENTO por diseño: preset activo, toggle Original | Master, chip de
 * estado vivo. El chip lee la señal REAL del bus vía useLiveMeterReading
 * (re-render acotado a este span; el canvas del deck sigue 100% imperativo).
 *
 * El toggle imita el patrón visual de pills de Player.tsx (thumb deslizante +
 * botones: grid de 2, bg --surface-hover, active --accent-primary).
 */

'use client';

import { useState } from 'react';
import { PRESET_INFO, PRESET_COLORS, DEFAULT_PRESET_COLOR } from '@/core/presets';
import { useLiveMeterReading } from '@/lib/live/liveMeterBus';

/** Lado seleccionado en el toggle Original | Master. */
export type LiveSide = 'original' | 'master';

/**
 * Métricas estáticas por lado — espejo de AnalysisResult/MasterResultMetrics
 * (campos reales de los tipos API: integrated_lufs / true_peak_db / crest_factor_db).
 */
export interface LiveStaticMetrics {
  integrated_lufs: number | null;
  true_peak_db: number | null;
  crest_factor_db: number | null;
}

interface PresetHeaderProps {
  /** Preset activo del flujo de mastering (PRESET_INFO lookup). */
  presetId?: string | null;
  isPlaying: boolean;
  isActive: boolean;
  hasMaster: boolean;
  side: LiveSide;
  onSideChange: (side: LiveSide) => void;
  /** Habilita el lado Master en el toggle (sin master result → deshabilitado). */
  canMaster: boolean;
}

type StatusKind = 'playing' | 'paused' | 'no_signal';

const STATUS_LABEL: Record<StatusKind, string> = {
  playing: 'En reproducción',
  paused: 'Pausado',
  no_signal: 'Sin señal',
};

/**
 * Chip de estado vivo: "En reproducción" (dot --meter-safe), "Pausado",
 * "Sin señal" (idle/sin buffer). Derivado de isPlaying + isActive + señal real
 * del bus. "Pausado" solo tras haber reproducido alguna vez con este master.
 */
function StatusChip({
  isPlaying,
  isActive,
  hasMaster,
}: {
  isPlaying: boolean;
  isActive: boolean;
  hasMaster: boolean;
}) {
  const reading = useLiveMeterReading();

  // Distingue "Pausado" (hubo play) de "Sin señal" (nunca arrancó / sin master).
  // everPlayed es STATE (se lee durante render). Ajuste de estado durante
  // render (patrón oficial React, guardado): master nuevo → reset de historial;
  // primer play → marca everPlayed.
  const [everPlayed, setEverPlayed] = useState(false);
  const [prevHasMaster, setPrevHasMaster] = useState(hasMaster);
  if (prevHasMaster !== hasMaster) {
    setPrevHasMaster(hasMaster);
    if (hasMaster) setEverPlayed(false);
  }
  if (isPlaying && !everPlayed) setEverPlayed(true);

  // Señal real: RMS o pico por encima del piso (el bus publica ceros en pausa,
  // así que el largo de frequency NO sirve para detectar señal).
  const hasSignal = reading.outputLevel > 0.0005 || reading.peakL > -90;

  let status: StatusKind;
  if (!isActive || !hasMaster) {
    status = 'no_signal';
  } else if (isPlaying || hasSignal) {
    status = 'playing';
  } else if (everPlayed) {
    status = 'paused';
  } else {
    status = 'no_signal';
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-secondary)] whitespace-nowrap">
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: status === 'playing' ? 'var(--meter-safe)' : 'var(--text-muted)' }}
        aria-hidden="true"
      />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function PresetHeader({
  presetId,
  isPlaying,
  isActive,
  hasMaster,
  side,
  onSideChange,
  canMaster,
}: PresetHeaderProps) {
  const info = presetId ? PRESET_INFO[presetId] : undefined;
  const presetColor =
    (presetId ? PRESET_COLORS[presetId]?.wave : undefined) ?? DEFAULT_PRESET_COLOR.wave;
  const title = info?.title ?? presetId ?? 'Live';
  const sourceIndex = side === 'master' ? 1 : 0;

  return (
    <div className="px-3 pt-2 pb-1.5 border-b border-[var(--border-subtle)] space-y-1.5">
      {/* Fila 1: preset + estado vivo */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: presetColor }}
            aria-hidden="true"
          />
          <span className="text-xs font-semibold text-[var(--text-primary)] truncate">
            {title}
          </span>
        </div>
        <StatusChip isPlaying={isPlaying} isActive={isActive} hasMaster={hasMaster} />
      </div>

      {/* Fila 2: toggle Original | Master — mismo patrón de pills que Player */}
      <div className="relative grid grid-cols-2 bg-[var(--surface-hover)] rounded-full p-0.5 w-full max-w-[200px]">
        <div
          className="absolute top-0.5 bottom-0.5 left-0 rounded-full bg-[var(--accent-primary)]"
          style={{
            width: 'calc((100% - 4px) / 2)',
            opacity: 0.25,
            transform: `translateX(calc(${sourceIndex * 100}% + 2px))`,
            transition: 'transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)',
          }}
        />
        <button
          type="button"
          onClick={() => onSideChange('original')}
          className={`relative z-10 px-2 py-0.5 rounded-full text-[10px] font-medium text-center transition-colors duration-200 ${
            side === 'original'
              ? 'text-[var(--accent-primary)]'
              : 'text-[var(--text-muted)]'
          }`}
        >
          Original
        </button>
        <button
          type="button"
          onClick={() => onSideChange('master')}
          disabled={!canMaster}
          className={`relative z-10 px-2 py-0.5 rounded-full text-[10px] font-medium text-center transition-colors duration-200 ${
            side === 'master'
              ? 'text-[var(--accent-primary)]'
              : 'text-[var(--text-muted)]'
          } disabled:opacity-30 disabled:cursor-not-allowed`}
        >
          Master
        </button>
      </div>
    </div>
  );
}