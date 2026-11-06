"use client";

import { useState } from "react";
import { useTranslation } from "@/i18n";
import { PRESETS } from "@/presentation/components/ModulePanel";
import { PRESET_COLORS, DEFAULT_PRESET_COLOR } from "@/core/presets";

/**
 * Mastering profiles rendered as the same painted macro-cards used inside the
 * Studio mastering workspace (color-coded dot, border glow, description and
 * genre pill on a dark glass surface).
 */
export default function LandingPresets() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string>("universal");

  return (
    <section id="perfiles" className="w-full bg-[var(--bg-app)] px-4 py-24 sm:px-8 lg:px-12 lg:py-32">
      <div className="mx-auto flex max-w-5xl flex-col gap-10">
        <div className="mx-auto flex max-w-3xl flex-col items-center gap-3 text-center">
          <h2 className="text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
            {t("landing.presets.title", "Perfiles de Masterización")}
          </h2>
          <p className="text-sm leading-relaxed text-[var(--text-secondary)] sm:text-base">
            {t(
              "landing.presets.subtitle",
              "Miles de combinaciones de mezcla y master, adaptables a cualquier estilo. La IA elige la ruta según tu audio, sin encasillarlo en un género."
            )}
          </p>
        </div>

        <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PRESETS.map((preset) => {
            const Icon = preset.icon;
            const presetColor = PRESET_COLORS[preset.id]?.wave ?? DEFAULT_PRESET_COLOR.wave;
            const active = selectedId === preset.id;

            const title = t(`mastering.presets.${preset.id}.name`, preset.title);
            const description = t(`mastering.presets.${preset.id}.description`, preset.description);
            const genre = t(`mastering.presets.${preset.id}.genre`, preset.genre);

            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => setSelectedId(preset.id)}
                aria-pressed={active}
                className="flex flex-col items-start rounded-xl p-4 text-left select-none cursor-pointer transition-all duration-300"
                style={{
                  background: active
                    ? `color-mix(in srgb, ${presetColor} 10%, var(--bg-glass-elevated))`
                    : "var(--bg-glass-elevated)",
                  backdropFilter: "blur(16px)",
                  WebkitBackdropFilter: "blur(16px)",
                  border: active
                    ? `1px solid ${presetColor}`
                    : `1px solid color-mix(in srgb, ${presetColor} 35%, transparent)`,
                  boxShadow: active
                    ? `0px 0px 20px color-mix(in srgb, ${presetColor} 28%, transparent)`
                    : "none",
                }}
              >
                <span style={{ color: `color-mix(in srgb, ${presetColor} var(--preset-ink-strength), #000)` }} aria-hidden="true">
                  <Icon size={18} />
                </span>

                <div className="mt-2.5 flex items-center gap-2">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{
                      background: presetColor,
                      boxShadow: `0 0 6px ${presetColor}`,
                    }}
                  />
                  <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                    {title}
                  </h3>
                </div>

                <p className="mt-1.5 flex-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                  {description}
                </p>

                <span
                  className="mt-3 inline-block rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-widest"
                  style={{
                    background: `color-mix(in srgb, ${presetColor} 16%, transparent)`,
                    color: `color-mix(in srgb, ${presetColor} var(--preset-ink-strength), #000)`,
                    border: `1px solid color-mix(in srgb, ${presetColor} 45%, transparent)`,
                  }}
                >
                  {genre}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
