"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "@/i18n";
import BigGhostWithNotes from "@/presentation/components/BigGhostWithNotes";

export default function LandingHero() {
  const { t } = useTranslation();

  return (
    <section
      id="hero"
      className="relative w-full overflow-hidden px-5 sm:px-8 lg:px-12 pt-36 sm:pt-44 lg:pt-48 pb-20 sm:pb-28"
    >
      <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-6 text-center sm:gap-8">
        {/* Same ghost-with-notes centerpiece as the upload screen. The space is
            reserved so the orbiting notes never overlap the title. */}
        <div className="flex h-40 w-full items-center justify-center sm:h-48">
          <BigGhostWithNotes size={72} radius={64} noteCount={6} />
        </div>

        <h1 className="text-balance text-4xl font-bold leading-tight tracking-tight text-[var(--text-primary)] sm:text-5xl lg:text-6xl">
          {t("landing.hero.title", "Masters profesionales en segundos.")}
        </h1>

        <p className="max-w-xl text-base leading-relaxed text-[var(--text-secondary)] sm:text-lg">
          {t(
            "landing.hero.subtitle",
            "Sube tu mezcla y obtén un sonido con pegada, dinámica y listo para plataformas de streaming. Sin dañar tu audio original."
          )}
        </p>

        <Link
          href="/upload"
          className="inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-primary px-8 py-4 font-semibold text-[var(--color-on-primary)] transition-colors hover:bg-primary-container focus-visible:ring-2 focus-visible:ring-primary/70 sm:w-auto"
        >
          <span>{t("landing.hero.ctaEnter", "Ingresar a Brik Studio")}</span>
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}
