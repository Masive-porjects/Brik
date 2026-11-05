"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import { useTranslation } from "@/i18n";
import { BASE_PATH } from "@/lib/basePath";
import { AB_METRICS } from "./data";
import Reveal from "./Reveal";
import type { ABMetricDefinition, ABMetricId, AccentToken } from "./types";

/* ─────────────────────────────────────────────────────────────────────────
   Real 40s A/B demo: "RESILIENCIA" (Raw mix vs Brik Master)

   Two 40-second MP3 stems rendered from the same cut of RESILIENCIA:
   • `/audio/resiliencia-raw.mp3`      (-18.5 LUFS, -6.0 dBTP, unmastered headroom)
   • `/audio/resiliencia-mastered.mp3` (-14.0 LUFS, -2.5 dBTP, processed by Brik)

   Both `<audio>` elements play in lockstep through a Web Audio graph with
   two GainNodes. Toggling Crudo/Masterizado or moving the intensity fader
   crossfades smoothly via `setTargetAtTime(..., 0.02)` (zero zipper noise).
   ───────────────────────────────────────────────────────────────────────── */

const BAR_COUNT = 96;
const CLIP_DURATION_SEC = 40;

/** Measured 96-bar envelope of `resiliencia-raw.mp3` (normalized to master peak). */
const RAW_BARS: readonly number[] = [
  0.615, 0.711, 0.435, 0.625, 0.609, 0.509, 0.745, 0.519, 0.711, 0.521, 0.603, 0.723,
  0.703, 0.715, 0.445, 0.729, 0.545, 0.305, 0.711, 0.597, 0.685, 0.577, 0.611, 0.437,
  0.493, 0.745, 0.311, 0.717, 0.321, 0.729, 0.549, 0.645, 0.713, 0.567, 0.741, 0.561,
  0.637, 0.611, 0.583, 0.699, 0.619, 0.611, 0.509, 0.743, 0.529, 0.339, 0.727, 0.599,
  0.727, 0.699, 0.713, 0.489, 0.593, 0.737, 0.305, 0.713, 0.591, 0.695, 0.519, 0.609,
  0.581, 0.491, 0.745, 0.471, 0.717, 0.339, 0.563, 0.238, 0.675, 0.701, 0.519, 0.745,
  0.573, 0.635, 0.583, 0.741, 0.697, 0.627, 0.643, 0.513, 0.737, 0.561, 0.375, 0.725,
  0.615, 0.739, 0.683, 0.709, 0.551, 0.537, 0.739, 0.311, 0.709, 0.593, 0.673, 0.297,
];

/** Measured 96-bar envelope of `resiliencia-mastered.mp3`. */
const MAST_BARS: readonly number[] = [
  0.832, 0.842, 0.507, 0.778, 0.862, 0.754, 0.892, 0.832, 0.892, 0.81, 0.818, 0.874,
  0.79, 0.874, 0.766, 0.944, 0.774, 0.778, 0.892, 0.762, 0.83, 0.619, 0.84, 0.812,
  0.806, 1.0, 0.802, 0.884, 0.802, 0.932, 0.637, 0.834, 0.976, 0.818, 0.912, 0.828,
  0.864, 0.83, 0.727, 0.826, 0.772, 0.87, 0.824, 0.894, 0.828, 0.81, 0.898, 0.812,
  0.88, 0.721, 0.876, 0.77, 0.772, 0.946, 0.78, 0.892, 0.609, 0.836, 0.587, 0.794,
  0.828, 0.818, 1.0, 0.583, 0.888, 0.796, 0.852, 0.415, 0.77, 0.928, 0.745, 0.906,
  0.731, 0.854, 0.808, 0.78, 0.892, 0.735, 0.92, 0.816, 0.87, 0.752, 0.798, 0.892,
  0.864, 0.86, 0.82, 0.842, 0.758, 0.836, 0.932, 0.78, 0.876, 0.812, 0.832, 0.76,
];

const RAW_COLOR: readonly [number, number, number] = [134, 147, 145];
const MASTER_COLOR: readonly [number, number, number] = [110, 233, 224];

const ACCENTS: Record<AccentToken, { text: string; bg: string }> = {
  primary: { text: "text-primary", bg: "bg-primary" },
  secondary: { text: "text-secondary", bg: "bg-secondary" },
  tertiary: { text: "text-tertiary-container", bg: "bg-tertiary-container" },
};

/** Engine processes shown as badges while the Mastered state is active. */
const PROCESS_KEYS = ["saturation", "stereo", "peaks", "push"] as const;

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function formatTime(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r < 10 ? "0" : ""}${r}`;
}

function masteredMetrics(): Record<ABMetricId, number> {
  const out = {} as Record<ABMetricId, number>;
  for (const metric of AB_METRICS) out[metric.id] = metric.mastered;
  return out;
}

function normalize(metric: ABMetricDefinition, value: number): number {
  const span = metric.max - metric.min;
  if (span <= 0) return 0;
  return Math.max(0, Math.min(1, (value - metric.min) / span));
}

interface MetricCardProps {
  metric: ABMetricDefinition;
  value: number;
  label: string;
  unit: string;
}

function MetricCard({ metric, value, label, unit }: MetricCardProps) {
  const accent = ACCENTS[metric.accent];
  const fill = normalize(metric, value) * 100;

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-glass)] p-2.5 sm:p-3">
      <span className="font-label-technical text-[9px] leading-tight text-[var(--text-muted)] sm:text-[10px]">
        {label}
      </span>
      <div className="flex items-baseline justify-between gap-1">
        <span className={`font-metric-val-lg text-base font-bold tabular-nums sm:text-xl ${accent.text}`}>
          {value.toFixed(metric.decimals)}
        </span>
        <span className={`font-label-technical text-[9px] sm:text-xs ${accent.text}`}>{unit}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-active)]">
        <div className={`h-full rounded-full ${accent.bg}`} style={{ width: `${fill}%` }} />
      </div>
    </div>
  );
}

interface FaderProps {
  value: number;
  onChange: (next: number) => void;
  ariaLabel: string;
}

function Fader({ value, onChange, ariaLabel }: FaderProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const trackRectRef = useRef<DOMRect | null>(null);

  const updateFromX = useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      if (!el) return;
      // Usar el rect cacheado al iniciar el puntero: leer getBoundingClientRect
      // en cada pointermove durante el drag forzaría un reflow síncrono por frame.
      const rect = trackRectRef.current ?? el.getBoundingClientRect();
      if (rect.width === 0) return;
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      onChange(Math.round(ratio * 100));
    },
    [onChange],
  );

  return (
    <div
      ref={trackRef}
      role="slider"
      tabIndex={0}
      aria-label={ariaLabel}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-valuetext={`${value}%`}
      className="relative flex h-11 w-full min-w-0 max-w-[220px] cursor-pointer touch-none select-none items-center rounded-full focus-visible:ring-2 focus-visible:ring-primary/70"
      onPointerDown={(event) => {
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        // Cachear la geometría una sola vez al iniciar el puntero.
        trackRectRef.current = event.currentTarget.getBoundingClientRect();
        updateFromX(event.clientX);
      }}
      onPointerMove={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) updateFromX(event.clientX);
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        trackRectRef.current = null;
      }}
      onKeyDown={(event) => {
        const step = event.shiftKey ? 10 : 2;
        let next = value;
        if (event.key === "ArrowRight" || event.key === "ArrowUp") next = value + step;
        else if (event.key === "ArrowLeft" || event.key === "ArrowDown") next = value - step;
        else if (event.key === "PageUp") next = value + 10;
        else if (event.key === "PageDown") next = value - 10;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = 100;
        else return;
        event.preventDefault();
        onChange(Math.min(100, Math.max(0, next)));
      }}
    >
      <div className="absolute inset-x-0 h-1.5 rounded-full bg-[var(--surface-active)]" />
      <div className="absolute left-0 h-1.5 rounded-full bg-primary" style={{ width: `${value}%` }} />
      <div
        className="absolute h-5 w-5 -translate-x-1/2 rounded-full border-2 border-primary bg-[var(--bg-glass-elevated)]"
        style={{ left: `${value}%` }}
      />
    </div>
  );
}

interface RealAudioGraph {
  ctx: AudioContext;
  rawEl: HTMLAudioElement;
  mastEl: HTMLAudioElement;
  rawGain: GainNode;
  mastGain: GainNode;
}

export default function LandingABPlayer() {
  const { t } = useTranslation();
  const prefersReduced = useReducedMotion() ?? false;

  const [isBrik, setIsBrik] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);
  const [intensity, setIntensity] = useState(100);
  const [currentTime, setCurrentTime] = useState(0);
  const [metrics, setMetrics] = useState<Record<ABMetricId, number>>(masteredMetrics);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioRef = useRef<RealAudioGraph | null>(null);

  const stateRef = useRef({ target: 1, playing: false, reduced: false, intensity: 100 });
  const morphRef = useRef(1);
  const phaseRef = useRef(0);
  const playheadRef = useRef(0);

  useEffect(() => {
    stateRef.current.reduced = prefersReduced;
  }, [prefersReduced]);

  /* ── Smooth Web Audio crossfade between Raw and Mastered MP3s ────── */
  const applyMixGains = useCallback(() => {
    const graph = audioRef.current;
    if (!graph) return;
    const { target, intensity: pct } = stateRef.current;
    // Wet factor: 0 = 100% Raw, 1 = 100% Mastered (scaled by intensity when Mastered is active)
    const wet = target === 1 ? Math.max(0, Math.min(1, pct / 100)) : 0;
    const now = graph.ctx.currentTime;
    // Anti-zipper rule: always use setTargetAtTime with 0.02s time constant
    graph.rawGain.gain.setTargetAtTime(1 - wet, now, 0.02);
    graph.mastGain.gain.setTargetAtTime(wet, now, 0.02);
  }, []);

  const ensureGraph = useCallback((): RealAudioGraph | null => {
    if (typeof window === "undefined") return null;
    if (audioRef.current) return audioRef.current;

    type AudioContextCtor = typeof AudioContext;
    const Ctor: AudioContextCtor | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
    if (!Ctor) return null;

    const ctx = new Ctor();
    const rawEl = new Audio(`${BASE_PATH}/audio/resiliencia-raw.mp3`);
    const mastEl = new Audio(`${BASE_PATH}/audio/resiliencia-mastered.mp3`);
    rawEl.preload = "auto";
    mastEl.preload = "auto";
    rawEl.loop = true;
    mastEl.loop = true;
    rawEl.crossOrigin = "anonymous";
    mastEl.crossOrigin = "anonymous";

    const rawSrc = ctx.createMediaElementSource(rawEl);
    const mastSrc = ctx.createMediaElementSource(mastEl);
    const rawGain = ctx.createGain();
    const mastGain = ctx.createGain();

    rawGain.gain.value = 0;
    mastGain.gain.value = 1;

    rawSrc.connect(rawGain);
    mastSrc.connect(mastGain);
    rawGain.connect(ctx.destination);
    mastGain.connect(ctx.destination);

    const graph: RealAudioGraph = { ctx, rawEl, mastEl, rawGain, mastGain };
    audioRef.current = graph;
    return graph;
  }, []);

  const startAudio = useCallback(async () => {
    try {
      const graph = ensureGraph();
      if (!graph) return;
      if (graph.ctx.state === "suspended") {
        await graph.ctx.resume();
      }
      // Keep both stems sample-aligned before starting playback
      if (Math.abs(graph.rawEl.currentTime - graph.mastEl.currentTime) > 0.03) {
        graph.rawEl.currentTime = graph.mastEl.currentTime;
      }
      applyMixGains();
      await Promise.all([graph.rawEl.play(), graph.mastEl.play()]);
      setIsPlaying(true);
    } catch {
      setIsPlaying(false);
    }
  }, [ensureGraph, applyMixGains]);

  const stopAudio = useCallback(() => {
    const graph = audioRef.current;
    if (!graph) return;
    graph.rawEl.pause();
    graph.mastEl.pause();
    setIsPlaying(false);
  }, []);

  const togglePlay = useCallback(() => {
    if (isPlaying) {
      stopAudio();
    } else {
      void startAudio();
    }
  }, [isPlaying, startAudio, stopAudio]);

  const handleSeek = useCallback((clientX: number, rect: DOMRect) => {
    if (rect.width <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const nextSec = ratio * CLIP_DURATION_SEC;
    playheadRef.current = ratio * 100;
    setCurrentTime(nextSec);
    const graph = audioRef.current;
    if (graph) {
      graph.rawEl.currentTime = nextSec;
      graph.mastEl.currentTime = nextSec;
    }
  }, []);

  useEffect(() => {
    stateRef.current.target = isBrik ? 1 : 0;
    applyMixGains();
  }, [isBrik, applyMixGains]);

  useEffect(() => {
    stateRef.current.playing = isPlaying;
  }, [isPlaying]);

  useEffect(() => {
    stateRef.current.intensity = intensity;
    applyMixGains();
  }, [intensity, applyMixGains]);

  useEffect(() => {
    return () => {
      const graph = audioRef.current;
      audioRef.current = null;
      if (graph) {
        try {
          graph.rawEl.pause();
          graph.mastEl.pause();
          void graph.ctx.close();
        } catch {
          // Already closed
        }
      }
    };
  }, []);

  // Keyboard shortcut: A = Crudo, B = Masterizado
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const el = event.target as HTMLElement | null;
      if (
        el &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.tagName === "SELECT" ||
          el.isContentEditable)
      ) {
        return;
      }
      if (event.key === "a" || event.key === "A") setIsBrik(false);
      else if (event.key === "b" || event.key === "B") setIsBrik(true);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  /* ── Canvas waveform + metric readouts ────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let frame = 0;
    let last = performance.now();
    let publishedMorph = 1;
    let lastTimeUpdate = 0;

    const step = (now: number) => {
      frame = requestAnimationFrame(step);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      const state = stateRef.current;
      const effectiveTarget = state.target === 1 ? state.intensity / 100 : 0;

      let morph = morphRef.current;
      if (state.reduced) {
        morph = effectiveTarget;
      } else {
        morph += (effectiveTarget - morph) * Math.min(1, dt * 6);
        if (Math.abs(effectiveTarget - morph) < 0.001) morph = effectiveTarget;
      }
      morphRef.current = morph;

      const graph = audioRef.current;
      if (graph && state.playing) {
        // Keep the two stems locked within 25ms
        if (Math.abs(graph.rawEl.currentTime - graph.mastEl.currentTime) > 0.025) {
          graph.rawEl.currentTime = graph.mastEl.currentTime;
        }
        const dur = graph.mastEl.duration || CLIP_DURATION_SEC;
        playheadRef.current = ((graph.mastEl.currentTime % dur) / dur) * 100;
        if (now - lastTimeUpdate > 200) {
          lastTimeUpdate = now;
          setCurrentTime(graph.mastEl.currentTime % dur);
        }
      }

      if (!state.reduced) {
        phaseRef.current += dt * (state.playing ? 3.2 : 0.6);
      }
      const phase = phaseRef.current;

      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (width === 0 || height === 0) return;
      const pixelsW = Math.round(width * dpr);
      const pixelsH = Math.round(height * dpr);
      if (canvas.width !== pixelsW || canvas.height !== pixelsH) {
        canvas.width = pixelsW;
        canvas.height = pixelsH;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const cy = height / 2;
      const maxHalf = height / 2 - 4;
      const barStep = width / BAR_COUNT;
      const barW = Math.max(1, barStep * 0.62);
      const playheadIndex = (playheadRef.current / 100) * BAR_COUNT;

      if (morph > 0.15) {
        const ceiling = cy - maxHalf * 0.92;
        ctx.strokeStyle = `rgba(110, 233, 224, ${(0.22 * morph).toFixed(3)})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, ceiling);
        ctx.lineTo(width, ceiling);
        ctx.moveTo(0, height - ceiling);
        ctx.lineTo(width, height - ceiling);
        ctx.stroke();
      }

      const cr = Math.round(lerp(RAW_COLOR[0], MASTER_COLOR[0], morph));
      const cg = Math.round(lerp(RAW_COLOR[1], MASTER_COLOR[1], morph));
      const cb = Math.round(lerp(RAW_COLOR[2], MASTER_COLOR[2], morph));

      for (let i = 0; i < BAR_COUNT; i++) {
        let amp = lerp(RAW_BARS[i], MAST_BARS[i], morph);
        if (!state.reduced && state.playing) {
          amp *= 1 + Math.sin(phase + i * 0.35) * 0.08;
        }
        amp = Math.max(0.05, Math.min(1, amp));
        const half = amp * maxHalf;
        const x = i * barStep + (barStep - barW) / 2;
        const passed = i <= playheadIndex;
        const alpha = passed ? 0.55 + amp * 0.4 : 0.25 + amp * 0.35;
        ctx.fillStyle = `rgba(${cr}, ${cg}, ${cb}, ${alpha.toFixed(3)})`;
        ctx.fillRect(x, cy - half, barW, half * 2);
      }

      if (state.playing || playheadRef.current > 0) {
        const px = (playheadRef.current / 100) * width;
        ctx.save();
        ctx.shadowColor = "rgba(110, 233, 224, 0.9)";
        ctx.shadowBlur = 8;
        ctx.fillStyle = "#6ee9e0";
        ctx.fillRect(px - 0.75, 0, 1.5, height);
        ctx.restore();
      }

      if (Math.abs(morph - publishedMorph) > 0.001) {
        publishedMorph = morph;
        const next = {} as Record<ABMetricId, number>;
        for (const metric of AB_METRICS) {
          next[metric.id] = lerp(metric.original, metric.mastered, morph);
        }
        setMetrics(next);
      }
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, []);

  const toggleBase =
    "min-h-[44px] flex-1 px-4 rounded-full font-label-technical text-xs font-bold transition-all cursor-pointer touch-manipulation active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-primary/70";

  return (
    <Reveal as="section" id="comparador" className="relative w-full bg-[var(--bg-app)] px-4 py-24 sm:px-8 lg:px-12 lg:py-32">
      <div className="mx-auto flex max-w-3xl flex-col gap-10">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="font-label-technical text-[10px] uppercase tracking-widest text-primary">
            {t("landing.abPlayer.badge", "Comparador A/B")}
          </span>
          <h2 className="font-headline-lg text-3xl font-bold text-[var(--text-primary)] sm:text-4xl lg:text-5xl">
            {t("landing.abPlayer.title", "Escucha la diferencia")}
          </h2>
          <p className="max-w-xl text-sm leading-relaxed text-[var(--text-secondary)] sm:text-base">
            {t(
              "landing.abPlayer.subtitle",
              "Alterna entre el audio crudo y el masterizado. Mismo material, mismo momento."
            )}
          </p>
        </div>

        <div className="flex flex-col gap-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-glass-elevated)] p-4 sm:p-6">
          {/* Track + play + Raw/Mastered toggle */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={togglePlay}
                className="flex h-12 w-12 shrink-0 cursor-pointer touch-manipulation items-center justify-center rounded-full bg-primary text-[var(--color-on-primary)] transition-all hover:bg-primary-container active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-primary/70"
                aria-label={isPlaying ? t("landing.abPlayer.pauseAria", "Pausar") : t("landing.abPlayer.playAria", "Reproducir")}
                aria-pressed={isPlaying}
              >
                {isPlaying ? <Pause className="h-5 w-5 fill-current" /> : <Play className="ml-0.5 h-5 w-5 fill-current" />}
              </button>
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-semibold text-[var(--text-primary)] sm:text-base">
                  {t("landing.abPlayer.trackTitle", "RESILIENCIA (Extracto 40s)")}
                </span>
                <span className="font-label-technical truncate text-[10px] text-[var(--text-muted)] tabular-nums">
                  {formatTime(currentTime)} / 0:40 · {t("landing.abPlayer.trackMeta", "44.1 KHZ · 24-BIT · CRUDO VS MASTER BRIK")}
                </span>
              </div>
            </div>

            <div
              role="group"
              aria-label={t("landing.abPlayer.toggleAria", "Modo de comparación: crudo o masterizado")}
              className="grid w-full grid-cols-2 gap-1 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-active)] p-1 sm:w-auto sm:min-w-[260px]"
            >
              <button
                type="button"
                onClick={() => setIsBrik(false)}
                aria-pressed={!isBrik}
                aria-keyshortcuts="a"
                className={`${toggleBase} ${
                  !isBrik
                    ? "border border-[var(--border-strong)] bg-[var(--bg-glass-elevated)] text-[var(--text-primary)] shadow-md"
                    : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                {t("landing.abPlayer.btnOrig", "Crudo")}
              </button>
              <button
                type="button"
                onClick={() => setIsBrik(true)}
                aria-pressed={isBrik}
                aria-keyshortcuts="b"
                className={`${toggleBase} ${
                  isBrik
                    ? "bg-primary text-[var(--color-on-primary)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                {t("landing.abPlayer.btnBrik", "Masterizado")}
              </button>
            </div>
          </div>

          {/* Compact seekable waveform */}
          <div
            className="relative h-16 w-full cursor-pointer overflow-hidden rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-app)] sm:h-20"
            onClick={(e) => handleSeek(e.clientX, e.currentTarget.getBoundingClientRect())}
          >
            <canvas
              ref={canvasRef}
              role="img"
              aria-label={t("landing.abPlayer.vizAria", "Onda que reacciona al comparador A/B")}
              className="absolute inset-0 block h-full w-full"
            />
            <div className="pointer-events-none absolute inset-x-3 top-2 flex items-center justify-between gap-3 text-[9px] font-label-technical sm:text-[10px]">
              <span className="shrink-0 font-bold text-primary">{t("landing.abPlayer.vizLabel", "ONDA — CRUDO VS MASTER")}</span>
              <span
                className={`truncate text-right uppercase tracking-wider transition-colors duration-500 ${
                  isBrik ? "text-primary" : "text-[var(--text-muted)]"
                }`}
              >
                {isBrik ? t("landing.abPlayer.statusBrik") : t("landing.abPlayer.statusOrig")}
              </span>
            </div>
          </div>

          {/* Active processes: lit in Mastered, dimmed in Raw */}
          <div className="flex flex-col gap-2">
            <span className="font-label-technical text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
              {t("landing.abPlayer.processesTitle", "Procesos activos")}
            </span>
            <ul className="flex flex-wrap gap-2">
              {PROCESS_KEYS.map((key) => (
                <li
                  key={key}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-all duration-500 ${
                    isBrik
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-[var(--border-subtle)] text-[var(--text-muted)] opacity-50"
                  }`}
                >
                  {t(`landing.abPlayer.processes.${key}`)}
                </li>
              ))}
            </ul>
          </div>

          {/* Intensity */}
          <div className="flex items-center gap-3">
            <span className="font-label-technical shrink-0 text-[10px] uppercase text-[var(--text-muted)]">
              {t("landing.abPlayer.intensityLabel", "INTENSIDAD:")}
            </span>
            <Fader
              value={intensity}
              onChange={setIntensity}
              ariaLabel={t("landing.abPlayer.intensityAria", "Intensidad del procesamiento")}
            />
            <span className="font-label-technical w-10 shrink-0 text-right text-xs font-bold tabular-nums text-primary">
              {intensity}%
            </span>
          </div>

          {/* Metrics */}
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            {AB_METRICS.map((metric) => (
              <MetricCard
                key={metric.id}
                metric={metric}
                value={metrics[metric.id]}
                label={t(`landing.abPlayer.${metric.labelKey}`)}
                unit={t(`landing.abPlayer.${metric.unitKey}`)}
              />
            ))}
          </div>

          <p className="font-label-technical text-center text-[10px] leading-relaxed text-[var(--text-muted)]">
            {t(
              "landing.abPlayer.demoNote",
              "Extracto real de 40 s de RESILIENCIA: compara la mezcla cruda (-18.5 LUFS) frente al master procesado por Brik (-14.0 LUFS)."
            )}
          </p>
        </div>
      </div>
    </Reveal>
  );
}
