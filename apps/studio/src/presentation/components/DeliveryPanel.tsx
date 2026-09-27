"use client";

import type { MasteringParameters } from "@/lib/api";
import PlatformSelector from "@/components/PlatformSelector";
import { useTranslation } from "@/i18n";

/* ── Delivery / Compliance Phase 1 (Entrega) ────────────────
   Controls the delivery chain: processing mode, platform target
   (mirroring loudness/ceiling into the params so the UI shows what
   the backend will apply), output sample rate and bit depth, and the
   strict-input QC toggle. The platform chip is reused only when the
   current platform_target is undefined or "custom" — i.e. when the
   loudness target is fully user-controlled. */

interface DeliveryPanelProps {
  params: MasteringParameters;
  onChange: (updater: (prev: MasteringParameters) => MasteringParameters) => void;
}

/** Known platform → (target_lufs_db, limiter_ceiling_db) — mirrors the
 *  backend's `_apply_platform_defaults` (models/audio.py). Exported so the
 *  preset merge in page.tsx re-applies the same values. */
export const PLATFORM_DEFAULTS: Record<
  "spotify" | "apple_music" | "youtube" | "tidal",
  { lufs: number; ceiling: number }
> = {
  spotify: { lufs: -14, ceiling: -1.0 },
  apple_music: { lufs: -16, ceiling: -1.0 },
  youtube: { lufs: -14, ceiling: -1.0 },
  tidal: { lufs: -14, ceiling: -1.0 },
};

const PLATFORM_OPTIONS: Array<{
  id: "automatic" | "custom" | "spotify" | "apple_music" | "youtube" | "tidal";
  label: string;
}> = [
  { id: "automatic", label: "Automático" },
  { id: "spotify", label: "Spotify" },
  { id: "apple_music", label: "Apple Music" },
  { id: "youtube", label: "YouTube" },
  { id: "tidal", label: "Tidal" },
  { id: "custom", label: "Personalizado" },
];

const SR_OPTIONS: Array<{ id: MasteringParameters["output_sr"]; label: string }> = [
  { id: "same_as_input", label: "Misma que la entrada" },
  { id: "44100", label: "44.1 kHz" },
  { id: "48000", label: "48 kHz" },
  { id: "96000", label: "96 kHz" },
];

export default function DeliveryPanel({ params, onChange }: DeliveryPanelProps) {
  const { t } = useTranslation();
  const set = (patch: Partial<MasteringParameters>) =>
    onChange((prev) => ({ ...prev, ...patch }));

  /* Pick a platform target. Known platforms mirror their delivery default
     into target_lufs_db + limiter_ceiling_db so the UI reflects exactly
     what the backend validator (`_apply_platform_defaults`) will apply.
     Automático clears the platform but leaves the knobs untouched;
     Personalizado just marks platform_target="custom". */
  const pickPlatform = (id: (typeof PLATFORM_OPTIONS)[number]["id"]) => {
    if (id === "automatic") return set({ platform_target: undefined });
    if (id === "custom") return set({ platform_target: "custom" });
    const defaults = PLATFORM_DEFAULTS[id];
    set({
      platform_target: id,
      target_lufs_db: defaults.lufs,
      limiter_ceiling_db: defaults.ceiling,
    });
  };

  const platformId: (typeof PLATFORM_OPTIONS)[number]["id"] =
    params.platform_target &&
    (params.platform_target === "custom" ||
      ["spotify", "apple_music", "youtube", "tidal"].includes(params.platform_target))
      ? params.platform_target
      : "automatic";

  const freePlatform =
    params.platform_target === undefined || params.platform_target === "custom";

  return (
    <div className="space-y-4">
      {/* ── Processing mode ─────────────────────────────────── */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span
            className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest"
            title='Creativo = cadena completa (mastering). Transparente = solo entrega (loudness/SRC/bit depth), no toca el timbre.'
          >
            {t("delivery.processingMode", "Modo de procesamiento")}
          </span>
        </div>
        <div className="relative grid grid-cols-2 bg-[var(--surface-hover)] rounded-full p-0.5">
          <div
            className="absolute top-0.5 bottom-0.5 left-0 rounded-full"
            style={{
              width: "calc((100% - 4px) / 2)",
              background: "var(--accent-primary)",
              opacity: 0.25,
              transform: `translateX(calc(${params.processing_mode === "master" ? 0 : 100}% + 2px))`,
              transition: "transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)",
            }}
          />
          <button
            type="button"
            title={t("delivery.creativeTooltip", "Cadena completa: ecualización, compresión, saturación, loudness.")}
            onClick={() => set({ processing_mode: "master" })}
            className={`relative z-10 px-2 py-1.5 rounded-full text-xs font-medium text-center transition-colors duration-200 ${
              params.processing_mode === "master"
                ? "text-[var(--accent-primary)]"
                : "text-[var(--text-muted)]"
            }`}
          >
            {t("delivery.creative", "Creativo")}
          </button>
          <button
            type="button"
            title={t("delivery.transparentTooltip", "Solo entrega: loudness (si hay target/plataforma), limiter, SRC y bit depth. No moldea el timbre.")}
            onClick={() => set({ processing_mode: "transparent" })}
            className={`relative z-10 px-2 py-1.5 rounded-full text-xs font-medium text-center transition-colors duration-200 ${
              params.processing_mode === "transparent"
                ? "text-[var(--accent-primary)]"
                : "text-[var(--text-muted)]"
            }`}
          >
            {t("delivery.transparent", "Transparente")}
          </button>
        </div>
      </div>

      {/* ── Delivery platform ──────────────────────────────── */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
            {t("delivery.platformTitle", "Plataforma de entrega")}
          </span>
          <span className="text-[9px] font-mono text-[var(--text-muted)] tabular-nums">
            {params.target_lufs_db === undefined
              ? "auto"
              : `\u2212${Math.abs(params.target_lufs_db)} LUFS`}
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {PLATFORM_OPTIONS.map((option) => {
            const active = platformId === option.id;
            const label =
              option.id === "automatic"
                ? t("delivery.automatic", "Automático")
                : option.id === "custom"
                  ? t("delivery.custom", "Personalizado")
                  : option.label;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => pickPlatform(option.id)}
                className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all duration-200 border ${
                  active
                    ? "text-[var(--accent-primary)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
                }`}
                style={{
                  background: active
                    ? "rgba(98, 126, 132, 0.08)"
                    : "var(--surface-hover)",
                  borderColor: active
                    ? "rgba(98, 126, 132, 0.25)"
                    : "var(--border-subtle)",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>

        {/* Loudness Target — reusable chip group, only when the user owns
            the loudness (Platform Automático / Personalizado). */}
        {freePlatform && (
          <div className="space-y-1.5">
            <p className="text-[9px] text-[var(--text-muted)] leading-relaxed">
              {t(
                "delivery.manualTweakNote",
                "Ajuste manual — aplica cuando la plataforma es Automático o Personalizado."
              )}
            </p>
            <PlatformSelector
              value={params.target_lufs_db}
              onChange={(t) => set({ target_lufs_db: t })}
            />
          </div>
        )}
      </div>

      {/* ── Output SR + bit depth ──────────────────────────── */}
      <div className="space-y-2">
        <span className="block text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
          {t("delivery.outputFormat", "Formato de salida")}
        </span>

        <div className="space-y-1">
          <span className="text-[9px] font-medium text-[var(--text-muted)] uppercase tracking-widest">
            {t("delivery.sampleRateLabel", "Sample rate")}
          </span>
          <div className="flex flex-wrap gap-1.5">
            {SR_OPTIONS.map((opt) => {
              const active = params.output_sr === opt.id;
              const label =
                opt.id === "same_as_input"
                  ? t("delivery.sameAsInput", "Misma que la entrada")
                  : opt.label;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => set({ output_sr: opt.id })}
                  className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all duration-200 border ${
                    active
                      ? "text-[var(--accent-primary)]"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
                  }`}
                  style={{
                    background: active
                      ? "rgba(98, 126, 132, 0.08)"
                      : "var(--surface-hover)",
                    borderColor: active
                      ? "rgba(98, 126, 132, 0.25)"
                      : "var(--border-subtle)",
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-1">
          <span className="text-[9px] font-medium text-[var(--text-muted)] uppercase tracking-widest">
            {t("delivery.bitDepthLabel", "Bit depth")}
          </span>
          <div className="flex flex-wrap gap-1.5">
            {([16, 24] as const).map((bits) => {
              const active = params.output_bit_depth === bits;
              return (
                <button
                  key={bits}
                  type="button"
                  onClick={() => set({ output_bit_depth: bits })}
                  className={`rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all duration-200 border ${
                    active
                      ? "text-[var(--accent-primary)]"
                      : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-active)]"
                  }`}
                  style={{
                    background: active
                      ? "rgba(98, 126, 132, 0.08)"
                      : "var(--surface-hover)",
                    borderColor: active
                      ? "rgba(98, 126, 132, 0.25)"
                      : "var(--border-subtle)",
                  }}
                >
                  {bits}-bit
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Strict QC ──────────────────────────────────────── */}
      <div
        className="flex items-center justify-between gap-3 rounded-xl px-3 py-2.5"
        style={{
          background: "var(--surface-hover)",
          border: "1px solid var(--border-subtle)",
        }}
      >
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-[var(--text-primary)]">
            {t("delivery.strictQc", "QC estricto")}
          </p>
          <p
            className="text-[9px] text-[var(--text-muted)] leading-relaxed"
            title="Rechaza material dañado (clipping / true peak alto) con error claro en vez de procesarlo."
          >
            {t("delivery.strictQcDesc", "Rechaza material dañado con error claro")}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={params.strict_mode}
          onClick={() => set({ strict_mode: !params.strict_mode })}
          title="Rechaza material dañado (clipping / true peak alto) con error claro en vez de procesarlo."
          className="relative shrink-0 w-10 h-6 rounded-full transition-colors duration-200"
          style={{
            background: params.strict_mode
              ? "var(--accent-primary)"
              : "var(--surface-active)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          <span
            className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200"
            style={{
              transform: params.strict_mode ? "translateX(1rem)" : "translateX(0)",
            }}
          />
        </button>
      </div>
    </div>
  );
}