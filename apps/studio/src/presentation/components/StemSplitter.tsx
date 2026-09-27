"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  Mic2, Drum, Music, Waves,
  Play, Pause, Download, Loader2,
  Volume2, VolumeX, Headphones, CheckCircle2,
} from "lucide-react";
import WaveSurfer from "wavesurfer.js";
import { getStemUrl, type StemSplitResult } from "@/lib/api";
import { useTranslation } from "@/i18n";

/* ── Types ───────────────────────────────────────────── */

export type StemName = "vocals" | "drums" | "bass" | "other";

export interface StemInfo {
  name: StemName;
  label: string;
  icon: React.ComponentType<{ size?: number }>;
  color: string;
}

export const STEMS: StemInfo[] = [
  { name: "vocals", label: "Voz", icon: Mic2, color: "#ff3b30" },
  { name: "drums", label: "Batería", icon: Drum, color: "#ff9f0a" },
  { name: "bass", label: "Bajo", icon: Music, color: "#30d158" },
  { name: "other", label: "Melodías", icon: Waves, color: "#5e5ce6" },
];

export interface StemState {
  gain: number;
  mute: boolean;
  solo: boolean;
}

export interface StemSplitterState {
  enabled: boolean;
  stems: Record<StemName, StemState>;
  splitting: boolean;
  splitDone: boolean;
  result: StemSplitResult | null;
}

export function createDefaultStemState(): StemSplitterState {
  const stems = {} as Record<StemName, StemState>;
  for (const s of STEMS) stems[s.name] = { gain: 0, mute: false, solo: false };
  return { enabled: true, stems, splitting: false, splitDone: false, result: null };
}

interface StemSplitterProps {
  state: StemSplitterState;
  onChange: (state: StemSplitterState) => void;
  onSplit: () => Promise<StemSplitResult>;
  sessionId: string | null;
  disabled?: boolean;
}

/* ── Audio player hook per stem ──────────────────────── */

function useStemPlayer(url: string, stemColor: string) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const isCleaningRef = useRef(false);

  // Create/destroy WaveSurfer on URL change
  useEffect(() => {
    isCleaningRef.current = false;

    if (wsRef.current) {
      try {
        wsRef.current.unAll();
        wsRef.current.pause();
        wsRef.current.destroy();
      } catch {}
      wsRef.current = null;
    }

    const resetTimer = setTimeout(() => {
      setPlaying(false);
      setCurrentTime(0);
      setDuration(0);
    }, 0);

    if (!containerRef.current || !url) return;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: stemColor + "40",
      progressColor: stemColor,
      cursorColor: "var(--text-primary)",
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      height: 70,
      normalize: true,
      interact: true,
    });

    const p = ws.load(url);
    if (p && typeof p.catch === "function") {
      p.catch(() => {});
    }

    wsRef.current = ws;

    const onReady = () => {
      if (isCleaningRef.current) return;
      setDuration(ws.getDuration());
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
      if (wsRef.current) {
        try {
          wsRef.current.unAll();
          wsRef.current.pause();
          wsRef.current.destroy();
        } catch {}
        wsRef.current = null;
      }
    };
  }, [url, stemColor]);

  const toggle = useCallback(() => {
    const ws = wsRef.current;
    if (!ws) return;
    ws.playPause();
  }, []);

  const stop = useCallback(() => {
    wsRef.current?.pause();
    setPlaying(false);
  }, []);

  const setVolume = useCallback((vol: number) => {
    if (wsRef.current) wsRef.current.setVolume(vol);
  }, []);

  return {
    playing,
    currentTime,
    duration,
    toggle,
    stop,
    setVolume,
    containerRef,
  };
}

/* ── Individual stem card ────────────────────────────── */

function StemCard({
  stem,
  stemState,
  stemUrl,
  onChange,
  disabled,
}: {
  stem: StemInfo;
  stemState: StemState;
  stemUrl?: string;
  onChange: (updates: Partial<StemState>) => void;
  disabled?: boolean;
}) {
  const { playing, toggle, setVolume, containerRef } = useStemPlayer(stemUrl ?? "", stem.color);
  const { t } = useTranslation();
  const pct = ((stemState.gain + 12) / 24) * 100;

  // Sync volume when gain changes
  useEffect(() => {
    const vol = Math.pow(10, stemState.mute ? -60 : stemState.gain / 20);
    setVolume(Math.min(1, vol));
  }, [stemState.gain, stemState.mute, setVolume]);

  const isMuted = stemState.mute;

  return (
    <div
      className="rounded-2xl p-4 transition-all duration-200"
      style={{
        background: isMuted ? "rgba(60, 60, 60, 0.08)" : "var(--surface-hover)",
        border: `1px solid ${isMuted ? "var(--border-subtle)" : `${stem.color}20`}`,
        opacity: isMuted ? 0.5 : 1,
      }}
    >
      {/* Waveform */}
      {stemUrl && (
        <div
          ref={containerRef}
          className="w-full mb-3 rounded-lg overflow-hidden"
          style={{
            height: 70,
            background: "rgba(0,0,0,0.15)",
            cursor: "crosshair",
          }}
          title={`${playing ? "Pausar" : "Reproducir"} • Clic para buscar • Arrastra para scrub`}
        />
      )}

      <div className="flex items-center gap-3">
        {/* Play button */}
        {stemUrl && (
          <button
            onClick={toggle}
            disabled={disabled || isMuted}
            className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all hover:brightness-110"
            style={{ background: `${stem.color}18`, color: stem.color }}
            title={playing ? "Pausar" : "Escuchar"}
          >
            {playing ? <Pause size={16} /> : <Play size={16} />}
          </button>
        )}

        {/* Icon + Label */}
        <div className="w-24 shrink-0 flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: `${stem.color}15`, color: stem.color }}
          >
            <stem.icon size={16} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-[var(--text-primary)] truncate">
              {t(`splitter.${stem.name}`, stem.label)}
            </p>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
              {stemState.gain > 0 ? `+${stemState.gain}` : stemState.gain} dB
            </p>
          </div>
        </div>

        {/* Fader */}
        <div className="flex-1 relative h-1.5 rounded-full min-w-[80px]" style={{ background: "var(--border-subtle)" }}>
          <div
            className="h-full rounded-full transition-all duration-100"
            style={{
              width: `${pct}%`,
              background: `linear-gradient(90deg, ${stem.color}60, ${stem.color})`,
            }}
          />
          <input
            type="range"
            min={-12}
            max={12}
            step={0.5}
            value={stemState.gain}
            onChange={(e) => onChange({ gain: parseFloat(e.target.value) })}
            disabled={disabled || isMuted}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          />
        </div>

        {/* Mute / Solo */}
        <div className="flex gap-1 shrink-0">
          <button
            onClick={() => onChange({ mute: !stemState.mute })}
            disabled={disabled}
            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all text-[11px] font-bold ${
              stemState.mute
                ? "bg-[rgba(255,59,48,0.2)] text-[#ff3b30]"
                : "bg-[var(--surface-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
            }`}
            title={t("splitter.mute", "Silenciar")}
          >
            {stemState.mute ? <VolumeX size={13} /> : <Volume2 size={13} />}
          </button>
          <button
            onClick={() => onChange({ solo: !stemState.solo })}
            disabled={disabled}
            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all text-[11px] font-bold ${
              stemState.solo
                ? "bg-[rgba(255,159,10,0.2)] text-[#ff9f0a]"
                : "bg-[var(--surface-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
            }`}
            title={t("splitter.solo", "Solo")}
          >
            <Headphones size={13} />
          </button>
        </div>

        {/* Download */}
        {stemUrl && (
          <a
            href={stemUrl}
            download
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)] transition-all shrink-0"
            title={t("splitter.downloadWav", "Descargar WAV")}
          >
            <Download size={13} />
          </a>
        )}
      </div>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────── */

export default function StemSplitter({
  state,
  onChange,
  onSplit,
  sessionId,
  disabled,
}: StemSplitterProps) {
  const { t } = useTranslation();

  const updateStem = useCallback(
    (name: StemName, updates: Partial<StemState>) => {
      onChange({
        ...state,
        stems: { ...state.stems, [name]: { ...state.stems[name], ...updates } },
      });
    },
    [state, onChange],
  );

  const handleSplit = useCallback(async () => {
    onChange({ ...state, splitting: true });
    try {
      const result = await onSplit();
      onChange({ ...state, splitting: false, splitDone: true, result });
    } catch {
      onChange({ ...state, splitting: false });
    }
  }, [state, onChange, onSplit]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-primary)]" style={{ letterSpacing: "-0.02em" }}>
            {t("splitter.title", "Stem")} <span className="serif-accent">{t("splitter.titleAccent", "Splitter")}</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {t("splitter.subtitle", "Separá tu mezcla en 4 pistas independientes")}
          </p>
        </div>

        <button
          onClick={handleSplit}
          disabled={disabled || state.splitting || !sessionId}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
          style={{
            background: state.splitDone
              ? "rgba(48, 209, 88, 0.12)"
              : "linear-gradient(135deg, rgba(94,92,230,0.15), rgba(94,92,230,0.06))",
            border: `1px solid ${
              state.splitDone ? "rgba(48, 209, 88, 0.2)" : "rgba(94,92,230,0.2)"
            }`,
            color: state.splitDone ? "#30d158" : "#5e5ce6",
          }}
        >
          {state.splitting ? (
            <><Loader2 size={16} className="animate-spin" /> {t("splitter.splitting", "Separando...")}</>
          ) : state.splitDone ? (
            <><CheckCircle2 size={16} /> {t("splitter.splitDone", "Separado")}</>
          ) : (
            <><Waves size={16} /> {t("splitter.splitButton", "Separar Stems")}</>
          )}
        </button>
      </div>

      {/* Stem cards */}
      <div className="space-y-2">
        {STEMS.map((stem) => (
          <StemCard
            key={stem.name}
            stem={stem}
            stemState={state.stems[stem.name]}
            stemUrl={
              state.splitDone && sessionId
                ? getStemUrl(sessionId, stem.name)
                : undefined
            }
            onChange={(updates) => updateStem(stem.name, updates)}
            disabled={disabled || !state.splitDone}
          />
        ))}
      </div>

      {/* Status messages */}
      {!state.splitDone && !state.splitting && (
        <p className="text-xs text-[var(--text-muted)] text-center pt-2">
          {t("splitter.firstTimeNotice", "Presioná \"Separar Stems\" para empezar. La primera vez descarga el modelo (~1.9 GB) y puede demorar un minuto.")}
        </p>
      )}
      {state.splitting && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <Loader2 size={14} className="animate-spin text-[#5e5ce6]" />
          <span className="text-xs text-[var(--text-secondary)]">{t("splitter.splittingTracks", "Separando pistas...")}</span>
        </div>
      )}
      {state.splitDone && (
        <div className="pt-2 space-y-1">
          <div className="flex items-center justify-center gap-2">
            <CheckCircle2 size={14} className="text-[#30d158]" />
            <p className="text-xs text-[var(--text-secondary)]">
              {t("splitter.splitDoneCount", "Separación completa — 4 stems generados")}
            </p>
          </div>
          <p className="text-xs text-[var(--text-muted)] text-center">
            {t("splitter.guideNotice", "Usa los botones de reproducción para escuchar cada stem, los faders para ajustar volumen, Mute/Solo para aislar, y Descargar para guardar.")}
          </p>
        </div>
      )}
    </div>
  );
}
