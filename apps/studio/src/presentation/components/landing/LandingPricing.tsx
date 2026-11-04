"use client";

import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";
import { useTranslation } from "@/i18n";
import { PRICING_PLANS } from "./data";

/** Two plain offers side by side. One accent color is used, only for the CTA. */
export default function LandingPricing() {
  const { t } = useTranslation();

  return (
    <section
      id="precios"
      className="w-full py-24 lg:py-32 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)]"
    >
      <div className="max-w-[1000px] mx-auto flex flex-col gap-12">
        <div className="flex flex-col gap-3 max-w-2xl">
          <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text-primary)]">
            {t("landing.pricing.title", "Precios claros, sin sorpresas")}
          </h2>
          <p className="text-base leading-relaxed text-[var(--text-secondary)]">
            {t(
              "landing.pricing.subtitle",
              "Paga por canción o compra créditos para tu estudio o sello."
            )}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {PRICING_PLANS.map((plan) => (
            <div
              key={plan.id}
              className="flex flex-col gap-6 p-8 rounded-2xl bg-[var(--bg-glass-elevated)] border border-[var(--border-subtle)]"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <h3 className="text-lg font-bold text-[var(--text-primary)]">{t(plan.nameKey)}</h3>
                  <span className="text-sm text-[var(--text-secondary)]">{t(plan.taglineKey)}</span>
                </div>
                {plan.highlighted && (
                  <span className="px-2.5 py-1 rounded-full bg-primary/15 text-primary text-xs font-semibold whitespace-nowrap">
                    {t("landing.pricing.featuredBadge", "Más elegido")}
                  </span>
                )}
              </div>

              <div className="flex items-baseline gap-1.5">
                <span className="text-sm text-[var(--text-muted)]">{plan.currency}</span>
                <span className="text-5xl font-bold tracking-tight leading-none text-[var(--text-primary)]">
                  {plan.price}
                </span>
                <span className="text-sm text-[var(--text-muted)]">{t(plan.unitKey)}</span>
              </div>

              <ul className="flex flex-col gap-3 flex-1">
                {plan.featureKeys.map((featureKey) => (
                  <li key={featureKey} className="flex items-start gap-2.5">
                    <Check className="w-4 h-4 mt-0.5 flex-shrink-0 text-primary" aria-hidden="true" />
                    <span className="text-sm leading-relaxed text-[var(--text-secondary)]">
                      {t(featureKey)}
                    </span>
                  </li>
                ))}
              </ul>

              <Link
                href={plan.ctaHref}
                className={`min-h-[44px] flex items-center justify-center gap-2 px-4 py-3 rounded-xl font-semibold transition-colors ${
                  plan.highlighted
                    ? "bg-primary text-[var(--color-on-primary)] hover:bg-primary-container"
                    : "border border-[var(--border-subtle)] text-[var(--text-primary)] hover:bg-[var(--surface-hover)]"
                }`}
              >
                <span>{t(plan.ctaKey)}</span>
                <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </Link>
            </div>
          ))}
        </div>

        <p className="text-xs text-[var(--text-muted)]">
          {t("landing.pricing.disclaimer", "Precios de referencia: se confirmarán al habilitar el pago.")}
        </p>
      </div>
    </section>
  );
}
