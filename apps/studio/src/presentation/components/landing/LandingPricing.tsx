"use client";

import { useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check, ChevronDown, Layers } from "lucide-react";
import { useTranslation } from "@/i18n";
import { easings, transitions } from "@/shared/lib/animations";

/**
 * Value-first plans panel. Prices are intentionally not shown: the section
 * explains what the user gets (WAV delivery, batch albums) behind a disclosure.
 */
export default function LandingPricing() {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const panelId = "pricing-details";

  return (
    <section id="precios" className="w-full bg-[var(--bg-app)] px-4 py-24 sm:px-8 lg:px-12 lg:py-32">
      <div className="mx-auto flex max-w-2xl flex-col items-center gap-8 text-center">
        <div className="flex flex-col gap-3">
          <h2 className="text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
            {t("landing.pricing.title", "Planes y entrega")}
          </h2>
          <p className="text-sm leading-relaxed text-[var(--text-secondary)] sm:text-base">
            {t(
              "landing.pricing.subtitle",
              "Mezcla y master de canciones sueltas o de álbumes completos, a tu ritmo."
            )}
          </p>
        </div>

        <div className="w-full overflow-hidden rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-glass-elevated)] text-left">
          <button
            type="button"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => setIsOpen((open) => !open)}
            className="flex min-h-[56px] w-full items-center justify-between gap-4 px-5 py-4 text-base font-semibold text-[var(--text-primary)] transition-colors hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/70 sm:px-6"
          >
            <span>{isOpen ? t("landing.pricing.toggleClose", "Ocultar detalles") : t("landing.pricing.toggleOpen", "Descubre nuestros planes")}</span>
            <motion.span
              animate={{ rotate: isOpen ? 180 : 0 }}
              transition={{ duration: 0.25, ease: easings.power2Out }}
              className="shrink-0"
              aria-hidden="true"
            >
              <ChevronDown className="h-5 w-5 text-primary" />
            </motion.span>
          </button>

          <AnimatePresence initial={false}>
            {isOpen && (
              <motion.div
                id={panelId}
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={transitions.presence}
                className="overflow-hidden"
              >
                <div className="flex flex-col gap-5 px-5 pb-6 sm:px-6">
                  <p className="flex items-start gap-2.5 text-sm leading-relaxed text-[var(--text-secondary)]">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                    <span>{t("landing.pricing.delivery", "Entrega final en formato WAV original.")}</span>
                  </p>

                  <div className="flex gap-4 rounded-xl border border-primary/30 bg-primary/10 p-4 sm:p-5">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
                      <Layers className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <p className="text-sm font-semibold leading-relaxed text-[var(--text-primary)]">
                      {t(
                        "landing.pricing.batch",
                        "Carga de álbumes completos y procesamiento por lotes (Mezcla y Master de múltiples tracks a la vez)."
                      )}
                    </p>
                  </div>

                  <Link
                    href="/upload"
                    className="inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 font-semibold text-[var(--color-on-primary)] transition-colors hover:bg-primary-container focus-visible:ring-2 focus-visible:ring-primary/70"
                  >
                    <span>{t("landing.pricing.cta", "Ingresar a Brik Studio")}</span>
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
