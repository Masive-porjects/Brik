"use client";

import { useRef } from "react";
import { useTranslation } from "@/i18n";
import { useTaglineReveal } from "@/hooks/useTaglineReveal";

/**
 * Manifesto tagline — a deliberate pause between the preset catalogue and the
 * pricing plans. The statement lights up word by word on scroll (GSAP
 * `SplitText` + scrubbed `ScrollTrigger`), driven by `useTaglineReveal`.
 *
 * The section owns a single ref; the hook discovers the `data-tagline` and
 * `data-tagline-deco` nodes inside its effect. With reduced motion, or if
 * JavaScript never runs, the statement renders at full opacity.
 */
export default function LandingTagline() {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLElement>(null);
  useTaglineReveal(containerRef);

  return (
    <section
      id="manifiesto"
      ref={containerRef}
      className="w-full py-20 sm:py-28 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] relative overflow-hidden border-y border-white/[0.04]"
    >
      {/* Ambient spectral bloom behind the statement — brightened on scroll */}
      <div
        data-tagline-deco
        aria-hidden="true"
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[720px] h-[360px] max-w-[92vw] rounded-full bg-primary/10 blur-[140px] pointer-events-none opacity-50"
      />

      <div className="max-w-[1440px] mx-auto relative z-10">
        <div className="flex flex-col items-center text-center gap-5 mx-auto max-w-4xl">
          <span className="font-label-technical text-primary text-[10px] uppercase tracking-widest">
            {t("landing.tagline.eyebrow", "Manifiesto")}
          </span>
          <h2
            data-tagline
            className="font-display-xl text-2xl sm:text-4xl lg:text-5xl tracking-tight text-[#e3e2e8]"
          >
            {t(
              "landing.tagline.statement",
              "Un master no es magia: es física aplicada con precisión. Trece etapas, cero adivinanzas, tu música intacta."
            )}
          </h2>
        </div>
      </div>
    </section>
  );
}
