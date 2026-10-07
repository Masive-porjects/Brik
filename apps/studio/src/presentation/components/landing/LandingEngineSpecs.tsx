"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Cpu,
  Gauge,
  Activity,
  Radio,
  ShieldCheck,
  Zap,
  Layers,
  Filter,
  SlidersHorizontal,
  Box,
  Disc,
  Speaker,
  Grid,
  ChevronDown,
  CheckCircle2,
  ExternalLink,
} from "lucide-react";
import { useTranslation } from "@/i18n";
import { InteractiveCard } from "./InteractiveCard";
import { transitions } from "@/shared/lib/animations";

const ICONS_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Cpu,
  Gauge,
  Activity,
  Radio,
  Zap,
  Layers,
  Filter,
  SlidersHorizontal,
  Box,
  Disc,
  Speaker,
  Grid,
};

interface SpecItem {
  label: string;
  value: string;
  description?: string;
}

interface SpecCategory {
  id: string;
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  color: "primary" | "secondary" | "tertiary";
  specs: SpecItem[];
}

export default function LandingEngineSpecs() {
  const { t } = useTranslation();
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);

  const categories: SpecCategory[] = [
    {
      id: "dsp-core",
      title: "landing.specs.dspCore.title",
      icon: Cpu,
      color: "primary",
      specs: [
        { label: "landing.specs.dspCore.spec1.label", value: "landing.specs.dspCore.spec1.value", description: "landing.specs.dspCore.spec1.desc" },
        { label: "landing.specs.dspCore.spec2.label", value: "landing.specs.dspCore.spec2.value", description: "landing.specs.dspCore.spec2.desc" },
        { label: "landing.specs.dspCore.spec3.label", value: "landing.specs.dspCore.spec3.value", description: "landing.specs.dspCore.spec3.desc" },
        { label: "landing.specs.dspCore.spec4.label", value: "landing.specs.dspCore.spec4.value", description: "landing.specs.dspCore.spec4.desc" },
        { label: "landing.specs.dspCore.spec5.label", value: "landing.specs.dspCore.spec5.value", description: "landing.specs.dspCore.spec5.desc" },
      ],
    },
    {
      id: "target-loudness",
      title: "landing.specs.loudness.title",
      icon: Gauge,
      color: "secondary",
      specs: [
        { label: "landing.specs.loudness.spec1.label", value: "landing.specs.loudness.spec1.value", description: "landing.specs.loudness.spec1.desc" },
        { label: "landing.specs.loudness.spec2.label", value: "landing.specs.loudness.spec2.value", description: "landing.specs.loudness.spec2.desc" },
        { label: "landing.specs.loudness.spec3.label", value: "landing.specs.loudness.spec3.value", description: "landing.specs.loudness.spec3.desc" },
        { label: "landing.specs.loudness.spec4.label", value: "landing.specs.loudness.spec4.value", description: "landing.specs.loudness.spec4.desc" },
      ],
    },
    {
      id: "spatial-haas",
      title: "landing.specs.spatial.title",
      icon: Radio,
      color: "tertiary",
      specs: [
        { label: "landing.specs.spatial.spec1.label", value: "landing.specs.spatial.spec1.value", description: "landing.specs.spatial.spec1.desc" },
        { label: "landing.specs.spatial.spec2.label", value: "landing.specs.spatial.spec2.value", description: "landing.specs.spatial.spec2.desc" },
        { label: "landing.specs.spatial.spec3.label", value: "landing.specs.spatial.spec3.value", description: "landing.specs.spatial.spec3.desc" },
        { label: "landing.specs.spatial.spec4.label", value: "landing.specs.spatial.spec4.value", description: "landing.specs.spatial.spec4.desc" },
      ],
    },
    {
      id: "pipeline-quality",
      title: "landing.specs.pipeline.title",
      icon: ShieldCheck,
      color: "primary",
      specs: [
        { label: "landing.specs.pipeline.spec1.label", value: "landing.specs.pipeline.spec1.value", description: "landing.specs.pipeline.spec1.desc" },
        { label: "landing.specs.pipeline.spec2.label", value: "landing.specs.pipeline.spec2.value", description: "landing.specs.pipeline.spec2.desc" },
        { label: "landing.specs.pipeline.spec3.label", value: "landing.specs.pipeline.spec3.value", description: "landing.specs.pipeline.spec3.desc" },
        { label: "landing.specs.pipeline.spec4.label", value: "landing.specs.pipeline.spec4.value", description: "landing.specs.pipeline.spec4.desc" },
      ],
    },
  ];

  return (
    <section id="especificaciones-motor" className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] border-y border-white/[0.04] relative overflow-x-hidden">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.15 }}
          transition={transitions.scrollReveal}
          className="flex flex-col md:flex-row md:items-end justify-between gap-6"
        >
          <div className="flex flex-col gap-2 max-w-2xl">
            <span className="font-label-technical text-primary text-[10px] uppercase tracking-widest">
              {t("landing.specs.badge", "Especificaciones del Motor DSP")}
            </span>
            <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
              {t("landing.specs.title", "Arquitectura Técnica Detallada")}
            </h2>
            <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
              {t("landing.specs.subtitle", "Todos los parámetros, métricas y capacidades del motor de 13 etapas en un solo lugar.")}
            </p>
          </div>

          <div className="font-label-technical text-xs text-[#bcc9c7] bg-[#1a1b20] border border-white/5 px-4 py-2 rounded-lg flex items-center gap-2.5 self-start md:self-auto shadow-sm">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            <span>{t("landing.specs.liveBadge", "Motor v3.4 Activo")}</span>
          </div>
        </motion.div>

        {/* Categories Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 items-stretch">
          {categories.map((category, idx) => {
            const Icon = category.icon;
            const isExpanded = expandedCategory === category.id;

            return (
              <InteractiveCard
                key={category.id}
                index={idx}
                isExpanded={isExpanded}
                glowColor={category.color}
                disableHoverOnMobile
              >
                <div className="flex flex-col gap-5 relative z-10 flex-1">
                  <motion.div
                    whileHover={{ scale: 1.05, rotate: 2 }}
                    transition={transitions.cardHover}
                    className="w-12 h-12 rounded-xl bg-[#292a2e] border border-white/5 flex items-center justify-center text-primary shadow-sm group-hover:border-primary/30 transition-colors"
                  >
                    <Icon className="w-6 h-6" />
                  </motion.div>

                  <div className="flex flex-col gap-1.5">
                    <span className="font-label-technical text-[10px] text-primary uppercase tracking-wider">
                      {t("landing.specs.categoryLabel", "MÓDULO")}
                    </span>
                    <h3 className="font-headline-sm text-lg sm:text-xl font-bold text-[#e3e2e8] min-h-[3rem] flex items-center">
                      {t(category.title)}
                    </h3>
                  </div>

                  {/* Preview specs (first 2) */}
                  <div className="flex flex-col gap-2 flex-1">
                    {category.specs.slice(0, 2).map((spec, sIdx) => (
                      <motion.div
                        key={spec.label}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2, delay: 0.05 * sIdx }}
                        className="flex items-center gap-2 text-xs text-[#bcc9c7]"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 text-primary shrink-0" />
                        <span className="font-body-sm text-[11px]">
                          <span className="text-[#e3e2e8] font-bold">{t(spec.label)}:</span> {t(spec.value)}
                        </span>
                      </motion.div>
                    ))}
                    {category.specs.length > 2 && (
                      <motion.div
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2, delay: 0.1 }}
                        className="font-label-technical text-[10px] text-primary flex items-center gap-1 cursor-pointer"
                        onClick={() => setExpandedCategory(isExpanded ? null : category.id)}
                      >
                        <span>{t("landing.specs.showMore")} +{category.specs.length - 2}</span>
                        <motion.div animate={{ rotate: isExpanded ? 180 : 0 }} transition={{ duration: 0.25 }}>
                          <ChevronDown className="w-3.5 h-3.5" />
                        </motion.div>
                      </motion.div>
                    )}
                  </div>
                </div>

                <div className="pt-6 mt-auto border-t border-white/5 flex flex-col gap-3 relative z-10">
                  <motion.button
                    type="button"
                    onClick={() => setExpandedCategory(isExpanded ? null : category.id)}
                    whileHover={{ backgroundColor: "#292a2e" }}
                    whileTap={{ scale: 0.99 }}
                    transition={transitions.cardHover}
                    className="w-full py-1.5 px-3 rounded-lg bg-[#292a2e]/60 hover:bg-[#292a2e] border border-white/5 hover:border-white/10 text-[#bcc9c7] hover:text-[#e3e2e8] font-label-technical text-[10px] flex items-center justify-between transition-colors cursor-pointer"
                  >
                    <span>
                      {isExpanded
                        ? t("landing.specs.hideSpecs", "Ocultar detalles")
                        : t("landing.specs.viewSpecs", "Ver especificaciones completas")}
                    </span>
                    <motion.div animate={{ rotate: isExpanded ? 180 : 0 }} transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}>
                      <ChevronDown className="w-3.5 h-3.5" />
                    </motion.div>
                  </motion.button>

                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={transitions.presence}
                        className="overflow-hidden flex flex-col gap-2 pt-2"
                      >
                        {category.specs.map((spec, sIdx) => (
                          <motion.div
                            key={spec.label}
                            initial={{ opacity: 0, x: -8 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: 8 }}
                            transition={{ duration: 0.2, delay: 0.05 * sIdx }}
                            className="flex flex-col gap-1 p-3 bg-[#292a2e] rounded-lg border border-white/5"
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-label-technical text-xs text-primary font-bold">{t(spec.label)}</span>
                              <span className="font-label-technical text-xs text-[#e3e2e8] font-bold">{t(spec.value)}</span>
                            </div>
                            {spec.description && (
                              <p className="font-body-sm text-[11px] text-[#bcc9c7] leading-relaxed">
                                {t(spec.description)}
                              </p>
                            )}
                          </motion.div>
                        ))}
                        <motion.div
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.2, delay: 0.1 }}
                          className="pt-2 border-t border-white/5 flex items-center justify-center gap-2"
                        >
                          <ExternalLink className="w-4 h-4 text-[#869391]" />
                          <span className="font-label-technical text-xs text-[#869391]">
                            {t("landing.specs.viewDocs", "Ver documentación técnica completa")}
                          </span>
                        </motion.div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </InteractiveCard>
            );
          })}
        </div>
      </div>
    </section>
  );
}