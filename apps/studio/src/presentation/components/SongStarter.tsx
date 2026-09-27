"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import {
  Music2, Play, Pause, Loader2, CheckCircle2,
  Trash2, Download, Volume2, VolumeX,
} from "lucide-react";
import {
  generateBeat,
  saveBeat,
  listBeats,
  deleteBeat,
  getBeatAudioUrl,
  type BeatParams,
  type BeatResponse,
  type SavedBeat,
} from "@/lib/api";
import GrooveSequencer from "@/components/audio/GrooveSequencer";
import { useTranslation } from "@/i18n";

/* ── Constants ─────────────────────────────────────── */

const SCALES: { label: string; value: string }[] = [
  { label: "Mayor", value: "major" },
  { label: "Menor Natural", value: "natural_minor" },
  { label: "Dórico", value: "dorian" },
  { label: "Frigio", value: "phrygian" },
  { label: "Lidio", value: "lydian" },
  { label: "Mixolidio", value: "mixolydian" },
  { label: "Eólico", value: "natural_minor" },
  { label: "Locrio", value: "locrian" },
  { label: "Pentatónica Mayor", value: "pentatonic_major" },
  { label: "Pentatónica Menor", value: "pentatonic_minor" },
  { label: "Armónica Menor", value: "harmonic_minor" },
  { label: "Disminuido", value: "locrian" },
];

const ROOT_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

const STEM_LABELS: Record<string, string> = {
  mix: "Mezcla",
  kick: "Kick",
  snare: "Snare",
  hihat_closed: "Hi-Hat Closed",
  hihat_open: "Hi-Hat Open",
  clap: "Clap",
  bass: "Bajo",
  chords: "Acordes",
};

const STEM_COLORS: Record<string, string> = {
  mix: "#f59e0b",
  kick: "#ff3b30",
  snare: "#ff9f0a",
  hihat_closed: "#30d158",
  hihat_open: "#34c759",
  clap: "#5e5ce6",
  bass: "#007aff",
  chords: "#ff6488",
};

const DEFAULT_BEAT_PARAMS: BeatParams = {
  bpm: 120,
  scale: "major",
  root_note: "C",
  swing_amount: 0.3,
};

/* ── Stem row ──────────────────────────────────────── */

function StemRow({
  name,
  label,
  color,
  url,
  disabled,
  playing,
  onToggle,
  onVolumeChange,
}: {
  name: string;
  label: string;
  color: string;
  url?: string;
  disabled?: boolean;
  playing: boolean;
  onToggle: () => void;
  onVolumeChange: (name: string, vol: number) => void;
}) {
  const [gain, setGain] = useState(0);
  const [muted, setMuted] = useState(false);
  const pct = ((gain + 60) / 66) * 100;

  // Sync volume when gain or mute changes
  useEffect(() => {
    const vol = muted ? 0 : Math.min(1, Math.pow(10, Math.max(-60, gain) / 20));
    onVolumeChange(name, vol);
  }, [gain, muted, name, onVolumeChange]);

  return (
    <div
      className="flex items-center gap-3 rounded-xl px-3 py-2 transition-all"
      style={{
        background: muted ? "rgba(60,60,60,0.08)" : "var(--surface-hover)",
        border: `1px solid ${muted ? "var(--border-subtle)" : `${color}18`}`,
        opacity: muted ? 0.5 : 1,
      }}
    >
      {/* Play button */}
      {url && (
        <button
          onClick={onToggle}
          disabled={disabled || muted}
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all hover:brightness-110"
          style={{ background: `${color}18`, color }}
          title={playing ? "Pausar" : "Reproducir"}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
      )}

      {/* Stem name */}
      <div className="w-28 shrink-0">
        <p className="text-sm font-medium text-[var(--text-primary)] truncate">{label}</p>
        <p className="text-[10px] text-[var(--text-muted)] font-mono">
          {gain <= -60 ? "-∞" : `${gain > 0 ? "+" : ""}${gain.toFixed(1)} dB`}
        </p>
      </div>

      {/* Fader */}
      <div className="flex-1 relative h-1.5 rounded-full min-w-[60px]" style={{ background: "var(--border-subtle)" }}>
        <div
          className="h-full rounded-full transition-all duration-100"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${color}60, ${color})`,
          }}
        />
        <input
          type="range"
          min={-60}
          max={6}
          step={0.5}
          value={gain}
          onChange={(e) => setGain(parseFloat(e.target.value))}
          disabled={disabled || muted}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
      </div>

      {/* Mute */}
      <button
        onClick={() => setMuted(!muted)}
        disabled={disabled}
        className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all shrink-0 ${
          muted
            ? "bg-[rgba(255,59,48,0.2)] text-[#ff3b30]"
            : "bg-[var(--surface-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
        }`}
        title="Mute"
      >
        {muted ? <VolumeX size={12} /> : <Volume2 size={12} />}
      </button>
    </div>
  );
}

/* ── Main Component ────────────────────────────────── */

interface SongStarterProps {
  sessionId: string | null;
  disabled?: boolean;
}

export default function SongStarter({ sessionId, disabled }: SongStarterProps) {
  const { t } = useTranslation();
  const [params, setParams] = useState<BeatParams>(DEFAULT_BEAT_PARAMS);
  const [generating, setGenerating] = useState(false);
  const [beat, setBeat] = useState<BeatResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [savedBeats, setSavedBeats] = useState<SavedBeat[]>([]);
  const [loadingBeats, setLoadingBeats] = useState(false);

  // Generate a stable session ID for the SongStarter (fallback if no session)
  const [stableSessionId] = useState<string>(() => {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return `ss-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  });

  const effectiveSessionId = sessionId ?? stableSessionId;

  /* ── Shared audio transport ─────────────────────────
     One Audio element per stem (plus one for the mix),
     created lazily and keyed by stem name. All stems
     start from beat 0 so they stay in sync. */
  const audioEls = useRef<Record<string, HTMLAudioElement>>({});
  const volumesRef = useRef<Record<string, number>>({});
  const [activeStems, setActiveStems] = useState<Set<string>>(new Set());
  const [mixPlaying, setMixPlaying] = useState(false);

  // Map each stem/mix to its audio URL for the current beat
  const beatUrls = useMemo<Record<string, string>>(() => {
    if (!beat) return {};
    const urls: Record<string, string> = {
      mix: getBeatAudioUrl(effectiveSessionId, beat.beat_id),
    };
    Object.keys(beat.stems).forEach((name) => {
      urls[name] = getBeatAudioUrl(effectiveSessionId, beat.beat_id, name);
    });
    return urls;
  }, [beat, effectiveSessionId]);

  const handleAudioEnded = useCallback((key: string) => {
    if (key === "mix") {
      setMixPlaying(false);
      return;
    }
    setActiveStems((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  }, []);

  const ensureAudio = useCallback(
    (key: string, url: string): HTMLAudioElement => {
      let el = audioEls.current[key];
      if (!el) {
        el = new Audio();
        el.preload = "none";
        el.addEventListener("ended", () => handleAudioEnded(key));
        el.volume = volumesRef.current[key] ?? 1;
        audioEls.current[key] = el;
      }
      if (el.getAttribute("data-src") !== url) {
        el.pause();
        el.src = url;
        el.load();
        el.setAttribute("data-src", url);
      }
      return el;
    },
    [handleAudioEnded],
  );

  const stopMix = useCallback(() => {
    const mix = audioEls.current["mix"];
    if (mix) {
      mix.pause();
      mix.currentTime = 0;
    }
    setMixPlaying(false);
  }, []);

  const stopAllStems = useCallback(() => {
    Object.entries(audioEls.current).forEach(([key, el]) => {
      if (key === "mix") return;
      el.pause();
      el.currentTime = 0;
    });
    setActiveStems(new Set());
  }, []);

  const playStems = useCallback(
    (targetKey: string) => {
      if (!beat) return;
      stopMix();
      // Pause every stem and rewind to beat 0 so the pressed
      // stem joins the already-active ones on the same downbeat.
      const toPlay = new Set(activeStems);
      toPlay.add(targetKey);
      Object.entries(audioEls.current).forEach(([key, el]) => {
        if (key === "mix") return;
        el.pause();
        el.currentTime = 0;
      });
      toPlay.forEach((key) => {
        const url = beatUrls[key];
        if (!url) return;
        const el = ensureAudio(key, url);
        el.currentTime = 0;
        el.play().catch(() => {});
      });
      setActiveStems(toPlay);
    },
    [beat, activeStems, beatUrls, ensureAudio, stopMix],
  );

  const pauseStem = useCallback((key: string) => {
    audioEls.current[key]?.pause();
    setActiveStems((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  }, []);

  const handleStemToggle = useCallback(
    (key: string) => {
      if (!beat) return;
      if (activeStems.has(key)) pauseStem(key);
      else playStems(key);
    },
    [beat, activeStems, pauseStem, playStems],
  );

  const handleStemVolume = useCallback((key: string, vol: number) => {
    volumesRef.current[key] = vol;
    const el = audioEls.current[key];
    if (el) el.volume = vol;
  }, []);

  const handleMixToggle = useCallback(() => {
    if (!beat) return;
    if (mixPlaying) {
      stopMix();
      return;
    }
    stopAllStems();
    const url = beatUrls["mix"];
    if (!url) return;
    const mix = ensureAudio("mix", url);
    mix.currentTime = 0;
    mix
      .play()
      .then(() => setMixPlaying(true))
      .catch(() => {});
  }, [beat, mixPlaying, beatUrls, ensureAudio, stopMix, stopAllStems]);

  // Stop + reset the transport whenever the beat changes
  useEffect(() => {
    Object.values(audioEls.current).forEach((el) => {
      el.pause();
      el.currentTime = 0;
    });
    audioEls.current = {};
    const resetTimer = setTimeout(() => {
      setActiveStems(new Set());
      setMixPlaying(false);
    }, 0);
    return () => clearTimeout(resetTimer);
  }, [beat?.beat_id]);

  // When no stems remain active, rewind them to beat 0
  useEffect(() => {
    if (activeStems.size === 0) {
      Object.entries(audioEls.current).forEach(([key, el]) => {
        if (key !== "mix") el.currentTime = 0;
      });
    }
  }, [activeStems]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      Object.values(audioEls.current).forEach((el) => {
        el.pause();
        el.src = "";
      });
      audioEls.current = {};
    };
  }, []);

  // Load saved beats on mount
  const refreshBeats = useCallback(async () => {
    setLoadingBeats(true);
    try {
      const beats = await listBeats();
      setSavedBeats(beats);
    } catch {
      // Silently fail — library is best-effort
    } finally {
      setLoadingBeats(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => refreshBeats(), 0);
    return () => clearTimeout(t);
  }, [refreshBeats]);

  // Generate a beat
  const handleGenerate = useCallback(async () => {
    if (disabled) return;
    setGenerating(true);
    setSaved(false);
    try {
      const result = await generateBeat(effectiveSessionId, params);
      setBeat(result);
    } catch {
      setBeat(null);
    } finally {
      setGenerating(false);
    }
  }, [effectiveSessionId, params, disabled]);

  // Save the current beat
  const handleSave = useCallback(async () => {
    if (!beat || saving) return;
    setSaving(true);
    try {
      await saveBeat(effectiveSessionId, beat.beat_id, undefined, {
        bpm: beat.bpm,
        scale: beat.scale,
        root_note: beat.root_note,
        swing_amount: beat.swing_amount,
      });
      setSaved(true);
      await refreshBeats();
    } catch {
      // Error handled silently
    } finally {
      setSaving(false);
    }
  }, [beat, saving, effectiveSessionId, refreshBeats]);

  // Load a saved beat
  const handleLoadBeat = useCallback((saved: SavedBeat) => {
    setParams({
      bpm: saved.bpm,
      scale: saved.scale,
      root_note: saved.root_note,
      swing_amount: saved.swing_amount,
    });
    // Construct a beat from the saved data for playback
    setBeat({
      beat_id: saved.id,
      bpm: saved.bpm,
      scale: saved.scale,
      root_note: saved.root_note,
      swing_amount: saved.swing_amount,
      duration: saved.duration,
      output_path: "",
      stems: {},
    });
    setSaved(false);
  }, []);

  // Delete a saved beat
  const handleDeleteBeat = useCallback(async (beatId: string) => {
    try {
      await deleteBeat(beatId);
      await refreshBeats();
    } catch {
      // Error handled silently
    }
  }, [refreshBeats]);

  // Derive stem list from the beat's stems
  const stemEntries = beat
    ? [
        { name: "mix", label: t("songstarter.tracks.mix", STEM_LABELS.mix), color: STEM_COLORS.mix },
        ...Object.keys(beat.stems).map((name) => ({
          name,
          label: t(`songstarter.tracks.${name}`, STEM_LABELS[name] ?? name),
          color: STEM_COLORS[name] ?? "#888",
        })),
      ]
    : [];

  return (
    <div className="space-y-5">
      {/* ═══════════════════════════════════════════════
           Header
           ═══════════════════════════════════════════════ */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[var(--text-primary)]" style={{ letterSpacing: "-0.02em" }}>
            SongStarter
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {t("songstarter.subtitle", "Generá bases rítmicas y armónicas al instante")}
          </p>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════
           Controls Rack
           ═══════════════════════════════════════════════ */}
      <div
        className="rounded-2xl p-5 md:p-6"
        style={{
          background: "linear-gradient(180deg, var(--bg-tertiary), var(--bg-secondary))",
          border: "1px solid var(--border-subtle)",
          boxShadow: "inset 0 1px 0 var(--border-subtle), var(--shadow-card)",
        }}
      >
        {/* Rack ears */}
        <div className="flex items-center justify-center mb-5">
          <div className="flex items-center gap-3">
            <Music2 size={16} className="text-[#f59e0b]" />
            <span className="text-[10px] font-semibold text-[var(--text-muted)] tracking-[0.2em] uppercase">
              SongStarter — WaveEngine
            </span>
            <Music2 size={16} className="text-[#f59e0b]" />
          </div>
        </div>

        {/* Controls grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* BPM */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-[var(--text-secondary)] font-medium tracking-wide">
              {t("songstarter.bpm", "BPM")} <span className="text-[#f59e0b] font-bold">{params.bpm}</span>
            </label>
            <input
              type="range"
              min={60}
              max={180}
              step={1}
              value={params.bpm}
              onChange={(e) => setParams({ ...params, bpm: parseInt(e.target.value) })}
              disabled={disabled}
              className="w-full accent-[#f59e0b]"
              style={{ height: 6, borderRadius: 3, background: "var(--border-subtle)" }}
            />
            <div className="flex justify-between text-[9px] text-[var(--text-muted)]">
              <span>60</span>
              <span>120</span>
              <span>180</span>
            </div>
          </div>

          {/* Scale */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-[var(--text-secondary)] font-medium tracking-wide">
              {t("songstarter.scale", "Modo")}
            </label>
            <select
              value={params.scale}
              onChange={(e) => setParams({ ...params, scale: e.target.value })}
              disabled={disabled}
              className="w-full rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] bg-[var(--surface-hover)] border border-[var(--border-subtle)] focus:border-[#f59e0b] outline-none transition-all"
              style={{ appearance: "auto" }}
            >
              {SCALES.map((s) => (
                <option key={`${s.value}-${s.label}`} value={s.value} className="bg-[var(--bg-secondary)] text-[var(--text-primary)]">
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {/* Root note */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-[var(--text-secondary)] font-medium tracking-wide">
              {t("songstarter.rootNote", "Tónica")}
            </label>
            <div className="flex flex-wrap gap-1">
              {ROOT_NOTES.map((note) => (
                <button
                  key={note}
                  onClick={() => setParams({ ...params, root_note: note })}
                  disabled={disabled}
                  className={`w-8 h-8 rounded-lg text-xs font-bold transition-all ${
                    params.root_note === note
                      ? "bg-[#f59e0b] text-black shadow-lg shadow-[rgba(245,158,11,0.3)]"
                      : "bg-[var(--surface-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
                  }`}
                >
                  {note}
                </button>
              ))}
            </div>
          </div>

          {/* Swing */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-[var(--text-secondary)] font-medium tracking-wide">
              {t("songstarter.swing", "Swing")} <span className="text-[#f59e0b] font-bold">{Math.round((params.swing_amount ?? 0) * 100)}%</span>
            </label>
            <input
              type="range"
              min={0}
              max={0.8}
              step={0.05}
              value={params.swing_amount ?? 0.3}
              onChange={(e) => setParams({ ...params, swing_amount: parseFloat(e.target.value) })}
              disabled={disabled}
              className="w-full accent-[#f59e0b]"
              style={{ height: 6, borderRadius: 3, background: "var(--border-subtle)" }}
            />
            <div className="flex justify-between text-[9px] text-[var(--text-muted)]">
              <span>0%</span>
              <span>40%</span>
              <span>80%</span>
            </div>
          </div>
        </div>

        {/* Generate button */}
        <div className="flex justify-center mt-5">
          <button
            onClick={handleGenerate}
            disabled={disabled || generating}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
            style={{
              background: beat
                ? "rgba(245,158,11,0.12)"
                : "linear-gradient(135deg, rgba(245,158,11,0.15), rgba(245,158,11,0.06))",
              border: `1px solid ${
                beat ? "rgba(245,158,11,0.2)" : "rgba(245,158,11,0.15)"
              }`,
              color: "#f59e0b",
            }}
          >
            {generating ? (
              <><Loader2 size={16} className="animate-spin" /> {t("songstarter.generating", "Generando...")}</>
            ) : beat ? (
              <><Music2 size={16} /> {t("songstarter.regenerate", "Regenerar Beat")}</>
            ) : (
              <><Music2 size={16} /> {t("songstarter.generateBeat", "Generar Beat")}</>
            )}
          </button>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════
           Prueba el groove — secuenciador interactivo
           ═══════════════════════════════════════════════ */}
      <GrooveSequencer />

      {/* ═══════════════════════════════════════════════
           Player Section
           ═══════════════════════════════════════════════ */}
      {beat && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              {t("songstarter.stemsTitle", "Stems")}
            </h3>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[var(--text-muted)]">
                {beat.bpm} BPM · {beat.scale} · {beat.root_note} · {beat.duration.toFixed(1)}s
              </span>
              {/* Save button */}
              <button
                onClick={handleSave}
                disabled={disabled || saving || saved}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110"
                style={{
                  background: saved
                    ? "rgba(48,209,88,0.12)"
                    : "var(--surface-hover)",
                  border: `1px solid ${
                    saved ? "rgba(48,209,88,0.2)" : "var(--border-subtle)"
                  }`,
                  color: saved ? "#30d158" : "#f59e0b",
                }}
              >
                {saving ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : saved ? (
                  <CheckCircle2 size={12} />
                ) : (
                  <Download size={12} />
                )}
                {saving
                  ? t("common.saving", "Guardando...")
                  : saved
                    ? t("songstarter.saved", "Guardado")
                    : t("songstarter.saveBeat", "Guardar")}
              </button>
            </div>
          </div>

          {/* Escuchar todo — main transport for the full mix */}
          <button
            onClick={handleMixToggle}
            disabled={disabled}
            className="flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-300 hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: mixPlaying
                ? "rgba(245,158,11,0.15)"
                : "linear-gradient(135deg, rgba(245,158,11,0.15), rgba(245,158,11,0.06))",
              border: "1px solid rgba(245,158,11,0.2)",
              color: "#f59e0b",
              boxShadow: mixPlaying
                ? "0 0 24px rgba(245,158,11,0.12)"
                : "none",
            }}
          >
            {mixPlaying ? <Pause size={16} /> : <Play size={16} />}
            {mixPlaying ? t("player.pause", "Pausar") : t("songstarter.listenAll", "Escuchar todo")}
          </button>

          <div className="space-y-1.5">
            {stemEntries.map((stem) => (
              <StemRow
                key={stem.name}
                name={stem.name}
                label={stem.label}
                color={stem.color}
                url={beatUrls[stem.name]}
                disabled={disabled}
                playing={
                  stem.name === "mix" ? mixPlaying : activeStems.has(stem.name)
                }
                onToggle={
                  stem.name === "mix"
                    ? handleMixToggle
                    : () => handleStemToggle(stem.name)
                }
                onVolumeChange={handleStemVolume}
              />
            ))}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
           Library Panel
           ═══════════════════════════════════════════════ */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            {t("songstarter.savedBeats", "Beats Guardados")}
          </h3>
          <button
            onClick={refreshBeats}
            disabled={loadingBeats}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            {loadingBeats ? t("common.loading", "Cargando...") : t("common.refresh", "Actualizar")}
          </button>
        </div>

        {savedBeats.length === 0 && !loadingBeats && (
          <div
            className="rounded-xl p-4 text-center"
            style={{ background: "var(--surface-hover)", border: "1px solid var(--border-subtle)" }}
          >
            <p className="text-xs text-[var(--text-muted)]">
              {t("songstarter.noSavedBeats", "No hay beats guardados todavía. Genera uno y presiona Guardar.")}
            </p>
          </div>
        )}

        {loadingBeats && (
          <div className="flex items-center justify-center py-4">
            <Loader2 size={16} className="animate-spin text-[#f59e0b]" />
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {savedBeats.map((saved) => (
            <div
              key={saved.id}
              className="rounded-xl p-4 transition-all hover:brightness-110"
              style={{
                background: "var(--surface-hover)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <div className="flex items-start justify-between mb-2">
                <div>
                  <p className="text-sm font-medium text-[var(--text-primary)] truncate max-w-[120px]">
                    {saved.name ?? `Beat ${saved.id.slice(0, 8)}`}
                  </p>
                  <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
                    {new Date(saved.created_at).toLocaleDateString(undefined, {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
                <Music2 size={14} className="text-[#f59e0b] shrink-0" />
              </div>

              <div className="flex gap-2 text-[10px] text-[var(--text-secondary)] mb-3">
                <span className="bg-[rgba(245,158,11,0.1)] text-[#f59e0b] px-2 py-0.5 rounded-md font-medium">
                  {saved.bpm} BPM
                </span>
                <span className="bg-[var(--surface-hover)] px-2 py-0.5 rounded-md">
                  {saved.scale}
                </span>
                <span className="bg-[var(--surface-hover)] px-2 py-0.5 rounded-md">
                  {saved.root_note}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleLoadBeat(saved)}
                  className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-all bg-[rgba(245,158,11,0.1)] text-[#f59e0b] hover:brightness-110"
                >
                  {t("songstarter.load", "Cargar")}
                </button>
                <button
                  onClick={() => handleDeleteBeat(saved.id)}
                  className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[#ff3b30] hover:bg-[rgba(255,59,48,0.1)] transition-all"
                  title={t("common.delete", "Eliminar")}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ═══════════════════════════════════════════════
           Status messages
           ═══════════════════════════════════════════════ */}
      {!beat && !generating && (
        <p className="text-xs text-[var(--text-muted)] text-center">
          {t("songstarter.startPrompt", "Ajusta los parámetros y presiona \"Generar Beat\" para empezar.")}
        </p>
      )}
      {generating && (
        <div className="flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin text-[#f59e0b]" />
          <span className="text-xs text-[var(--text-secondary)]">
            {t("songstarter.generatingBeat", "Generando beat...")}
          </span>
        </div>
      )}
    </div>
  );
}
