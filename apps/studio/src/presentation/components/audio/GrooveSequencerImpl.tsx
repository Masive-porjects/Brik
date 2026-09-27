"use client";

import { useState, useMemo } from "react";
import { Pause, Play } from "lucide-react";
import StepGrid from "./StepGrid";
import { GENRE_PRESETS, parsePresetGrid } from "./genrePresets";
import { useSequencerEngine } from "./useSequencerEngine";
import { audioEngine } from "@/adapters/audio/engine";
import { useTranslation } from "@/i18n";

// Matches the SongStarter stem palette so both sections read as one instrument.
const TRACK_COLORS: readonly string[] = [
  "#ff3b30", // Kick
  "#ff9f0a", // Caja
  "#30d158", // Hi-Hat
  "#007aff", // Bajo
];

const INITIAL_PRESET = GENRE_PRESETS[0];

export default function GrooveSequencerImpl() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState(INITIAL_PRESET.id);
  const {
    playing,
    bpm,
    grid,
    canvasRef,
    toggleStep,
    toggleTransport,
    applyPattern,
  } = useSequencerEngine({
    initialGrid: () => parsePresetGrid(INITIAL_PRESET),
    initialBpm: INITIAL_PRESET.bpm,
    initialBassNotes: INITIAL_PRESET.bassNotes,
  });

  const trackNames = useMemo(
    () => [
      t("songstarter.tracks.kick", "Kick"),
      t("songstarter.tracks.snare", "Caja"),
      t("songstarter.tracks.hihat", "Hi-Hat"),
      t("songstarter.tracks.bass", "Bajo"),
    ],
    [t],
  );

  const handleGenreSelect = async (id: string): Promise<void> => {
    const preset = GENRE_PRESETS.find((genre) => genre.id === id);
    if (!preset) return;
    setSelectedId(id);
    // Autoplay-policy gate inside the click gesture. The pattern itself
    // reaches a running sequence through the ref mirror — no recreation.
    await audioEngine.ensureStarted();
    applyPattern({
      bpm: preset.bpm,
      grid: parsePresetGrid(preset),
      bassNotes: preset.bassNotes,
    });
  };

  return (
    <section
      className="rounded-2xl p-5"
      style={{
        background:
          "linear-gradient(180deg, var(--bg-tertiary), var(--bg-secondary))",
        border: "1px solid var(--border-subtle)",
        boxShadow: "inset 0 1px 0 var(--border-subtle), var(--shadow-card)",
      }}
    >
      <header className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            {t("songstarter.grooveTitle", "Prueba el groove")}
          </h3>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {t("songstarter.grooveSubtitle", "Elige un género y edita los pasos mientras suena")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void toggleTransport();
          }}
          className="flex shrink-0 items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold transition-all duration-300 hover:brightness-110"
          style={{
            background: playing
              ? "rgba(245,158,11,0.15)"
              : "linear-gradient(135deg, rgba(245,158,11,0.15), rgba(245,158,11,0.06))",
            border: "1px solid rgba(245,158,11,0.2)",
            color: "#f59e0b",
          }}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
          {playing ? t("songstarter.stop", "Detener") : t("songstarter.play", "Reproducir")}
        </button>
      </header>

      <div
        role="group"
        aria-label="Géneros"
        className="mb-4 flex flex-wrap gap-2"
      >
        {GENRE_PRESETS.map((preset) => {
          const active = selectedId === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              aria-pressed={active}
              onClick={() => {
                void handleGenreSelect(preset.id);
              }}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all hover:brightness-110 ${
                active ? "" : "hover:text-[var(--text-primary)]"
              }`}
              style={{
                background: active
                  ? "rgba(245,158,11,0.15)"
                  : "var(--surface-hover)",
                border: `1px solid ${
                  active ? "rgba(245,158,11,0.4)" : "var(--border-subtle)"
                }`,
                color: active ? "#f59e0b" : "var(--text-secondary)",
              }}
            >
              {preset.label}
              <span className="ml-1.5 font-mono text-[10px] opacity-70">
                {preset.bpm}
              </span>
            </button>
          );
        })}
      </div>

      <canvas
        ref={canvasRef}
        className="mb-4 h-14 w-full rounded-md"
        style={{
          background: "var(--bg-tertiary)",
          border: "1px solid var(--border)",
        }}
        aria-hidden="true"
      />

      <StepGrid
        grid={grid}
        trackNames={trackNames}
        onToggleCell={toggleStep}
        trackColors={TRACK_COLORS}
      />

      <footer className="mt-4 flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
          {playing ? t("songstarter.playing", "Reproduciendo") : t("songstarter.ready", "Listo")}
        </span>
        <span
          className="rounded-md px-2 py-0.5 text-[10px] font-medium"
          style={{
            background: "rgba(245,158,11,0.1)",
            color: "#f59e0b",
          }}
        >
          {bpm} BPM
        </span>
      </footer>
    </section>
  );
}
