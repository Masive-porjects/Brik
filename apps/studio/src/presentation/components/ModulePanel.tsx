"use client";

import { useRef, useState, useCallback } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { PRESET_COLORS, DEFAULT_PRESET_COLOR } from "@/core/presets";
import { type MasteringParameters, DEFAULT_PARAMS } from "@/lib/api";
import {
  Sparkles,
  Flame,
  Sun,
  AudioLines,
  Leaf,
  Orbit,
  Music2,
  Zap,
  GripVertical,
  Info,
} from "lucide-react";
import PresetTooltip from "@/components/PresetTooltip";
import { useTranslation } from "@/i18n";

/* ── Types ────────────────────────────────────────────── */

interface ModulePanelProps {
  params: MasteringParameters;
  onChange: (params: MasteringParameters) => void;
  disabled?: boolean;
  activePresetId?: string | null;
  onPresetSelect?: (params: MasteringParameters, presetId: string) => void;
}

interface MacroPreset {
  id: string;
  title: string;
  genre: string;
  description: string;
  tooltip: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  params: MasteringParameters;
}

/* ── 8 Macro-Character Presets ────────────────────────── */

/** Exportado para que el agente pueda aplicar un preset sin duplicar sus
 *  parametros. Los ids coinciden con PRESET_CHAINS del backend. */
export const PRESETS: MacroPreset[] = [
  {
    id: "universal",
    title: "Pulido",
    genre: "Multigénero",
    description: "Balance profesional para cualquier género",
    tooltip: "Cadena equilibrada: ecualización transparente, compresión suave (1.5:1) y limitación a -14 LUFS. Ideal cuando no sabes qué preset elegir — preserva la intención de la mezcla original.",
    icon: Sparkles,
    params: { ...DEFAULT_PARAMS, target_lufs_db: -14 },
  },
  {
    id: "fuego",
    title: "Brutal",
    genre: "Trap / Drill",
    description: "Compresión agresiva y pegada máxima para beats modernos",
    tooltip: "Compresión pesada (5:1) con boost de transientes +3dB y saturación leve. Masteriza a -12 LUFS con techo en -1dB, el máximo seguro para streaming: suena caliente en trap y drill sin que Spotify/Apple/YouTube lo atenúen ni le agreguen distorsión.",
    icon: Flame,
    params: {
      ...DEFAULT_PARAMS,
      compression_ratio: 5.0,
      transient_boost_db: 3.0,
      saturation_drive_db: 2.0,
      saturation_warmth_db: 0.5,
      limiter_ceiling_db: -1.0,
      stereo_width: 1.0,
      haas_delay_ms: 0,
      target_lufs_db: -12,
    },
  },
  {
    id: "claridad",
    title: "Cristalino",
    genre: "Pop / Latin Pop",
    description: "Brillo extremo y apertura estéreo para voces y mezclas pop",
    tooltip: "Ecualización con +4dB de brillo en agudos, Haas delay de 6ms para amplitud estéreo y compresión suave (2:1). Perfecto para voces pop que necesitan brillar por encima de la mezcla.",
    icon: Sun,
    params: {
      ...DEFAULT_PARAMS,
      clarity_wet: 0.35,
      clarity_brightness_db: 4.0,
      compression_ratio: 2.0,
      transient_boost_db: 2.0,
      stereo_width: 1.3,
      haas_delay_ms: 6,
      target_lufs_db: -13,
    },
  },
  {
    id: "cinta",
    title: "Vintage",
    genre: "Lo-Fi / Hip Hop",
    description: "Saturación armónica tipo cinta analógica con calidez vintage",
    tooltip: "Saturación armónica de segundo orden (+3dB drive, +4dB warmth) que simula cinta analógica. Compresión suave (2:1) con techo en -1.5dB. Los armónicos pegan calidez y la mezcla suena 'vivida'.",
    icon: AudioLines,
    params: {
      ...DEFAULT_PARAMS,
      saturation_drive_db: 3.0,
      saturation_warmth_db: 4.0,
      compression_ratio: 2.0,
      limiter_ceiling_db: -1.5,
      clarity_brightness_db: -0.5,
      transient_boost_db: 0.5,
      stereo_width: 1.0,
      target_lufs_db: -12,
    },
  },
  {
    id: "natural",
    title: "Crudo",
    genre: "Acústico / Folk",
    description: "Mínimo procesamiento, dinámica orgánica y transparencia",
    tooltip: "Compresión casi transparente (1.5:1) con techo conservador en -2dB. Saturación mínima, sin Haas delay. Respeta la dinámica natural — ideal para acústica, folk y grabaciones en vivo donde cada matiz importa.",
    icon: Leaf,
    params: {
      ...DEFAULT_PARAMS,
      compression_ratio: 1.5,
      limiter_ceiling_db: -2.0,
      clarity_wet: 0.05,
      clarity_brightness_db: 0.5,
      saturation_drive_db: 0.3,
      saturation_warmth_db: 0.5,
      transient_boost_db: 0.5,
      stereo_width: 1.0,
      haas_delay_ms: 0,
      target_lufs_db: -14,
    },
  },
  {
    id: "espacial",
    title: "Envolvente",
    genre: "Ambient / Electronic",
    description: "Imagen stereo anchísima con Haas delay para paisajes sónicos",
    tooltip: "Stereo width al máximo (1.8x) con Haas delay de 15ms que crea una imagen sonora envolvente. Brillo +2dB y compresión suave (2:1). Pensado para pads, synths y paisajes que necesitan habitar el espacio.",
    icon: Orbit,
    params: {
      ...DEFAULT_PARAMS,
      stereo_width: 1.8,
      haas_delay_ms: 15,
      clarity_brightness_db: 2.0,
      clarity_wet: 0.3,
      compression_ratio: 2.0,
      target_lufs_db: -13,
    },
  },
  {
    id: "cinematico",
    title: "Épico",
    genre: "Rock / Alternativo",
    description: "Punch, calidez y pegada para guitarras y baterías en vivo",
    tooltip: "Stereo amplio (1.6x) con Haas delay de 12ms, saturación cálida (+2.5dB) y compresión con punch (2.5:1). Boost de transientes +2.5dB para que baterías y guitarras corten con presencia cinematográfica.",
    icon: Music2,
    params: {
      ...DEFAULT_PARAMS,
      stereo_width: 1.6,
      haas_delay_ms: 12,
      clarity_brightness_db: 2.5,
      clarity_wet: 0.3,
      saturation_warmth_db: 2.5,
      saturation_drive_db: 2.0,
      compression_ratio: 2.5,
      transient_boost_db: 2.5,
      target_lufs_db: -12,
    },
  },
  {
    id: "empuje",
    title: "Muro",
    genre: "Reggaeton / Dembow",
    description: "Loudness máximo con graves contundentes para pistas urbanas",
    tooltip: "Compresión pesada (8:1) con saturación (+4dB) y limitador en -1dB, el máximo seguro de true-peak para streaming. Transientes +4dB para que el dembow y el reggaeton golpeen como muro. Es el preset más denso — suena fuerte sin romper el estándar de -1 dBTP.",
    icon: Zap,
    params: {
      ...DEFAULT_PARAMS,
      compression_ratio: 8.0,
      limiter_ceiling_db: -1.0,
      transient_boost_db: 4.0,
      saturation_drive_db: 4.0,
      clarity_brightness_db: 1.0,
      stereo_width: 1.0,
      haas_delay_ms: 0,
      target_lufs_db: -12,
    },
  },
];

/* ── Macro-Character Card ─────────────────────────────── */

function MacroCard({
  preset,
  active,
  onClick,
  disabled,
}: {
  preset: MacroPreset;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const cardRef = useRef<HTMLDivElement>(null);
  const Icon = preset.icon;
  const presetColor = PRESET_COLORS[preset.id]?.wave ?? DEFAULT_PRESET_COLOR.wave;

  const title = t(`mastering.presets.${preset.id}.name`, preset.title);
  const description = t(`mastering.presets.${preset.id}.description`, preset.description);
  const genre = t(`mastering.presets.${preset.id}.genre`, preset.genre);
  const tooltip = t(`mastering.presets.${preset.id}.tooltip`, preset.tooltip);

  /* Entry animation — runs once on mount */
  useGSAP(
    () => {
      if (cardRef.current) {
        gsap.from(cardRef.current, {
          scale: 0.92,
          opacity: 0,
          y: 24,
          duration: 0.5,
          ease: "power2.out",
        });
      }
    },
    { scope: cardRef },
  );

  /* ── Event handlers — drive GSAP tweens ── */
  const handleMouseEnter = () => {
    if (disabled) return;
    gsap.to(cardRef.current, {
      scale: 1.03,
      borderColor: active ? presetColor : "rgba(98, 126, 132, 0.5)",
      boxShadow: active
        ? `0px 0px 24px color-mix(in srgb, ${presetColor} 35%, transparent)`
        : "0px 0px 24px rgba(98, 126, 132, 0.2)",
      duration: 0.35,
      ease: "power2.out",
    });
  };

  const handleMouseLeave = () => {
    gsap.to(cardRef.current, {
      scale: 1,
      borderColor: active ? presetColor : "var(--border-subtle)",
      boxShadow: active
        ? `0px 0px 16px color-mix(in srgb, ${presetColor} 30%, transparent)`
        : "0px 0px 0px rgba(0,0,0,0)",
      duration: 0.35,
      ease: "power2.out",
    });
  };

  const handleMouseDown = () => {
    if (disabled) return;
    gsap.to(cardRef.current, {
      scale: 0.97,
      duration: 0.1,
      ease: "none",
    });
  };

  const handleMouseUp = () => {
    gsap.to(cardRef.current, {
      scale: 1.03,
      duration: 0.15,
      ease: "power2.out",
    });
  };

  return (
    <div
      ref={cardRef}
      onClick={disabled ? undefined : onClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      className="rounded-xl p-4 cursor-pointer select-none transition-[background] duration-300"
      style={{
        background: active
          ? "rgba(98, 126, 132, 0.06)"
          : "var(--bg-glass)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        border: active
          ? `1px solid ${presetColor}`
          : "1px solid var(--border-subtle)",
        boxShadow: active
          ? `0px 0px 16px color-mix(in srgb, ${presetColor} 30%, transparent)`
          : "0px 0px 0px rgba(0,0,0,0)",
      }}
    >
      {/* Icon */}
      <Icon
        size={22}
        className={active ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}
      />

      {/* Title + active dot + tooltip */}
      <div className="flex items-center gap-1.5 mt-2">
        <span
          className="w-2 h-2 rounded-full transition-all"
          style={{
            background: active ? presetColor : "var(--text-muted)",
            boxShadow: active ? `0 0 5px ${presetColor}` : "none",
          }}
        />
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
          {title}
        </h3>
        <PresetTooltip text={tooltip} color={presetColor} />
      </div>

      {/* Description */}
      <p className="text-[var(--text-secondary)] text-[11px] tracking-wide mt-1.5 leading-relaxed">
        {description}
      </p>

      {/* Genre tag */}
      <span
        className="inline-block mt-2 px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-widest"
        style={{
          background: active
            ? `color-mix(in srgb, ${presetColor} 18%, transparent)`
            : "var(--surface-hover)",
          color: active ? presetColor : "var(--text-muted)",
          border: active
            ? `1px solid ${presetColor}`
            : "1px solid var(--border-subtle)",
        }}
      >
        {genre}
      </span>
    </div>
  );
}

/* ── 3D Knob (same as before) ─────────────────────────── */

interface Knob3DProps {
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
}

function Knob3D({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  disabled,
  accent,
  size = 40,
}: Knob3DProps) {
  const dotColor = accent ?? "var(--accent-primary)";
  const pct = (value - min) / (max - min);
  const angle = -135 + pct * 270;
  const range = max - min;
  const sensitivity = 200;

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
      let newVal =
        Math.round((dragRef.current.startVal + deltaVal) / step) * step;
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
    <div className="flex flex-col items-center gap-1.5">
      {/* Knob body */}
      <div
        className={`relative select-none ${
          disabled
            ? "opacity-30 pointer-events-none"
            : "cursor-grab active:cursor-grabbing"
        }`}
        style={{ width: size, height: size }}
        onMouseDown={handleMouseDown}
      >
        {/* Outer ring */}
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "radial-gradient(circle at 35% 30%, var(--knob-gradient-1), var(--knob-gradient-2) 40%, var(--knob-gradient-3) 100%)",
            boxShadow:
              "var(--shadow-knob-inset), 0 0 0 1px var(--border-subtle), 0 2px 6px rgba(0,0,0,0.4)",
            border: "1px solid rgba(0,0,0,0.3)",
          }}
        />
        {/* Highlight */}
        <div
          className="absolute inset-[2px] rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle at 30% 25%, var(--knob-highlight), transparent 60%)",
          }}
        />
        {/* Center dimple */}
        <div
          className="absolute inset-[35%] rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, var(--knob-gradient-4), var(--knob-face-bottom))",
            boxShadow: "inset 0 1px 2px rgba(0,0,0,0.5)",
          }}
        />
        {/* LED indicator */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            transform: `rotate(${angle}deg)`,
            transition: "transform 0.08s ease-out",
          }}
        >
          <div
            className="absolute left-1/2 -translate-x-1/2 rounded-full"
            style={{
              top: "3px",
              width: "4px",
              height: "4px",
              background: dotColor,
              boxShadow: `0 0 6px ${dotColor}`,
            }}
          />
        </div>
      </div>

      <span className="text-[10px] text-[var(--text-secondary)] font-medium tracking-wide">
        {label}
      </span>
      <span className="text-[9px] font-mono text-[var(--text-muted)] tabular-nums leading-none">
        {value.toFixed(step < 1 ? 1 : 0)}
        {unit && <span className="text-[var(--text-muted)] ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}

/* ── Main Module Panel ────────────────────────────────── */

export default function ModulePanel({
  params,
  onChange,
  disabled,
  activePresetId,
  onPresetSelect,
}: ModulePanelProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [fineTuneOpen, setFineTuneOpen] = useState(false);

  /* Staggered entry animation for the card grid */
  useGSAP(
    () => {
      const grid = containerRef.current?.querySelector(".cards-grid");
      if (!grid) return;
      gsap.from(grid.children, {
        y: 30,
        opacity: 0,
        stagger: 0.04,
        duration: 0.45,
        ease: "power2.out",
        clearProps: "all",
      });
    },
    { scope: containerRef, dependencies: [] },
  );

  /* Preset select handler */
  const handlePresetClick = useCallback(
    (preset: MacroPreset) => {
      if (disabled) return;
      // If onPresetSelect is provided, use it (sets params + auto-processes)
      if (onPresetSelect) {
        onPresetSelect(preset.params, preset.id);
      } else {
        onChange(preset.params);
      }
    },
    [disabled, onChange, onPresetSelect],
  );

  /* Knob update helper */
  const update = useCallback(
    (key: keyof MasteringParameters, value: number) => {
      onChange({ ...params, [key]: value });
    },
    [params, onChange],
  );

  return (
    <div ref={containerRef} className="space-y-4">
      {/* ── Macro-Character Cards ──────────────────── */}
      <div className="cards-grid grid grid-cols-2 md:grid-cols-4 gap-3">
        {PRESETS.map((preset) => (
          <MacroCard
            key={preset.id}
            preset={preset}
            active={activePresetId === preset.id}
            onClick={() => handlePresetClick(preset)}
            disabled={disabled}
          />
        ))}
      </div>

      {/* ── Fine Tune (collapsible knobs) ──────────── */}
      <details
        open={fineTuneOpen}
        onToggle={(e) => setFineTuneOpen((e.target as HTMLDetailsElement).open)}
        className="group rounded-xl bg-[var(--surface-hover)] backdrop-blur-xl border border-[var(--border-subtle)] overflow-hidden transition-all duration-300"
      >
        <summary className="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-[var(--surface-hover)] transition-colors list-none select-none">
          <GripVertical size={14} className="text-[var(--text-muted)]" />
          <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
            {t("mastering.fineTune", "Ajuste Fino")}
          </span>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-[var(--text-muted)] ml-auto group-open:rotate-180 transition-transform duration-300"
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </summary>

        <div className="px-4 pb-5 pt-1">
          {/* Transparent mode: the creative knobs are inert (delivery-only).
              Banner + visual disable, layout untouched. */}
          {params.processing_mode === "transparent" && (
            <div
              className="mb-3 flex items-start gap-2 p-2.5 rounded-lg text-[10px] leading-relaxed"
              style={{
                background: "rgba(98, 126, 132, 0.08)",
                border: "1px solid rgba(98, 126, 132, 0.2)",
                color: "var(--accent-primary)",
              }}
            >
              <Info size={12} className="shrink-0 mt-0.5" />
              <span>
                {t("mastering.transparentWarning", "Modo transparente: las perillas creativas no se aplican — solo entrega (loudness / SRC / bit depth).")}
              </span>
            </div>
          )}

          <div
            className={`flex flex-wrap gap-5 justify-center items-start ${
              params.processing_mode === "transparent"
                ? "opacity-40 pointer-events-none select-none"
                : ""
            }`}
          >
            {/* Clarity */}
            <Knob3D
              label={t("mastering.knobs.reverb", "Reverb")}
              value={params.clarity_wet}
              min={0}
              max={1}
              step={0.05}
              unit="%"
              onChange={(v) => update("clarity_wet", v)}
              disabled={disabled}
            />
            <Knob3D
              label={t("mastering.knobs.brightness", "Brillo")}
              value={params.clarity_brightness_db}
              min={-6}
              max={6}
              step={0.5}
              unit="dB"
              onChange={(v) => update("clarity_brightness_db", v)}
              disabled={disabled}
            />

            {/* Dynamics */}
            <Knob3D
              label={t("analysis.ratio", "Ratio")}
              value={params.compression_ratio}
              min={1}
              max={10}
              step={0.5}
              unit=":1"
              onChange={(v) => update("compression_ratio", v)}
              disabled={disabled}
            />
            <Knob3D
              label={t("analysis.ceiling", "Ceiling")}
              value={params.limiter_ceiling_db}
              min={-3}
              max={0}
              step={0.1}
              unit="dB"
              onChange={(v) => update("limiter_ceiling_db", v)}
              disabled={disabled}
            />
            <Knob3D
              label={t("mastering.knobs.transients", "Punch")}
              value={params.transient_boost_db}
              min={0}
              max={6}
              step={0.5}
              unit="dB"
              onChange={(v) => update("transient_boost_db", v)}
              disabled={disabled}
            />

            {/* Saturation */}
            <Knob3D
              label={t("mastering.knobs.saturation", "Drive")}
              value={params.saturation_drive_db}
              min={0}
              max={10}
              step={0.5}
              unit="dB"
              onChange={(v) => update("saturation_drive_db", v)}
              disabled={disabled}
            />
            <Knob3D
              label={t("mastering.knobs.warmth", "Warmth")}
              value={params.saturation_warmth_db}
              min={-6}
              max={6}
              step={0.5}
              unit="dB"
              onChange={(v) => update("saturation_warmth_db", v)}
              disabled={disabled}
            />

            {/* Spatial */}
            <Knob3D
              label={t("mastering.knobs.stereoWidth", "Width")}
              value={params.stereo_width}
              min={0.5}
              max={2.0}
              step={0.1}
              unit="x"
              onChange={(v) => update("stereo_width", v)}
              disabled={disabled}
            />
            <Knob3D
              label={t("mastering.knobs.haasDelay", "Haas")}
              value={params.haas_delay_ms}
              min={0}
              max={40}
              step={1}
              unit="ms"
              onChange={(v) => update("haas_delay_ms", v)}
              disabled={disabled}
            />
          </div>
        </div>
      </details>
    </div>
  );
}
