"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  Play, Pause, Loader2, CheckCircle2, Mic2,
} from "lucide-react";
import { API_BASE } from "@/adapters/api/config";
import { useTranslation } from "@/i18n";

/* ── Types ───────────────────────────────────────────── */

export interface VocalParams {
  deesser_amount: number;     // 0.0 - 1.0
  pitch_shift_semitones: number; // -3.0 - +3.0
  cohesion_amount: number;    // 0.0 - 1.0
}

export const DEFAULT_VOCAL_PARAMS: VocalParams = {
  deesser_amount: 0.3,
  pitch_shift_semitones: 0.0,
  cohesion_amount: 0.4,
};

/* ── 3D Knob (big, improved version) ─────────────────── */

function VocalKnob({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  disabled,
  accent,
  size = 72,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (v: number) => void;
  disabled?: boolean;
  accent?: string;
  size?: number;
}) {
  const dotColor = accent ?? "var(--accent-primary)";
  const pct = (value - min) / (max - min);
  const angle = -135 + pct * 270;
  const range = max - min;
  const sensitivity = 300;

  const dragRef = useRef({ startY: 0, startVal: 0, dragging: false });

  const handleMouseDown = (e: React.MouseEvent) => {
    if (disabled) return;
    e.preventDefault();
    const d = dragRef.current;
    d.startY = e.clientY;
    d.startVal = value;
    d.dragging = true;

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragRef.current.dragging) return;
      const deltaY = dragRef.current.startY - ev.clientY;
      const deltaVal = (deltaY / sensitivity) * range;
      let newVal = Math.round((dragRef.current.startVal + deltaVal) / step) * step;
      newVal = Math.max(min, Math.min(max, newVal));
      onChange(newVal);
    };

    const onMouseUp = () => {
      dragRef.current.dragging = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className={`relative select-none ${
          disabled ? "opacity-30 pointer-events-none" : "cursor-grab active:cursor-grabbing"
        }`}
        style={{ width: size, height: size }}
        onMouseDown={handleMouseDown}
      >
        {/* Outer ring — larger, more metallic */}
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background: "radial-gradient(circle at 35% 28%, var(--knob-gradient-5), var(--knob-gradient-6) 35%, var(--knob-gradient-7) 60%, var(--knob-gradient-8) 100%)",
            boxShadow: "var(--shadow-knob-inset), 0 0 0 1.5px var(--border-subtle), 0 4px 12px rgba(0,0,0,0.5)",
            border: "1px solid rgba(0,0,0,0.4)",
          }}
        />
        {/* Highlight rim */}
        <div
          className="absolute inset-[3px] rounded-full pointer-events-none"
          style={{
            background: "radial-gradient(circle at 28% 22%, var(--knob-highlight), transparent 55%)",
          }}
        />
        {/* Center dimple */}
        <div
          className="absolute inset-[38%] rounded-full pointer-events-none"
          style={{
            background: "radial-gradient(circle, var(--knob-gradient-6), var(--knob-face-bottom))",
            boxShadow: "inset 0 1.5px 3px rgba(0,0,0,0.6)",
          }}
        />
        {/* LED indicator with glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            transform: `rotate(${angle}deg)`,
            transition: "transform 0.06s ease-out",
          }}
        >
          <div
            className="absolute left-1/2 -translate-x-1/2 rounded-full"
            style={{
              top: "4px",
              width: "5px",
              height: "5px",
              background: dotColor,
              boxShadow: `0 0 8px ${dotColor}`,
            }}
          />
        </div>
      </div>

      <span className="text-xs text-[var(--text-secondary)] font-medium tracking-wide">{label}</span>
      <span className="text-[10px] font-mono text-[var(--text-muted)] tabular-nums leading-none">
        {step < 1 && step !== 1 ? value.toFixed(1) : value.toFixed(0)}
        {unit && <span className="text-[var(--text-muted)] ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────── */

interface VocalChainProps {
  sessionId: string | null;
  disabled?: boolean;
  onProcess: (params: VocalParams) => Promise<void>;
  processed: boolean;
  processing: boolean;
}

export default function VocalChain({
  sessionId,
  disabled,
  onProcess,
  processed,
  processing,
}: VocalChainProps) {
  const { t } = useTranslation();
  const [params, setParams] = useState<VocalParams>(DEFAULT_VOCAL_PARAMS);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // The vocal endpoint doesn't serve via /stem, but via /vocal/audio
  const vocalAudioUrl = sessionId
    ? `${API_BASE}/session/${sessionId}/vocal/audio`
    : null;

  // Play/pause the processed vocal
  const togglePlay = useCallback(() => {
    if (!vocalAudioUrl) return;
    if (!audioRef.current) {
      audioRef.current = new Audio(vocalAudioUrl);
      audioRef.current.onended = () => setPlaying(false);
    }
    const a = audioRef.current;
    if (playing) { a.pause(); setPlaying(false); }
    else {
      a.currentTime = 0;
      a.play().then(() => setPlaying(true)).catch(() => {});
    }
  }, [vocalAudioUrl, playing]);

  // Cleanup
  useEffect(() => {
    return () => { audioRef.current?.pause(); };
  }, []);

  const handleProcess = useCallback(async () => {
    await onProcess(params);
  }, [params, onProcess]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-primary)]" style={{ letterSpacing: "-0.02em" }}>
            VoiceChain <span className="serif-accent">Pro</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {t("vocal.subtitle", "Cadena de efectos vocales profesional")}
          </p>
        </div>
        <button
          onClick={handleProcess}
          disabled={disabled || processing || !sessionId}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
          style={{
            background: processed
              ? "rgba(48, 209, 88, 0.12)"
              : "linear-gradient(135deg, rgba(98,126,132,0.15), rgba(98,126,132,0.06))",
            border: `1px solid ${
              processed ? "rgba(48, 209, 88, 0.2)" : "rgba(255,59,48,0.2)"
            }`,
            color: processed ? "#30d158" : "var(--accent-primary)",
          }}
        >
          {processing ? (
            <><Loader2 size={16} className="animate-spin" /> {t("common.processing", "Procesando...")}</>
          ) : processed ? (
            <><CheckCircle2 size={16} /> {t("common.success", "Procesado")}</>
          ) : (
            <><Mic2 size={16} /> {t("vocal.processVoice", "Procesar Voz")}</>
          )}
        </button>
      </div>

      {/* Vintage Rack — 3 large knobs */}
      <div
        className="rounded-2xl p-6 md:p-8"
        style={{
          background: "linear-gradient(180deg, var(--bg-tertiary), var(--bg-secondary))",
          border: "1px solid var(--border-subtle)",
          boxShadow: "inset 0 1px 0 var(--border-subtle), var(--shadow-card)",
        }}
      >
        {/* Rack ear / branding */}
        <div className="flex items-center justify-center mb-6">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-[var(--accent-primary)] shadow-lg shadow-[rgba(98,126,132,0.3)]" />
            <span className="text-[10px] font-semibold text-[var(--text-muted)] tracking-[0.2em] uppercase">
              {t("vocal.channelStrip", "VoiceChain Pro — Channel Strip")}
            </span>
            <div className="w-2 h-2 rounded-full bg-[var(--accent-secondary)] shadow-lg shadow-[rgba(130,156,161,0.3)]" />
          </div>
        </div>

        {/* 3-Knob grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-12 items-start justify-items-center">
          {/* De-Esser */}
          <div className="flex flex-col items-center gap-3">
            <VocalKnob
              label={t("vocal.deesser", "De-Esser")}
              value={params.deesser_amount}
              min={0}
              max={1}
              step={0.05}
              unit="%"
              onChange={(v) => setParams({ ...params, deesser_amount: v })}
              disabled={disabled}
              accent="#ff9f0a"
              size={80}
            />
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[9px] text-[var(--text-muted)]">0%</span>
              <div className="w-24 h-1 rounded-full bg-[var(--border-subtle)] relative">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${params.deesser_amount * 100}%`,
                    background: "linear-gradient(90deg, rgba(255,159,10,0.4), #ff9f0a)",
                  }}
                />
              </div>
              <span className="text-[9px] text-[var(--text-muted)]">100%</span>
            </div>
            <p className="text-[10px] text-[var(--text-muted)] text-center leading-relaxed max-w-[160px]">
              {t("vocal.deesserDesc", "Reduce sibilancias en frecuencias agudas (5-8 kHz)")}
            </p>
          </div>

          {/* Auto-Tune Pitch */}
          <div className="flex flex-col items-center gap-3">
            <VocalKnob
              label={t("vocal.pitch", "Auto-Tune Pitch")}
              value={params.pitch_shift_semitones}
              min={-3}
              max={3}
              step={0.5}
              unit="st"
              onChange={(v) => setParams({ ...params, pitch_shift_semitones: v })}
              disabled={disabled}
              accent="#627e84"
              size={92}
            />
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[9px] text-[var(--text-muted)]">-3</span>
              <div className="w-24 h-1 rounded-full bg-[var(--border-subtle)] relative">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${((params.pitch_shift_semitones + 3) / 6) * 100}%`,
                    background: params.pitch_shift_semitones > 0
                      ? "linear-gradient(90deg, rgba(98,126,132,0.4), #627e84)"
                      : params.pitch_shift_semitones < 0
                      ? "linear-gradient(90deg, #5e5ce6, rgba(94,92,230,0.4))"
                      : "var(--border-subtle)",
                  }}
                />
              </div>
              <span className="text-[9px] text-[var(--text-muted)]">+3</span>
            </div>
            <p className="text-[10px] text-[var(--text-muted)] text-center leading-relaxed max-w-[160px]">
              {t("vocal.pitchDesc", "Corrección tonal con preservación de formantes.")} {params.pitch_shift_semitones > 0 ? t("vocal.pitchHigh", "↑ Agudo") : params.pitch_shift_semitones < 0 ? t("vocal.pitchLow", "↓ Grave") : t("vocal.pitchNeutral", "Neutral")}
            </p>
          </div>

          {/* Cohesion */}
          <div className="flex flex-col items-center gap-3">
            <VocalKnob
              label={t("vocal.cohesion", "Cohesión")}
              value={params.cohesion_amount}
              min={0}
              max={1}
              step={0.05}
              unit="%"
              onChange={(v) => setParams({ ...params, cohesion_amount: v })}
              disabled={disabled}
              accent="#30d158"
              size={80}
            />
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[9px] text-[var(--text-muted)]">0%</span>
              <div className="w-24 h-1 rounded-full bg-[var(--border-subtle)] relative">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${params.cohesion_amount * 100}%`,
                    background: "linear-gradient(90deg, rgba(48,209,88,0.4), #30d158)",
                  }}
                />
              </div>
              <span className="text-[9px] text-[var(--text-muted)]">100%</span>
            </div>
            <p className="text-[10px] text-[var(--text-muted)] text-center leading-relaxed max-w-[160px]">
              {t("vocal.cohesionDesc", "Compresor óptico analógico. Controla picos dinámicos y adelanta la presencia vocal.")}
            </p>
          </div>
        </div>

        {/* Chain order indicator */}
        <div className="flex items-center justify-center gap-3 mt-6 pt-4 border-t border-[var(--border-subtle)]">
          <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{t("vocal.deesser", "De-Esser")}</span>
          <div className="w-4 h-px bg-[var(--border-hover)]" />
          <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{t("vocal.pitch", "Pitch")}</span>
          <div className="w-4 h-px bg-[var(--border-hover)]" />
          <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">{t("vocal.compressor", "Compresor")}</span>
        </div>
      </div>

      {/* Processed audio player */}
      {processed && vocalAudioUrl && (
        <div className="rounded-2xl p-4 flex items-center gap-4" style={{ background: "rgba(48,209,88,0.04)", border: "1px solid rgba(48,209,88,0.1)" }}>
          <button
            onClick={togglePlay}
            className="w-10 h-10 rounded-xl flex items-center justify-center bg-[rgba(48,209,88,0.12)] text-[#30d158] hover:brightness-110 transition-all"
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-[var(--text-primary)] font-medium">{t("vocal.processedVoice", "Voz Procesada")}</p>
            <p className="text-xs text-[var(--text-muted)]">
              {playing ? t("vocal.playingPrompt", "Reproduciendo...") : t("vocal.playPrompt", "Presioná Play para escuchar el resultado")}
            </p>
          </div>
          <a
            href={vocalAudioUrl}
            download
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--surface-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)] transition-all"
          >
            {t("splitter.downloadWav", "Descargar WAV")}
          </a>
        </div>
      )}

      {/* Status */}
      {!processed && !processing && (
        <p className="text-xs text-[var(--text-muted)] text-center">
          {t("vocal.adjustPrompt", "Ajusta los 3 controles y presiona \"Procesar Voz\" para aplicar la cadena vocal.")}
        </p>
      )}
      {processing && (
        <div className="flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin text-[var(--accent-primary)]" />
          <span className="text-xs text-[var(--text-secondary)]">{t("vocal.applyingChain", "Aplicando cadena vocal...")}</span>
        </div>
      )}
    </div>
  );
}
