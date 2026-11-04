"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "@/i18n";

export default function LandingHero() {
  const { t } = useTranslation();

  return (
    <section
      id="hero"
      className="w-full px-4 sm:px-8 lg:px-12 pt-40 lg:pt-48 pb-24 lg:pb-32"
    >
      <div className="max-w-3xl mx-auto flex flex-col items-center text-center gap-8">
        <h1 className="font-sans text-4xl sm:text-5xl lg:text-6xl font-bold leading-tight tracking-tight text-[var(--text-primary)] text-balance">
          {t("landing.hero.title", "Masters profesionales en segundos.")}
        </h1>

        <p className="font-sans text-base sm:text-lg leading-relaxed text-[var(--text-secondary)] max-w-xl">
          {t(
            "landing.hero.subtitle",
            "Sube tu mezcla y obtén un sonido con pegada, dinámica y listo para plataformas de streaming. Sin dañar tu audio original."
          )}
        </p>

        <Link
          href="/upload"
          className="inline-flex items-center justify-center gap-2 min-h-[44px] px-8 py-4 rounded-full bg-primary text-[var(--color-on-primary)] font-semibold hover:bg-primary-container transition-colors focus-visible:ring-2 focus-visible:ring-primary/70"
        >
          <span>{t("landing.hero.ctaEnter", "Probar Brik Studio")}</span>
          <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}
