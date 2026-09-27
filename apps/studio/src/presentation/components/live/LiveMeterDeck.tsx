/**
 * LiveMeterDeck — panel de meters en vivo del Live Engine.
 *
 * Reemplaza a LiveMeters.tsx y elimina su anti-patrón: antes el engine hacía
 * setState por frame y el componente re-renderizaba React a 60fps. Ahora el
 * engine publica un `LiveMeterReading` en liveMeterBus por frame, y este deck
 * se SUSCRIBE imperativamente (subscribe → getSnapshot) dibujando en canvas:
 * cero re-renders de React, cero reconciliation en el hot path.
 *
 * Estructura:
 *   - PresetHeader (estado LENTO, DOM/React) arriba: preset + chip de estado
 *     vivo + toggle Original | Master.
 *   - Canvas (hot path imperativo): espectro + waveform overlay, meters L/R
 *     con peak hold 1.5s, latch de clip persistente (click lo resetea),
 *     TP estático del lado seleccionado, mini-cards LOUDNESS MOM/ST/INT con
 *     marcador de target del preset, correlación, width % y master dB.
 *
 * Tokens: los colores se leen de var(--...) UNA vez al montar vía
 * getComputedStyle (nunca en el hot path). No hay hexes hardcodeados en el
 * dibujo — solo rgba sobre blancos/negros o derivados de tokens leídos.
 */

'use client';

import { useCallback, useEffect, useRef } from 'react';
import { subscribe, getSnapshot, type LiveMeterReading } from '@/lib/live/liveMeterBus';
import { rmsToDb, clamp, corrState } from '@/lib/live/meterMath';
import { PRESET_INFO } from '@/core/presets';
import { PresetHeader, type LiveSide, type LiveStaticMetrics } from './PresetHeader';

/** Alto del PresetHeader (px) — el canvas vive debajo. */
const HEADER_H = 60;
/** Fallback de target LUFS cuando no hay preset activo (mismo default que AnalysisPanel). */
const DEFAULT_TARGET_LUFS = -14;
/** Pico ≥ este umbral fija el latch de clip (dBFS). */
const CLIP_THRESHOLD_DB = -0.5;
/** Escala de la barra de width: 1.5 = extra-wide. */
const WIDTH_SCALE = 1.5;

const SPECTRUM_LABELS = ['20Hz', '250Hz', '1kHz', '4kHz', '12kHz+'];

interface LiveMeterDeckProps {
  /** Ancho en px CSS. */
  width?: number;
  /** Alto en px CSS (header + canvas). */
  height?: number;
  /** Preset activo del flujo de mastering (header + target LUFS). */
  presetId?: string | null;
  isPlaying: boolean;
  isActive: boolean;
  hasMaster: boolean;
  /** Lado del A/B estático (Original | Master). */
  side: LiveSide;
  originalMetrics?: LiveStaticMetrics | null;
  masterMetrics?: LiveStaticMetrics | null;
  onSideChange: (side: LiveSide) => void;
}

/** Colores de token — leídos UNA vez al montar del documentElement. */
interface DeckTokens {
  meterSafe: string;
  meterWarn: string;
  meterClip: string;
  accentSecondary: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
}

function readCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function readDeckTokens(): DeckTokens {
  // Fallbacks = valores actuales de los tokens (no introducen colores nuevos).
  return {
    meterSafe: readCssVar('--meter-safe', '#34c759'),
    meterWarn: readCssVar('--meter-warn', '#ff9500'),
    meterClip: readCssVar('--meter-clip', '#ff3b30'),
    accentSecondary: readCssVar('--accent-secondary', '#829ca1'),
    textPrimary: readCssVar('--text-primary', '#e8e8e8'),
    textSecondary: readCssVar('--text-secondary', '#8a8a8a'),
    textMuted: readCssVar('--text-muted', '#555555'),
  };
}

/** rgba derivado de un token YA leído (permitido: derivados de tokens). */
function withAlpha(hexColor: string, alpha: number): string {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hexColor.trim());
  if (!m) return hexColor;
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 0xff;
  const g = (n >> 8) & 0xff;
  const b = n & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Fracción de barra en la banda -60..0 dB (silencio = 0, 0 dBFS = 1). */
function dbToFraction(db: number): number {
  return clamp((db + 60) / 60, 0, 1);
}

/** Escala de loudness -40..0 LUFS → 0..1 (para marcadores de las cards). */
function lufsToFrac(lufs: number): number {
  return clamp((lufs + 40) / 40, 0, 1);
}

export function LiveMeterDeck({
  width = 280,
  height = 400,
  presetId = null,
  isPlaying,
  isActive,
  hasMaster,
  side,
  originalMetrics = null,
  masterMetrics = null,
  onSideChange,
}: LiveMeterDeckProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tokensRef = useRef<DeckTokens | null>(null);
  const reducedMotionRef = useRef(false);
  const clipLatchedRef = useRef(false);
  const redrawRef = useRef<() => void>(() => {});

  const canvasH = height - HEADER_H;

  // CLIP se resetea con click en el deck (evento lento, nunca en el hot path).
  const handleDeckClick = useCallback(() => {
    if (!clipLatchedRef.current) return;
    clipLatchedRef.current = false;
    redrawRef.current();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Tokens UNA vez al montar (fuera del hot path), con fallbacks sin hexes nuevos.
    if (!tokensRef.current) tokensRef.current = readDeckTokens();
    const T = tokensRef.current;

    // prefers-reduced-motion leído una vez: sin suavizado ni release interpolado.
    reducedMotionRef.current =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const W = width;
    const H = canvasH;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;

    // Métricas estáticas del lado seleccionado (INT estático + TP secundario).
    const metrics = side === 'master' ? masterMetrics : originalMetrics;
    const intLufs = metrics?.integrated_lufs ?? null;
    const tpDb = metrics?.true_peak_db ?? null;
    const targetLufs =
      (presetId ? PRESET_INFO[presetId]?.targetLufs : undefined) ?? DEFAULT_TARGET_LUFS;

    // Peak hold por canal: retiene el pico 1.5s, luego suelta al pico actual.
    let holdL = -96;
    let holdR = -96;
    let holdUntilL = 0;
    let holdUntilR = 0;
    const HOLD_MS = 1500;

    const draw = (r: LiveMeterReading) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      const specH = Math.round(H * 0.33);
      const mY0 = specH + 26;
      const mY1 = H - 124;
      const mH = mY1 - mY0;
      const cardY = mY1 + 34;
      const cardH = 28;
      const corrRowY = cardY + cardH + 7;
      const widthRowY = corrRowY + 15;
      const masterRowY = widthRowY + 15;

      const barTrackH = 6;
      const labelW = 46;
      const valueW = 116;
      const barX = 8 + labelW;
      const barW = W - 16 - labelW - valueW;

      // ── Espectro superior ──────────────────────────────────────────
      const barCount = Math.min(r.frequency.length, 128);
      if (barCount > 0) {
        const barWpx = W / barCount;
        const maxBarH = specH * 0.86;
        for (let i = 0; i < barCount; i++) {
          const v = r.frequency[i] / 255;
          const bh = v * maxBarH;
          const hue = 170 - (i / barCount) * 40;
          ctx.fillStyle = `hsl(${hue}, ${60 + v * 30}%, ${35 + v * 40}%)`;
          ctx.beginPath();
          ctx.roundRect(i * barWpx + 0.5, specH - bh, Math.max(1, barWpx - 1), bh, Math.max(0.6, barWpx * 0.3));
          ctx.fill();
        }
      }

      // Forma de onda (overlay sutil sobre el espectro)
      if (r.timeDomain.length > 0) {
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        const midY = specH / 2;
        for (let i = 0; i < r.timeDomain.length; i++) {
          const x = (i / r.timeDomain.length) * W;
          const y = midY + ((r.timeDomain[i] - 128) / 128) * (specH * 0.15);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // Labels de frecuencia
      ctx.fillStyle = T.textMuted;
      ctx.font = '9px "Inter", ui-monospace, monospace';
      ctx.textBaseline = 'alphabetic';
      const last = SPECTRUM_LABELS.length - 1;
      SPECTRUM_LABELS.forEach((label, i) => {
        if (i === 0) {
          ctx.textAlign = 'left';
          ctx.fillText(label, 2, specH - 4);
        } else if (i === last) {
          ctx.textAlign = 'right';
          ctx.fillText(label, W - 2, specH - 4);
        } else {
          ctx.textAlign = 'center';
          ctx.fillText(label, (i / last) * W, specH - 4);
        }
      });

      // Divisor sutil
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, specH + 2);
      ctx.lineTo(W, specH + 2);
      ctx.stroke();

      // ── Peak hold L/R ──────────────────────────────────────────────
      // Reduced motion: release inmediato (valores directos, sin retención);
      // normal: hold de 1.5s que suelta al pico actual.
      const now = performance.now();
      if (reducedMotionRef.current) {
        holdL = r.peakL;
        holdR = r.peakR;
      } else {
        if (r.peakL >= holdL) {
          holdL = r.peakL;
          holdUntilL = now + HOLD_MS;
        } else if (now > holdUntilL) {
          holdL = r.peakL;
        }
        if (r.peakR >= holdR) {
          holdR = r.peakR;
          holdUntilR = now + HOLD_MS;
        } else if (now > holdUntilR) {
          holdR = r.peakR;
        }
      }

      // ── Clip latch PERSISTENTE ─────────────────────────────────────
      // Se fija con pico ≥ CLIP_THRESHOLD_DB y NO suelta solo: se resetea con
      // click en el deck (handleDeckClick). El hold de 1.5s por canal queda.
      if (r.peakL >= CLIP_THRESHOLD_DB || r.peakR >= CLIP_THRESHOLD_DB) {
        clipLatchedRef.current = true;
      }

      // ── Meters L/R (banda -60..0 dB, por canal) ────────────────────
      const meterW = 26;
      const meterGap = 44;
      const mX1 = W / 2 - meterGap / 2 - meterW;
      const mX2 = W / 2 + meterGap / 2;

      const drawMeter = (x: number, label: string, level: number, hold: number) => {
        // Label del canal
        ctx.fillStyle = T.textSecondary;
        ctx.font = '9px "Inter", ui-monospace, monospace';
        ctx.textAlign = 'center';
        ctx.fillText(label, x + meterW / 2, mY0 - 6);

        // Track
        ctx.fillStyle = 'rgba(0,0,0,0.4)';
        ctx.beginPath();
        ctx.roundRect(x, mY0, meterW, mH, 6);
        ctx.fill();

        // Fill: RMS en dB dentro de la banda -60..0
        const db = rmsToDb(level);
        const fillH = dbToFraction(db) * mH;
        if (fillH > 0.5) {
          const grad = ctx.createLinearGradient(0, mY1, 0, mY0);
          grad.addColorStop(0, T.meterSafe);
          grad.addColorStop(0.72, T.meterWarn);
          grad.addColorStop(1, T.meterClip);
          ctx.fillStyle = grad;
          ctx.fillRect(x + 1, mY1 - fillH, meterW - 2, fillH);
        }

        // Línea de peak hold
        const holdY = mY1 - dbToFraction(hold) * mH;
        ctx.fillStyle = T.meterClip;
        ctx.fillRect(x + 1, holdY, meterW - 2, 2);

        // Valor RMS del canal
        ctx.fillStyle = T.textSecondary;
        ctx.font = '9px "Inter", ui-monospace, monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`${db.toFixed(1)}dB`, x + meterW / 2, mY1 + 12);
      };

      drawMeter(mX1, 'L', r.levelL, holdL);
      drawMeter(mX2, 'R', r.levelR, holdR);

      // ── TP estático (lado seleccionado) + latch de clip ────────────
      const clipY = mY1 + 22;
      const latched = clipLatchedRef.current;
      ctx.font = '9px "Inter", ui-monospace, monospace';
      ctx.fillStyle = latched ? T.meterClip : T.textMuted;
      ctx.beginPath();
      ctx.arc(10, clipY, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.textAlign = 'left';
      ctx.fillText('CLIP', 18, clipY + 3);
      // TP estático secundario del lado seleccionado (solo si el campo existe)
      if (tpDb !== null && tpDb !== undefined) {
        ctx.textAlign = 'right';
        ctx.fillStyle = T.textPrimary;
        ctx.fillText(`TP ${tpDb >= 0 ? '+' : ''}${tpDb.toFixed(1)} dBTP`, W - 8, clipY + 3);
      }

      // ── Mini-cards LOUDNESS: MOM (~400ms) / ST (~3s) / INT (estático) ──
      const cards: Array<{ label: string; hint: string; value: number | null }> = [
        { label: 'MOM', hint: '~400ms', value: r.momentaryLufs },
        { label: 'ST', hint: '~3s', value: r.shortTermLufs },
        { label: 'INT', hint: side === 'master' ? 'master' : 'original', value: intLufs },
      ];
      const cardGap = 8;
      const cardW = (W - 16 - cardGap * 2) / 3;
      cards.forEach((card, i) => {
        const x = 8 + i * (cardW + cardGap);

        // INT: highlight del lado seleccionado (blanco derivado, sin colores nuevos)
        ctx.fillStyle = i === 2 ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.05)';
        ctx.beginPath();
        ctx.roundRect(x, cardY, cardW, cardH, 6);
        ctx.fill();

        // Label + hint de ventana
        ctx.fillStyle = T.textSecondary;
        ctx.font = '8px "Inter", ui-monospace, monospace';
        ctx.textAlign = 'left';
        ctx.fillText(card.label, x + 6, cardY + 9);
        ctx.textAlign = 'right';
        ctx.fillStyle = T.textMuted;
        ctx.fillText(card.hint, x + cardW - 6, cardY + 9);

        // Valor + unidad LUFS SIEMPRE visible
        const vStr = card.value === null ? '—' : card.value.toFixed(1);
        ctx.font = '10px "Inter", ui-monospace, monospace';
        ctx.fillStyle = T.textPrimary;
        ctx.textAlign = 'left';
        ctx.fillText(vStr, x + 6, cardY + 21);
        ctx.font = '8px "Inter", ui-monospace, monospace';
        ctx.fillStyle = T.textMuted;
        ctx.fillText('LUFS', x + 6 + ctx.measureText(vStr).width + 4, cardY + 21);

        // Barra con marcador de target del preset (opacidad blanca + border-subtle)
        const barXc = x + 6;
        const barWc = cardW - 12;
        const barYc = cardY + cardH - 5;
        ctx.fillStyle = 'rgba(255,255,255,0.06)';
        ctx.beginPath();
        ctx.roundRect(barXc, barYc, barWc, 3, 1.5);
        ctx.fill();
        ctx.fillStyle = 'rgba(255,255,255,0.5)';
        ctx.fillRect(barXc + lufsToFrac(targetLufs) * barWc - 0.5, barYc - 1, 1, 5);
        // Marcador del valor actual (si existe)
        if (card.value !== null) {
          ctx.fillStyle = T.textPrimary;
          ctx.fillRect(barXc + lufsToFrac(card.value) * barWc - 0.5, barYc - 1, 1, 5);
        }
      });

      // ── Tira inferior: correlación / width / master ───────────────
      const row = (label: string, y: number, barFill: number, valueText: string, valueColor: string, marker?: number) => {
        ctx.fillStyle = T.textSecondary;
        ctx.font = '9px "Inter", ui-monospace, monospace';
        ctx.textAlign = 'left';
        ctx.fillText(label, 8, y + 10);

        ctx.fillStyle = 'rgba(255,255,255,0.06)';
        ctx.beginPath();
        ctx.roundRect(barX, y, barW, barTrackH, 3);
        ctx.fill();

        if (barFill > 0.01 && barFill <= 1) {
          ctx.fillStyle = valueColor;
          ctx.fillRect(barX, y, barW * barFill, barTrackH);
        }

        if (marker !== undefined) {
          const mx = barX + clamp(marker, 0, 1) * barW;
          ctx.fillStyle = T.textPrimary;
          ctx.fillRect(mx - 0.5, y - 1.5, 1, barTrackH + 3);
        }

        ctx.fillStyle = valueColor;
        ctx.textAlign = 'right';
        ctx.fillText(valueText, W - 8, y + 10);
      };

      // Correlación: mitades teñidas (derivadas de tokens) + corrState (0.6/0.3)
      const corrPos = clamp((r.correlation + 1) / 2, 0, 1);
      ctx.fillStyle = T.textSecondary;
      ctx.font = '9px "Inter", ui-monospace, monospace';
      ctx.textAlign = 'left';
      ctx.fillText('CORR', 8, corrRowY + 10);
      ctx.fillStyle = withAlpha(T.meterClip, 0.2);
      ctx.fillRect(barX + barW / 2, corrRowY, barW / 2, barTrackH);
      ctx.fillStyle = withAlpha(T.meterSafe, 0.2);
      ctx.fillRect(barX, corrRowY, barW / 2, barTrackH);
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(barX, corrRowY, barW, barTrackH, 3);
      ctx.stroke();
      const cs = corrState(r.correlation);
      const corrColor = cs === 'safe' ? T.meterSafe : cs === 'warn' ? T.meterWarn : T.meterClip;
      ctx.fillStyle = corrColor;
      ctx.fillRect(barX + corrPos * barW - 0.5, corrRowY - 1.5, 1, barTrackH + 3);
      ctx.textAlign = 'right';
      ctx.fillText(`${r.correlation >= 0 ? '+' : ''}${r.correlation.toFixed(2)}`, W - 8, corrRowY + 10);

      // Ancho estéreo (escala 0..1.5, full stereo = 100%)
      const widthNorm = clamp(r.width / WIDTH_SCALE, 0, 1);
      row('WIDTH', widthRowY, widthNorm, `${(r.width * 100).toFixed(0)}%`, T.accentSecondary, widthNorm);

      // Master: RMS en dB (la loudness vive en las cards MOM/ST/INT)
      const masterDb = rmsToDb(r.outputLevel);
      row('MASTER', masterRowY, dbToFraction(masterDb), `${masterDb.toFixed(1)} dB`, T.textPrimary);
    };

    // Suscripción imperativa: dibujar en cada publish, sin re-render React.
    redrawRef.current = () => draw(getSnapshot());
    const unsubscribe = subscribe(() => draw(getSnapshot()));
    draw(getSnapshot());

    return () => {
      unsubscribe();
      redrawRef.current = () => {};
    };
  }, [width, canvasH, presetId, side, originalMetrics, masterMetrics]);

  return (
    <div
      className="rounded-2xl bg-[var(--bg-glass)] border border-[var(--border-subtle)] overflow-hidden"
      onClick={handleDeckClick}
    >
      <PresetHeader
        presetId={presetId}
        isPlaying={isPlaying}
        isActive={isActive}
        hasMaster={hasMaster}
        side={side}
        onSideChange={onSideChange}
        canMaster={masterMetrics !== null}
      />
      {/* Canvas decorativo: dibuja en el hot path; accesible vía header/DOM */}
      <canvas
        ref={canvasRef}
        style={{ width, height: canvasH, display: 'block' }}
        aria-hidden="true"
      />
    </div>
  );
}