"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import { useTranslation } from "@/i18n";
import { AB_METRICS } from "./data";
import Reveal from "./Reveal";
import type { ABMetricDefinition, ABMetricId, AccentToken } from "./types";

/* ─────────────────────────────────────────────────────────────────────────
   Demo model

   The comparator is a synthetic, illustrative demo: a local drone whose
   filter opens up when "Raw" is selected and closes under "Mastered". The
   waveform is drawn on a small canvas and morphs between two shapes:

   • Raw: low average with occasional tall peaks (uncontrolled).
   • Mastered: dense bars pinned under a limiter ceiling (controlled).

   It does not process or measure the user's file.
   ───────────────────────────────────────────────────────────────────────── */

const BAR_COUNT = 96;

/** Deterministic per-bar seeds (never Math.random) so renders stay stable. */
const BAR_SEEDS = Array.from({ length: BAR_COUNT }, (_, i) => {
  const s = Math.sin(i * 12.9898) * 43758.5453;
  return s - Math.floor(s);
});

/** Raw: low average with occasional tall dynamic peaks. */
function rawAmp(seed: number): number {
  return Math.min(1, 0.16 + Math.pow(seed, 2.2));
}

/** Mastered: dense, full bars pinned under a controlled ceiling. */
function masteredAmp(seed: number): number {
  return 0.6 + Math.min(0.3, seed * 0.3);
}

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

function masteredMetrics(): Record<ABMetricId, number> {
  const out = {} as Record<ABMetricId, number>;
  for (const metric of AB_METRICS) out[metric.id] = metric.mastered;
  return out;
}

/** Normalize a metric value into the 0–1 display scale used by the fill bar. */
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

/**
 * Thumb-friendly fader: 44px tall, `touch-action: none`, pointer capture, so a
 * drag controls the value without scrolling the page. Keyboard keys supported.
 */
function Fader({ value, onChange, ariaLabel }: FaderProps) {
  const trackRef = useRef<HTMLDivElement>(null);

  const updateFromX = useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
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
        updateFromX(event.clientX);
      }}
      onPointerMove={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) updateFromX(event.clientX);
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
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

interface AudioGraph {
  ctx: AudioContext;
  osc: OscillatorNode;
  sub: OscillatorNode;
  filter: BiquadFilterNode;
  gain: GainNode;
}

export default function LandingABPlayer() {
  const { t } = useTranslation();
  const prefersReduced = useReducedMotion() ?? false;

  const [isBrik, setIsBrik] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);
  const [intensity, setIntensity] = useState(70);
  const [metrics, setMetrics] = useState<Record<ABMetricId, number>>(masteredMetrics);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioRef = useRef<AudioGraph | null>(null);

  /** Animation state shared with the canvas loop (kept in a ref, not state). */
  const stateRef = useRef({ target: 1, playing: false, reduced: false, intensity: 70 });
  const morphRef = useRef(1);
  const phaseRef = useRef(0);
  const playheadRef = useRef(33);

  useEffect(() => {
    stateRef.current.reduced = prefersReduced;
  }, [prefersReduced]);

  /* ── Local synthetic drone (Oscillator → BiquadFilter → Gain) ─────── */
  const applyTone = useCallback(() => {
    const graph = audioRef.current;
    if (!graph) return;
    const { target, intensity: level } = stateRef.current;
    const now = graph.ctx.currentTime;
    // `setTargetAtTime` avoids zipper noise on every parameter change.
    graph.filter.frequency.setTargetAtTime(target === 1 ? 2400 : 700, now, 0.05);
    graph.gain.gain.setTargetAtTime(0.01 * (level / 100), now, 0.05);
  }, []);

  const startAudio = useCallback(() => {
    try {
      if (typeof window === "undefined") return;
      type AudioContextCtor = typeof AudioContext;
      const Ctor: AudioContextCtor | undefined =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
      if (!Ctor) return;

      let graph = audioRef.current;
      if (!graph) {
        const ctx = new Ctor();
        const filter = ctx.createBiquadFilter();
        filter.type = "lowpass";
        filter.Q.value = 0.7;

        const gain = ctx.createGain();
        gain.gain.value = 0;

        const osc = ctx.createOscillator();
        osc.type = "sawtooth";
        osc.frequency.value = 110;

        const sub = ctx.createOscillator();
        sub.type = "sine";
        sub.frequency.value = 55;
        const subGain = ctx.createGain();
        subGain.gain.value = 0.6;

        osc.connect(filter);
        sub.connect(subGain);
        subGain.connect(filter);
        filter.connect(gain);
        gain.connect(ctx.destination);

        osc.start();
        sub.start();
        graph = { ctx, osc, sub, filter, gain };
        audioRef.current = graph;
      }

      if (graph.ctx.state === "suspended") void graph.ctx.resume();
      applyTone();
    } catch {
      // Autoplay restrictions / unavailable Web Audio: the visual demo still works.
    }
  }, [applyTone]);

  const stopAudio = useCallback(() => {
    const graph = audioRef.current;
    if (!graph) return;
    audioRef.current = null;
    try {
      const now = graph.ctx.currentTime;
      graph.gain.gain.cancelScheduledValues(now);
      graph.gain.gain.setTargetAtTime(0, now, 0.02);
      graph.osc.stop(now + 0.1);
      graph.sub.stop(now + 0.1);
      graph.osc.onended = () => {
        try {
          graph.osc.disconnect();
          graph.sub.disconnect();
          graph.filter.disconnect();
          graph.gain.disconnect();
        } catch {
          // Already detached.
        }
      };
    } catch {
      // Node already stopped.
    }
  }, []);

  const togglePlay = useCallback(() => {
    if (isPlaying) {
      stopAudio();
      setIsPlaying(false);
    } else {
      startAudio();
      setIsPlaying(true);
    }
  }, [isPlaying, startAudio, stopAudio]);

  // Raw/Mastered changes retune the live drone without restarting it.
  useEffect(() => {
    stateRef.current.target = isBrik ? 1 : 0;
    applyTone();
  }, [isBrik, applyTone]);

  useEffect(() => {
    stateRef.current.playing = isPlaying;
  }, [isPlaying]);

  useEffect(() => {
    stateRef.current.intensity = intensity;
    applyTone();
  }, [intensity, applyTone]);

  // Tear the audio graph down exactly once.
  useEffect(() => {
    return () => {
      const graph = audioRef.current;
      audioRef.current = null;
      if (graph) {
        try {
          graph.osc.stop();
          graph.sub.stop();
          void graph.ctx.close();
        } catch {
          // Already stopped.
        }
      }
    };
  }, []);

  // Keyboard shortcut: A = Raw, B = Mastered.
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

    const step = (now: number) => {
      frame = requestAnimationFrame(step);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      const state = stateRef.current;

      // Ease the morph toward the selected state (snap under reduced motion).
      let morph = morphRef.current;
      if (state.reduced) {
        morph = state.target;
      } else {
        morph += (state.target - morph) * Math.min(1, dt * 6);
        if (Math.abs(state.target - morph) < 0.001) morph = state.target;
      }
      morphRef.current = morph;

      // Ambient motion + moving playhead (disabled under reduced motion).
      if (!state.reduced) {
        phaseRef.current += dt * (state.playing ? 3.2 : 0.7);
        if (state.playing) {
          playheadRef.current = (playheadRef.current + dt * 9) % 100;
        }
      }
      const phase = phaseRef.current;

      // Measure in CSS pixels, cap DPR for crisp-but-cheap rendering.
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
      const idleScale = state.playing ? 1 : 0.62;

      // Limiter ceiling fades in only as we approach the Mastered state.
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
        const seed = BAR_SEEDS[i];
        let amp = lerp(rawAmp(seed), masteredAmp(seed), morph) * idleScale;
        if (!state.reduced) {
          amp *= 1 + Math.sin(phase + i * 0.35) * (state.playing ? 0.16 : 0.05);
        }
        amp = Math.max(0.04, Math.min(1, amp));
        const half = amp * maxHalf;
        const x = i * barStep + (barStep - barW) / 2;
        const alpha = 0.28 + amp * 0.55;
        ctx.fillStyle = `rgba(${cr}, ${cg}, ${cb}, ${alpha.toFixed(3)})`;
        ctx.fillRect(x, cy - half, barW, half * 2);
      }

      // Playhead glow while playing.
      if (!state.reduced && state.playing) {
        const px = (playheadRef.current / 100) * width;
        ctx.save();
        ctx.shadowColor = "rgba(207, 92, 255, 0.9)";
        ctx.shadowBlur = 8;
        ctx.fillStyle = "#cf5cff";
        ctx.fillRect(px - 0.75, 0, 1.5, height);
        ctx.restore();
      }

      // Publish animated readouts only while the value is actually moving.
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
                  {t("landing.abPlayer.trackTitle", "Demo: bass electrónico")}
                </span>
                <span className="font-label-technical truncate text-[10px] text-[var(--text-muted)]">
                  {t("landing.abPlayer.trackMeta", "DEMO SINTÉTICA — BASS ELECTRÓNICO — 128 BPM")}
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

          {/* Compact waveform */}
          <div className="relative h-16 w-full overflow-hidden rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-app)] sm:h-20">
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
              "Demo sintética para comparar el carácter del proceso. Las métricas son ilustrativas y no miden tu archivo."
            )}
          </p>
        </div>
      </div>
    </Reveal>
  );
}
