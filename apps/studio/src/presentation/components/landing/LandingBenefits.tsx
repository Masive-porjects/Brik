"use client";

import { Check } from "lucide-react";
import { useTranslation } from "@/i18n";

const BENEFIT_KEYS = [
  { key: "landing.benefits.item1", fallback: "Procesamiento a 64-bit y cero alteración de fase" },
  { key: "landing.benefits.item2", fallback: "Optimización multi-dispositivo (14 perfiles)" },
  { key: "landing.benefits.item3", fallback: "Target EBU R128 (-14.0 LUFS)" },
] as const;

/** Compact technical summary. The full DSP detail is intentionally not shown. */
export default function LandingBenefits() {
  const { t } = useTranslation();

  return (
    <section
      id="beneficios"
      className="w-full py-24 lg:py-32 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)]"
    >
      <div className="max-w-2xl mx-auto flex flex-col gap-10">
        <h2 className="text-2xl sm:text-3xl font-bold text-[var(--text-primary)] text-center">
          {t("landing.benefits.title", "Características técnicas")}
        </h2>

        <ul className="flex flex-col gap-5">
          {BENEFIT_KEYS.map((item) => (
            <li key={item.key} className="flex items-start gap-3">
              <Check className="w-5 h-5 mt-0.5 flex-shrink-0 text-primary" aria-hidden="true" />
              <span className="text-base leading-relaxed text-[var(--text-secondary)]">
                {t(item.key, item.fallback)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
