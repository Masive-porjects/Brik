"use client";

import { useTranslation } from "@/i18n";
import { PRESETS_LIST } from "./data";

/** Mastering profiles as clean, static cards. Details live in Studio. */
export default function LandingPresets() {
  const { t } = useTranslation();

  return (
    <section
      id="perfiles"
      className="w-full py-24 lg:py-32 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)]"
    >
      <div className="max-w-[1200px] mx-auto flex flex-col gap-12">
        <div className="flex flex-col gap-3 max-w-2xl">
          <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text-primary)]">
            {t("landing.presets.title", "Perfiles de Masterización")}
          </h2>
          <p className="text-base leading-relaxed text-[var(--text-secondary)]">
            {t(
              "landing.presets.subtitle",
              "Un punto de partida para cada género. Elige un perfil y ajústalo en Studio."
            )}
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {PRESETS_LIST.map((preset) => (
            <article
              key={preset.id}
              className="flex flex-col gap-3 p-6 rounded-2xl bg-[var(--bg-glass-elevated)] border border-[var(--border-subtle)]"
            >
              <h3 className="text-lg font-bold text-[var(--text-primary)]">
                {t(`landing.presets.${preset.id}.title`)}
              </h3>
              <p className="text-sm leading-relaxed text-[var(--text-secondary)] flex-1">
                {t(`landing.presets.${preset.id}.desc`)}
              </p>
              <span className="text-xs font-semibold text-primary">
                {t(`landing.presets.${preset.id}.metric`)}
              </span>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
