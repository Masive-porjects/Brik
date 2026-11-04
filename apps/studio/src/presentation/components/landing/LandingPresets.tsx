"use client";

import { useTranslation } from "@/i18n";

/** Base profiles the engine combines; names come from the Studio dictionary. */
const BASE_PROFILE_IDS = ["universal", "cinta", "claridad", "espacial", "empuje", "natural"] as const;

/**
 * Profiles are presented as building blocks, not closed genres: the copy
 * stresses combinations that adapt to any style.
 */
export default function LandingPresets() {
  const { t } = useTranslation();

  return (
    <section id="perfiles" className="w-full bg-[var(--bg-app)] px-4 py-24 sm:px-8 lg:px-12 lg:py-32">
      <div className="mx-auto flex max-w-3xl flex-col items-center gap-10 text-center">
        <div className="flex flex-col gap-3">
          <h2 className="text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
            {t("landing.presets.title", "Perfiles de Masterización")}
          </h2>
          <p className="text-sm leading-relaxed text-[var(--text-secondary)] sm:text-base">
            {t(
              "landing.presets.subtitle",
              "Miles de combinaciones de mezcla y master, adaptables a cualquier estilo."
            )}
          </p>
        </div>

        <div className="flex w-full flex-col gap-4">
          <span className="text-xs font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            {t("landing.presets.chipsLabel", "Perfiles base")}
          </span>
          <ul className="flex flex-wrap justify-center gap-2.5">
            {BASE_PROFILE_IDS.map((id) => (
              <li
                key={id}
                className="rounded-full border border-[var(--border-subtle)] bg-[var(--bg-glass-elevated)] px-4 py-2 text-sm font-medium text-[var(--text-primary)]"
              >
                {t(`mastering.presets.${id}.name`)}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
