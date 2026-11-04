"use client";

import { Check, Layers, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "@/i18n";
import DynamicsDiagram from "./DynamicsDiagram";

interface FeatureCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
}

function FeatureCard({ icon: Icon, title, description }: FeatureCardProps) {
  return (
    <article className="flex gap-4 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-glass-elevated)] p-5 sm:p-6">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div className="flex flex-col gap-1.5">
        <h3 className="text-base font-bold text-[var(--text-primary)]">{title}</h3>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{description}</p>
      </div>
    </article>
  );
}

const TECH_KEYS = [
  { key: "landing.benefits.tech.item1", fallback: "Procesamiento a 64-bit y cero alteración de fase" },
  { key: "landing.benefits.tech.item2", fallback: "Optimización multi-dispositivo (14 perfiles)" },
  { key: "landing.benefits.tech.item3", fallback: "Target EBU R128 (-14.0 LUFS)" },
] as const;

export default function LandingBenefits() {
  const { t } = useTranslation();

  return (
    <section id="beneficios" className="w-full bg-[var(--bg-app)] px-4 py-24 sm:px-8 lg:px-12 lg:py-32">
      <div className="mx-auto flex max-w-5xl flex-col gap-12">
        <header className="flex flex-col items-center gap-3 text-center">
          <h2 className="text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
            {t("landing.benefits.title", "Beneficios")}
          </h2>
          <p className="max-w-xl text-sm leading-relaxed text-[var(--text-secondary)] sm:text-base">
            {t(
              "landing.benefits.subtitle",
              "Brik escucha tu audio antes de procesarlo y solo aplica lo que necesita."
            )}
          </p>
        </header>

        <div className="grid grid-cols-1 items-stretch gap-6 lg:grid-cols-2">
          <div className="flex flex-col gap-6">
            <FeatureCard
              icon={Sparkles}
              title={t("landing.benefits.brik.title", "Brik, la IA detrás de tu master")}
              description={t(
                "landing.benefits.brik.desc",
                "Brik analiza el estado de salud de tu audio. Si hace falta, mezcla primero y luego masteriza; si no, aplica solo el master."
              )}
            />
            <FeatureCard
              icon={Layers}
              title={t("landing.benefits.stems.title", "Separación de stems")}
              description={t(
                "landing.benefits.stems.desc",
                "Separa tu mezcla en stems y mezcla cada canal por separado, para que cada elemento tenga su propio espacio."
              )}
            />
          </div>

          <figure className="flex flex-col gap-4 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-glass-elevated)] p-5 sm:p-6">
            <DynamicsDiagram
              normalLabel={t("landing.benefits.diagram.normal", "Audio normal")}
              masteredLabel={t("landing.benefits.diagram.mastered", "Audio masterizado")}
              dynamicRangeLabel={t("landing.benefits.diagram.dynamicRange", "Rango dinámico")}
              peakControlLabel={t("landing.benefits.diagram.peakControl", "Control de picos")}
              cleanSpaceLabel={t("landing.benefits.diagram.cleanSpace", "Espacio limpio")}
              ariaLabel={t(
                "landing.benefits.diagram.caption",
                "Dinámica de un audio sin procesar frente al mismo audio masterizado."
              )}
            />
            <figcaption className="text-center text-xs text-[var(--text-muted)]">
              {t(
                "landing.benefits.diagram.caption",
                "Dinámica de un audio sin procesar frente al mismo audio masterizado."
              )}
            </figcaption>
          </figure>
        </div>

        <div className="flex flex-col gap-5">
          <h3 className="text-center text-sm font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            {t("landing.benefits.tech.title", "Características técnicas")}
          </h3>
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {TECH_KEYS.map((item) => (
              <li key={item.key} className="flex items-start gap-2.5 text-sm leading-relaxed text-[var(--text-secondary)]">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                <span>{t(item.key, item.fallback)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
