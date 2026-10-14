"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Building2, Check, Music2, Sparkle } from "lucide-react";
import { useTranslation } from "@/i18n";
import { PRICING_PLANS } from "./data";
import { InteractiveCard } from "./InteractiveCard";
import { transitions } from "@/shared/lib/animations";
import type { AccentToken } from "./types";

const PLAN_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "pay-per-song": Music2,
  credits: Building2,
};

const ACCENT_TEXT: Record<AccentToken, string> = {
  primary: "text-primary",
  secondary: "text-secondary",
  tertiary: "text-tertiary-container",
};

export default function LandingPricing() {
  const { t } = useTranslation();

  return (
    <section
      id="precios"
      className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)] relative overflow-x-hidden"
    >
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section header — same staggered reveal as the other landing sections */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.15 }}
          transition={transitions.scrollReveal}
          className="flex flex-col gap-2 max-w-2xl"
        >
          <span className="font-label-technical text-primary text-[10px] uppercase tracking-widest">
            {t("landing.pricing.badge", "Estructura Comercial")}
          </span>
          <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[var(--text-primary)] font-bold">
            {t("landing.pricing.title", "Precios claros, sin sorpresas")}
          </h2>
          <p className="font-body-md text-[var(--text-secondary)] text-sm sm:text-base leading-relaxed">
            {t(
              "landing.pricing.subtitle",
              "Paga por canción cuando lo necesites o compra créditos para tu estudio o sello. Sin suscripciones obligatorias ni cargos ocultos."
            )}
          </p>
        </motion.div>

        {/* Offers — stacked cards on mobile, 2-up on desktop */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch max-w-4xl">
          {PRICING_PLANS.map((plan, idx) => {
            const Icon = PLAN_ICONS[plan.id] ?? Music2;
            const accentText = ACCENT_TEXT[plan.accent];

            return (
              <InteractiveCard key={plan.id} index={idx} glowColor={plan.accent} disableHoverOnMobile>
                <div className="flex flex-col gap-6 flex-1">
                  {/* Offer identity + featured badge */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className="w-11 h-11 rounded-xl bg-[var(--surface-hover)] border border-[var(--border-subtle)] flex items-center justify-center flex-shrink-0">
                        <Icon className={`w-5 h-5 ${accentText}`} />
                      </span>
                      <div className="flex flex-col">
                        <span className="font-label-technical text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
                          {t(plan.nameKey)}
                        </span>
                        <span className="font-body-sm text-xs text-[var(--text-primary)] font-semibold">
                          {t(plan.taglineKey)}
                        </span>
                      </div>
                    </div>
                    {plan.highlighted && (
                      <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-primary/15 text-primary border border-primary/30 font-label-technical text-[9px] uppercase tracking-wider whitespace-nowrap flex-shrink-0">
                        <Sparkle className="w-3 h-3" />
                        {t("landing.pricing.featuredBadge", "Más elegido")}
                      </span>
                    )}
                  </div>

                  {/* Price — amount + currency + translated unit suffix */}
                  <div className="flex items-baseline gap-1.5">
                    <span className="font-label-technical text-sm text-[var(--text-muted)]">{plan.currency}</span>
                    <span className="font-display-xl text-4xl sm:text-5xl font-bold text-[var(--text-primary)] tracking-tight leading-none">
                      {plan.price}
                    </span>
                    <span className="font-body-sm text-xs text-[var(--text-muted)]">{t(plan.unitKey)}</span>
                  </div>

                  {/* Feature bullets */}
                  <ul className="flex flex-col gap-2.5 flex-1">
                    {plan.featureKeys.map((featureKey) => (
                      <li key={featureKey} className="flex items-start gap-2.5">
                        <Check className={`w-4 h-4 mt-0.5 flex-shrink-0 ${accentText}`} />
                        <span className="font-body-sm text-xs text-[var(--text-secondary)] leading-relaxed">
                          {t(featureKey)}
                        </span>
                      </li>
                    ))}
                  </ul>

                  {/* CTA — the featured offer gets the filled brand button */}
                  <Link
                    href={plan.ctaHref}
                    className={`w-full py-3 px-4 rounded-xl font-body-md font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98] ${
                      plan.highlighted
                        ? "bg-primary text-[var(--color-on-primary)] hover:bg-primary-container shadow-[0_0_20px_rgba(110,233,224,0.35)]"
                        : "bg-[var(--surface-active)] text-[var(--text-primary)] border border-[var(--border-subtle)] hover:bg-[var(--surface-hover)]"
                    }`}
                  >
                    <span>{t(plan.ctaKey)}</span>
                    <ArrowRight className="w-4 h-4" />
                  </Link>
                </div>
              </InteractiveCard>
            );
          })}
        </div>

        {/* Honest note: these are not the final commercial numbers yet. */}
        <p className="font-label-technical text-[10px] text-[var(--text-muted)]/80 max-w-4xl">
          {t(
            "landing.pricing.disclaimer",
            "Precios de referencia: se confirmarán al habilitar el pago."
          )}
        </p>
      </div>
    </section>
  );
}
