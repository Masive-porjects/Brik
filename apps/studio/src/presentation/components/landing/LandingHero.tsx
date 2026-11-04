"use client";

import Image from "next/image";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { useTranslation } from "@/i18n";
import { BASE_PATH } from "@/lib/basePath";

/**
 * Decorative brand ghosts. Positions are fixed so the server and client render
 * the same markup; the float is a slow loop that stops under reduced motion.
 */
const GHOSTS = [
  { position: "left-[4%] top-[14%] w-12 sm:w-20", duration: 7.5, delay: 0 },
  { position: "right-[5%] top-[30%] w-10 sm:w-16", duration: 9, delay: 1.2 },
  { position: "left-[12%] bottom-[8%] w-8 sm:w-12 hidden sm:block", duration: 8, delay: 2.4 },
] as const;

function FloatingGhosts() {
  const reduceMotion = useReducedMotion();

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      {GHOSTS.map((ghost) => (
        <motion.div
          key={ghost.position}
          className={`absolute opacity-40 ${ghost.position}`}
          animate={reduceMotion ? undefined : { y: [0, -14, 0], rotate: [0, -4, 0] }}
          transition={
            reduceMotion
              ? undefined
              : { duration: ghost.duration, delay: ghost.delay, repeat: Infinity, ease: "easeInOut" }
          }
        >
          <Image
            src={`${BASE_PATH}/brand/mascota-3d.webp`}
            alt=""
            width={96}
            height={96}
            className="h-auto w-full"
          />
        </motion.div>
      ))}
    </div>
  );
}

export default function LandingHero() {
  const { t } = useTranslation();

  return (
    <section
      id="hero"
      className="relative w-full overflow-hidden px-5 sm:px-8 lg:px-12 pt-36 sm:pt-44 lg:pt-48 pb-20 sm:pb-28"
    >
      <FloatingGhosts />

      <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-6 text-center sm:gap-8">
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
