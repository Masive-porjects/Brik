"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  ChevronDown,
  Pause,
  Play,
  SkipBack,
} from "lucide-react";
import { useTranslation } from "@/i18n";

interface MixWaveformABProps {
  /** URL del audio original (persistido en el backend). */
  originalUrl: string;
  /** URL del WAV mezclado (objectURL local o URL estable de sesión). */
  mixedUrl: string;
  /** Duración total del mix (``mixResult.duration_seconds`` /
   *  ``sessionMixAnalysis``). Si no hay dato, no se muestra.
   */
  mixedDuration?: number | null;
  /** ``hasMix`` del backend (``mix_status === "completed"``, T2): la
   *  insignia "Audio mezclado" se muestra solo con una mezcla ENTREGADA,
   *  nunca con un WAV local en vuelo o fallido. */
  hasMix?: boolean;
}

/* ── Tokens de onda (v5 — dark mode) ────────────────────
   WaveSurfer pinta sobre canvas (``fillStyle``), y canvas NO resuelve
   ``var(--x)`` de CSS: los tokens se leen vía getComputedStyle en runtime
   (cliente) en cada montaje de onda, cayendo al valor legacy si el token
   faltara. Único punto de contacto entre globals.css y el canvas.
   ``--waveform-original`` / ``--waveform-mastered`` son invariantes de
   tema; ``--text-secondary`` (progreso del lado original) sí cambia con
   el tema y se re-lee en cada remount. */

function tokenHex(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

/** Mezcla un hex con blanco (t) — "derivado" del token de onda para el
 *  progreso del lado mezclado (mint claro, misma familia de marca). */
function mixWithWhite(hex: string, t: number): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  const mix = (c: number) => Math.round(c + (255 - c) * t);
  return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
}

const ORIG_COLORS = {
  wave: () => tokenHex("--waveform-original", "#484855"),
  progress: () => tokenHex("--text-secondary", "#9aa0b5"),
};
const MIXED_COLORS = {
  wave: () => tokenHex("--waveform-mastered", "#00d4aa"),
  progress: () => mixWithWhite(tokenHex("--waveform-mastered", "#00d4aa"), 0.55),
};

/* ── Texturas de render ─────────────────────────────────
   AMBOS lados decodifican el WAV real (WaveSurfer `load(url)`);
   la diferencia es SOLO estética de picos, nunca datos inventados:
   - Mezclado (Final): `barWidth 0` activa el modo de picos CONTINUOS
     de WaveSurfer (shouldRenderBars=false → drawWaveform): envelope
     suave y pulido tipo "masterizado".
   - Original (RAW): bars gruesos y espaciados → textura densa y oscura. */

interface WsTexture {
  barWidth: number;
  barGap: number;
  barRadius: number;
  height: number;
  /** zoom por segundo reservado — en createWS se fuerza a 0 para que la
   *  onda ajuste al ancho completo del contenedor (0:00 → duración total,
   *  sin scroll ni paneo). */
  minPxPerSec: number;
}

const ORIG_TEXTURE: WsTexture = {
  barWidth: 3,
  barGap: 2,
  barRadius: 2,
  height: 64,
  minPxPerSec: 40,
};

const MIXED_TEXTURE: WsTexture = {
  barWidth: 0, // picos continuos (envelope)
  barGap: 0,
  barRadius: 0,
  height: 72,
  minPxPerSec: 60,
};

/* ── Helpers ───────────────────────────────────────────── */

function formatTime(t: number): string {
  if (!Number.isFinite(t) || t < 0) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function createWS(
  container: HTMLDivElement,
  url: string,
  waveColor: string,
  progressColor: string,
  texture: WsTexture,
): WaveSurfer {
  const ws = WaveSurfer.create({
    container,
    waveColor,
    progressColor,
    cursorColor: "transparent",
    cursorWidth: 0,
    interact: true,
    barWidth: texture.barWidth,
    barGap: texture.barGap,
    barRadius: texture.barRadius,
    height: texture.height,
    // La onda debe ocupar SIEMPRE el ancho completo del contenedor y
    // extenderse de 0:00 a la duración total, sin scroll horizontal ni
    // desplazamiento lateral al reproducir. Con `minPxPerSec > 0`
    // WaveSurfer crea un corredor de `ceil(duración × px/seg)` píxeles:
    // más ancho que el contenedor → scroll-x interno y paneo automático
    // durante la reproducción. 0 = fit exacto del contenedor (onda
    // completa siempre visible). Las texturas estéticas (envelope
    // continuo / bars densos) viven en barWidth/barGap y no cambian.
    minPxPerSec: 0,
    normalize: true,
  });

  // Swallow load errors (CORS / URL temporalmente inalcanzable): la UI
  // degrada a controles deshabilitados en vez de romper el panel.
  const p = ws.load(url);
  if (p && typeof p.catch === "function") {
    p.catch(() => {});
  }

  return ws;
}

function destroyWS(ws: WaveSurfer | null) {
  if (!ws) return;
  try {
    ws.unAll();
    ws.pause();
    ws.destroy();
  } catch {
    // Swallow AbortError o doble destroy
  }
}

/* ── Mitad A/B individual ────────────────────────────────
   Cada lado es una instancia WaveSurfer independiente (sin
   sincronización entre ambas): su propio play/pause, ⏮ y
   contador, alimentados por `timeupdate`. Click-to-seek
   nativo vía `interact: true`. */

interface WaveSideProps {
  url: string;
  kind: "original" | "mixed";
  /** Duración total del mix (solo lado mezclado; se omite sin dato). */
  mixedDuration?: number | null;
  /** Solo lado mezclado: hay mezcla entregada por el backend → insignia. */
  hasMix?: boolean;
}

function WaveSide({ url, kind, mixedDuration, hasMix }: WaveSideProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const isCleaningRef = useRef(false);
  const { t } = useTranslation();

  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [ready, setReady] = useState(false);

  const isMixed = kind === "mixed";
  const colors = isMixed ? MIXED_COLORS : ORIG_COLORS;

  // Crear / destruir la instancia al montar y al cambiar la URL.
  // Solo corre en el cliente (useEffect) — SSR intacto.
  useEffect(() => {
    isCleaningRef.current = false;

    destroyWS(wsRef.current);
    wsRef.current = null;

    const resetTimer = setTimeout(() => {
      setPlaying(false);
      setCurrentTime(0);
      setDuration(0);
      setReady(false);
    }, 0);

    if (!containerRef.current) return;

    const texture = isMixed ? MIXED_TEXTURE : ORIG_TEXTURE;
    const ws = createWS(
      containerRef.current,
      url,
      colors.wave(),
      colors.progress(),
      texture,
    );
    wsRef.current = ws;

    const onReady = () => {
      if (isCleaningRef.current) return;
      setDuration(ws.getDuration());
      setReady(true);
    };
    const onTimeUpdate = (t: number) => {
      if (isCleaningRef.current) return;
      setCurrentTime(t);
    };

    ws.on("ready", onReady);
    ws.on("timeupdate", onTimeUpdate);
    ws.on("play", () => {
      if (!isCleaningRef.current) setPlaying(true);
    });
    ws.on("pause", () => {
      if (!isCleaningRef.current) setPlaying(false);
    });
    ws.on("finish", () => {
      if (!isCleaningRef.current) setPlaying(false);
    });

    return () => {
      clearTimeout(resetTimer);
      isCleaningRef.current = true;
      destroyWS(wsRef.current);
      wsRef.current = null;
    };
    // Solo por cambio de URL
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const togglePlay = useCallback(() => {
    wsRef.current?.playPause();
  }, []);

  const restart = useCallback(() => {
    wsRef.current?.setTime(0);
    setCurrentTime(0);
  }, []);

  const playheadPct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      className="flex min-w-0 flex-col rounded-2xl"
      style={{
        background: "var(--bg-glass)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
      }}
    >
      {/* Etiqueta + insignia */}
      <div className="flex items-center justify-between gap-2 px-3 pt-3">
        <p
          className="text-[10px] font-bold uppercase tracking-[0.14em]"
          style={{ color: isMixed ? "#10b981" : "var(--text-secondary)" }}
        >
          {isMixed
            ? t("mezcla.mixedSideLabel", "Audio mezclado (Final)")
            : t("mezcla.originalSideLabel", "Original (Raw)")}
        </p>
        {isMixed && hasMix && (
          <motion.span
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-subtle)",
              color: "var(--accent-primary)",
            }}
            data-testid="mix-delivered-badge"
          >
            <CheckCircle2 size={11} />
            {t("mezcla.mixedAudioBadge", "Audio mezclado")}
          </motion.span>
        )}
      </div>

      {/* Onda + playhead — el contenedor queda transparente: la textura
          del waveform flota sobre el glass del lado */}
      <div
        className="relative mx-3 mt-2 w-full min-w-0 overflow-hidden rounded-lg"
        style={{
          height: 72,
          background: "transparent",
          cursor: "pointer",
        }}
      >
        {/* Glow verde-azulado por detrás del lado mezclado */}
        {isMixed && (
          <div
            className="pointer-events-none absolute inset-0 transition-opacity duration-300"
            style={{
              background:
                "radial-gradient(ellipse at 50% 50%, rgba(16, 185, 129, 0.10) 0%, transparent 70%)",
              opacity: playing ? 1 : 0.6,
            }}
          />
        )}
        <div ref={containerRef} className="h-full w-full min-w-0" />
        {ready && duration > 0 && (
          <div
            className="pointer-events-none absolute bottom-0 top-0 w-[2px]"
            style={{
              left: `${playheadPct}%`,
              transform: "translateX(-50%)",
              background: isMixed ? "#10b981" : "var(--text-secondary)",
              boxShadow: isMixed
                ? "0 0 8px rgba(16, 185, 129, 0.6)"
                : "none",
              transition: "left 60ms linear",
            }}
          />
        )}
      </div>

      {/* Transporte */}
      <div className="flex items-center gap-2 px-3 pb-3">
        <button
          onClick={restart}
          disabled={!ready}
          title="Volver al inicio"
          aria-label="Volver al inicio"
          className="flex h-8 w-8 items-center justify-center rounded-full transition-all hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-30"
          style={{ color: isMixed ? "#10b981" : "var(--text-secondary)" }}
        >
          <SkipBack size={15} fill="currentColor" />
        </button>
        <button
          onClick={togglePlay}
          disabled={!ready}
          aria-label={playing ? "Pausar" : "Reproducir"}
          title={playing ? "Pausar" : "Reproducir"}
          className="flex h-8 w-8 items-center justify-center rounded-full text-white transition-all hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
          style={{ background: isMixed ? "#10b981" : "var(--text-secondary)" }}
        >
          {playing ? (
            <Pause size={14} fill="currentColor" />
          ) : (
            <Play size={14} fill="currentColor" />
          )}
        </button>
        <span className="w-10 font-mono text-xs" style={{ color: "var(--text-secondary)" }}>
          {formatTime(currentTime)}
        </span>
        {isMixed && (
          <>
            <div className="flex-1" />
            {typeof mixedDuration === "number" && (
              <span
                className="flex items-center gap-1 font-mono text-xs text-[var(--text-muted)]"
                data-testid="mix-total-duration"
              >
                {formatTime(mixedDuration)}
                <ChevronDown size={12} />
              </span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ── Vista A/B completa ────────────────────────────────── */

export default function MixWaveformAB({
  originalUrl,
  mixedUrl,
  mixedDuration,
  hasMix,
}: MixWaveformABProps) {
  return (
    <div className="w-full min-w-0 grid grid-cols-1 gap-3 md:grid-cols-2">
      <WaveSide url={originalUrl} kind="original" />
      <WaveSide
        url={mixedUrl}
        kind="mixed"
        mixedDuration={mixedDuration}
        hasMix={hasMix}
      />
    </div>
  );
}