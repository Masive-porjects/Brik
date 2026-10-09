"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import { useTranslation } from "@/i18n";
import { AB_METRICS } from "./data";
import Reveal from "./Reveal";
import type { ABMetricDefinition, ABMetricId, AccentToken } from "./types";

/* ─────────────────────────────────────────────────────────────────────────
   Waveform model

   The waveform is drawn on a canvas, not in the DOM: it repaints every frame,
   and reconciling ~96 React nodes per frame would burn the frame budget on
   mobile. The two states are deliberately different shapes, not a recolor:

   • Original (bypass): mostly short bars with occasional tall dynamic peaks —
     high crest factor, uneven, "uncontrolled".
   • Mastered: dense, full bars locked under a limiter ceiling — louder and
     glued, with the peaks compressed into a consistent block.

   A single `morph` value (0 = Original, 1 = Mastered) blends both the shape
   and the color, so toggling A/B produces one continuous, fluid transition.
   ───────────────────────────────────────────────────────────────────────── */

const BAR_COUNT = 96;

/**
 * Deterministic per-bar seeds. A fixed table (never `Math.random`) keeps the
 * waveform stable across renders and lets both profiles share the same
 * "performance" while reading completely differently.
 */
const BAR_SEEDS = Array.from({ length: BAR_COUNT }, (_, i) => {
  const s = Math.sin(i * 12.9898) * 43758.5453;
  return s - Math.floor(s);
});

/** Original: low average with occasional tall dynamic peaks. */
function originalAmp(seed: number): number {
  return Math.min(1, 0.16 + Math.pow(seed, 2.2));
}

/** Mastered: dense, full bars pinned under a controlled ceiling. */
function masteredAmp(seed: number): number {
  return 0.6 + Math.min(0.3, seed * 0.3);
}

const ORIG_COLOR: readonly [number, number, number] = [134, 147, 145];
const MASTER_COLOR: readonly [number, number, number] = [110, 233, 224];

const ACCENTS: Record<AccentToken, { text: string; bg: string }> = {
  primary: { text: "text-primary", bg: "bg-primary" },
  secondary: { text: "text-secondary", bg: "bg-secondary" },
  tertiary: { text: "text-tertiary-container", bg: "bg-tertiary-container" },
};

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
    <div className="p-2.5 sm:p-4 bg-[#1f1f24] rounded-lg border border-white/5 flex flex-col gap-1.5">
      <span className="font-label-technical text-[9px] sm:text-[10px] leading-tight text-[#869391]">
        {label}
      </span>
      <div className="flex items-baseline justify-between gap-1">
        <span className={`font-metric-val-lg text-base sm:text-2xl font-bold tabular-nums ${accent.text}`}>
          {value.toFixed(metric.decimals)}
        </span>
        <span className={`font-label-technical text-[9px] sm:text-xs ${accent.text}`}>{unit}</span>
      </div>
      <div className="w-full bg-[#343439] h-1.5 rounded-full overflow-hidden">
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
 * Thumb-friendly fader.
 *
 * A native range input is small and lets mobile browsers scroll the page while
 * dragging. This is a 44px-tall slider with `touch-action: none` and pointer
 * capture, so a thumb drag controls the value and never scrolls the page.
 * Keyboard users get the usual slider keys.
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
      className="relative flex h-11 w-28 sm:w-40 touch-none select-none items-center rounded-full cursor-pointer focus-visible:ring-2 focus-visible:ring-primary/70"
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
      <div className="absolute inset-x-0 h-1.5 rounded-full bg-[#343439]" />
      <div className="absolute left-0 h-1.5 rounded-full bg-primary" style={{ width: `${value}%` }} />
      <div
        className="absolute h-5 w-5 -translate-x-1/2 rounded-full border-2 border-primary bg-[#1a1b20] shadow-[0_0_0_2px_rgba(0,0,0,0.4),0_0_10px_rgba(110,233,224,0.35)]"
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

  /* ── Keep the animation ref in sync with React state ──────────────── */
  useEffect(() => {
    stateRef.current.reduced = prefersReduced;
  }, [prefersReduced]);

  /* ── Local synthetic audio (Oscillator → BiquadFilter → gain) ─────── */
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

  // A/B changes retune the live drone without restarting it.
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

  // Keyboard shortcut: A = Original, B = Mastered.
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
      const maxHalf = height / 2 - 6;
      const barStep = width / BAR_COUNT;
      const barW = Math.max(1, barStep * 0.62);
      const idleScale = state.playing ? 1 : 0.62;

      // Fade in the limiter ceiling only as we approach the Mastered state.
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

      const cr = Math.round(lerp(ORIG_COLOR[0], MASTER_COLOR[0], morph));
      const cg = Math.round(lerp(ORIG_COLOR[1], MASTER_COLOR[1], morph));
      const cb = Math.round(lerp(ORIG_COLOR[2], MASTER_COLOR[2], morph));

      for (let i = 0; i < BAR_COUNT; i++) {
        const seed = BAR_SEEDS[i];
        let amp = lerp(originalAmp(seed), masteredAmp(seed), morph) * idleScale;
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

  return (
    <Reveal as="section" className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#121317] relative" id="comparador">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <div className="flex flex-col items-center text-center gap-2 max-w-3xl mx-auto">
          <span className="font-label-technical text-secondary text-[10px] uppercase tracking-widest">
            {t("landing.abPlayer.badge")}
          </span>
          <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
            {t("landing.abPlayer.title")}
          </h2>
          <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
            {t("landing.abPlayer.subtitle")}
          </p>
        </div>

        {/* Interactive Audio Widget Shell */}
        <div className="w-full bg-[#1a1b20] rounded-2xl p-4 sm:p-8 lg:p-10 shadow-2xl border border-white/5 flex flex-col gap-6">
          {/* Control Bar */}
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between pb-6 border-b border-white/10">
            {/* Track Info & Play */}
            <div className="flex items-center gap-3.5 min-w-0">
              <button
                type="button"
                onClick={togglePlay}
                className="shrink-0 w-12 h-12 min-h-[44px] rounded-full bg-primary text-[#003734] flex items-center justify-center hover:bg-primary-container transition-all shadow-[0_0_18px_rgba(110,233,224,0.35)] hover:scale-105 active:scale-[0.98] cursor-pointer touch-manipulation focus-visible:ring-2 focus-visible:ring-primary/70"
                aria-label={isPlaying ? t("landing.abPlayer.pauseAria") : t("landing.abPlayer.playAria")}
              >
                {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current ml-0.5" />}
              </button>
              <div className="flex flex-col min-w-0">
                <span className="font-headline-sm text-sm sm:text-base font-semibold text-[#e3e2e8] truncate">
                  {t("landing.abPlayer.trackTitle")}
                </span>
                <span className="font-label-technical text-[10px] text-[#869391] truncate">
                  {t("landing.abPlayer.trackMeta")}
                </span>
              </div>
            </div>

            {/* Intensity & A/B Switchers */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-4">
              {/* DSP Intensity Fader */}
              <div className="flex items-center gap-3 bg-[#1f1f24] px-4 rounded-full border border-white/5">
                <span className="font-label-technical text-[10px] text-[#869391] uppercase shrink-0">
                  {t("landing.abPlayer.intensityLabel")}
                </span>
                <Fader
                  value={intensity}
                  onChange={setIntensity}
                  ariaLabel={t("landing.abPlayer.intensityAria")}
                />
                <span className="font-label-technical text-xs text-primary font-bold w-9 text-right tabular-nums">
                  {intensity}%
                </span>
              </div>

              {/* A/B Switch Pills */}
              <div
                role="group"
                aria-label={t("landing.abPlayer.toggleAria")}
                className="grid grid-cols-2 gap-1 p-1 bg-[#292a2e] rounded-full border border-white/5 shadow-inner w-full sm:w-auto"
              >
                <button
                  type="button"
                  onClick={() => setIsBrik(false)}
                  aria-pressed={!isBrik}
                  aria-keyshortcuts="a"
                  className={`min-h-[44px] px-4 rounded-full font-label-technical text-xs font-bold transition-all cursor-pointer touch-manipulation active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-primary/70 ${
                    !isBrik
                      ? "bg-[#38393e] text-[#e3e2e8] shadow-md border border-white/10"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.abPlayer.btnOrig")}
                </button>
                <button
                  type="button"
                  onClick={() => setIsBrik(true)}
                  aria-pressed={isBrik}
                  aria-keyshortcuts="b"
                  className={`min-h-[44px] px-4 rounded-full font-label-technical text-xs font-bold transition-all cursor-pointer touch-manipulation active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-primary/70 ${
                    isBrik
                      ? "bg-primary text-[#003734] shadow-[0_0_12px_rgba(110,233,224,0.35)]"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.abPlayer.btnBrik")}
                </button>
              </div>
            </div>
          </div>

          {/* Waveform Canvas */}
          <div className="relative w-full h-48 sm:h-56 bg-[#0d0e12] rounded-xl overflow-hidden border border-white/5">
            <canvas
              ref={canvasRef}
              role="img"
              aria-label={t("landing.abPlayer.vizAria")}
              className="absolute inset-0 w-full h-full block"
            />
            <div className="absolute top-3 left-4 right-4 flex items-center justify-between gap-3 text-[10px] font-label-technical pointer-events-none">
              <span className="text-primary font-bold shrink-0">{t("landing.abPlayer.vizLabel")}</span>
              <span
                className={`uppercase tracking-wider text-right truncate transition-colors duration-500 ${
                  isBrik ? "text-primary" : "text-[#869391]"
                }`}
              >
                {isBrik ? t("landing.abPlayer.statusBrik") : t("landing.abPlayer.statusOrig")}
              </span>
            </div>
            <div className="absolute bottom-2 left-4 right-4 flex items-center justify-between text-[#869391] font-label-technical text-[10px] pointer-events-none">
              <span>20 Hz</span>
              <span className="hidden sm:inline">100 Hz</span>
              <span>1 kHz</span>
              <span className="hidden sm:inline">5 kHz</span>
              <span>12 kHz</span>
              <span>20 kHz</span>
            </div>
          </div>

          {/* Realtime Metrics Grid */}
          <div className="grid grid-cols-3 gap-2 sm:gap-4">
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

          {/* Honest demo disclaimer */}
          <p className="font-label-technical text-[10px] leading-relaxed text-[#869391] text-center">
            {t("landing.abPlayer.demoNote")}
          </p>
        </div>
      </div>
    </Reveal>
  );
}
