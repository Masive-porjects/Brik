"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Radio, ShieldCheck, ChevronDown, CheckCircle2 } from "lucide-react";
import { useTranslation } from "@/i18n";
import { InteractiveCard } from "./InteractiveCard";
import { transitions, easings } from "@/shared/lib/animations";

export default function LandingPhilosophy() {
  const { t } = useTranslation();
  const [expandedCard, setExpandedCard] = useState<string | null>(null);

  const cards = [
    {
      fenomeno: t("landing.philosophy.card1.tag", "Fenómeno 01"),
      title: t("landing.philosophy.card1.title", "El Fantasma de la Mezcla Plana"),
      desc: t(
        "landing.philosophy.card1.desc",
        "Las mezclas convencionales mueren en cajas bidimensionales sofocadas por transitorios sofocados y subgraves desalineados. Brik resucita el micro-contraste dinámico recuperando la respiración original que el limitador genérico aplasta."
      ),
      metricLabel: t("landing.philosophy.card1.metricLabel", "RESURRECCIÓN ARMÓNICA"),
      metricVal: t("landing.philosophy.card1.metricVal", "2.4x DINÁMICA"),
      icon: Activity,
      glowColor: "primary" as const,
      technicalPoints: [
        "Filtro FIR Fase Lineal con 8x oversampling",
        "Recuperador de micro-transitorios en paralelo",
        "Techo True Peak de -1.0 dBTP intersample seguro",
        "Pipeline Rust SIMD nativo a 64 bits",
      ],
    },
    {
      fenomeno: t("landing.philosophy.card2.tag", "Fenómeno 02"),
      title: t("landing.philosophy.card2.title", "Mid/Side Decorrelacionada"),
      desc: t(
        "landing.philosophy.card2.desc",
        "El canal central conserva la contundencia matemática del bombo y la voz principal, mientras que los flancos laterales se expanden espectralmente sin inducir cancelaciones de fase al reproducirse en sistemas monoaurales de club."
      ),
      metricLabel: t("landing.philosophy.card2.metricLabel", "COHERENCIA MONO"),
      metricVal: t("landing.philosophy.card2.metricVal", "100% PROTEGIDA"),
      icon: Radio,
      glowColor: "secondary" as const,
      technicalPoints: [
        "Matriz Suma/Diferencia decorrelacionada",
        "Bloque espacial Haas psicoacústico de 4-16 ms",
        "Side High-Pass a 120 Hz para limpieza subgrave",
        "Compatibilidad mono 100% libre de filtrado peine",
      ],
    },
    {
      fenomeno: t("landing.philosophy.card3.tag", "Fenómeno 03"),
      title: t("landing.philosophy.card3.title", "Validación de Ultratumba"),
      desc: t(
        "landing.philosophy.card3.desc",
        "Cada renderizado es sometido a un análisis espectro-temporal que simula 14 entornos de escucha reales: desde monitores de estudio estocásticos hasta altavoces de teléfonos y transductores de compresión en festivales masivos."
      ),
      metricLabel: t("landing.philosophy.card3.metricLabel", "CONTROL DE CALIDAD MULTI-DISPOSITIVO"),
      metricVal: t("landing.philosophy.card3.metricVal", "14 PERFILES"),
      icon: ShieldCheck,
      glowColor: "tertiary" as const,
      technicalPoints: [
        "14 perfiles acústicos de respuesta de impulso",
        "Cumplimiento EBU R128 (-14.0 LUFS) e ITU-R BS.1770",
        "Algoritmo anti-distorsión de transductores móviles",
        "Tolerancia espectral estricta de ±0.4 dB",
      ],
    },
  ];

  return (
    <section className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] border-y border-white/[0.04] relative overflow-x-hidden">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header - Stagger */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.15 }}
          transition={transitions.scrollReveal}
          className="flex flex-col md:flex-row md:items-end justify-between gap-6"
        >
          <div className="flex flex-col gap-2 max-w-2xl">
            <span className="font-label-technical text-primary text-[10px] uppercase tracking-widest">
              {t("landing.philosophy.badge", "Tríada Ontológica")}
            </span>
            <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
              {t("landing.philosophy.title", "Fenomenología Sonora de Brik")}
            </h2>
            <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
              {t(
                "landing.philosophy.subtitle",
                "Comprender el audio no como simple oscilación de voltaje, sino como un espectro vivo que habita múltiples dimensiones simultáneamente."
              )}
            </p>
          </div>

          <div className="font-label-technical text-xs text-[#bcc9c7] bg-[#1a1b20] border border-white/5 px-4 py-2 rounded-lg flex items-center gap-2.5 self-start md:self-auto shadow-sm">
            <motion.span
              animate={{ scale: [1, 1.3, 1], opacity: [0.5, 1, 0.5] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              className="w-2 h-2 rounded-full bg-secondary"
            />
            <span>{t("landing.philosophy.paradigmChip", "PARADIGMA DSP NO DESTRUCTIVO")}</span>
          </div>
        </motion.div>

        {/* 3 Phenomenon Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8 items-stretch">
          {cards.map((card, idx) => {
            const Icon = card.icon;
            const isExpanded = expandedCard === card.fenomeno;

            return (
              <InteractiveCard
                key={card.fenomeno}
                index={idx}
                isExpanded={isExpanded}
                glowColor={card.glowColor}
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
                      {card.fenomeno}
                    </span>
                    <h3 className="font-headline-sm text-lg sm:text-xl font-bold text-[#e3e2e8] min-h-[3rem] flex items-center">
                      {card.title}
                    </h3>
                  </div>

                  <p className="font-body-md text-[#bcc9c7] text-xs sm:text-sm leading-relaxed flex-1">
                    {card.desc}
                  </p>
                </div>

                <div className="pt-6 mt-auto border-t border-white/5 flex flex-col gap-3 relative z-10">
                  <div className="flex items-center justify-between font-label-technical text-[10px] sm:text-xs text-[#869391]">
                    <span>{card.metricLabel}</span>
                    <span className="text-primary font-bold">{card.metricVal}</span>
                  </div>

                  <motion.button
                    type="button"
                    onClick={() => setExpandedCard(isExpanded ? null : card.fenomeno)}
                    whileHover={{ backgroundColor: "#292a2e" }}
                    whileTap={{ scale: 0.99 }}
                    transition={transitions.cardHover}
                    className="w-full py-1.5 px-3 rounded-lg bg-[#292a2e]/60 border border-white/5 hover:border-white/10 text-[#bcc9c7] hover:text-[#e3e2e8] font-label-technical text-[10px] flex items-center justify-between transition-colors cursor-pointer"
                  >
                    <span>{isExpanded ? t("landing.philosophy.hideSpecs", "Ocultar especificación") : t("landing.philosophy.viewSpecs", "Examinar fenómeno")}</span>
                    <motion.div animate={{ rotate: isExpanded ? 180 : 0 }} transition={{ duration: 0.25, ease: easings.power2Out }}>
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
                        {card.technicalPoints.map((point) => (
                          <motion.div
                            key={point}
                            initial={{ opacity: 0, x: -8 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: 8 }}
                            transition={{ duration: 0.2, delay: 0.05 }}
                            className="flex items-center gap-2 text-xs text-[#bcc9c7]"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5 text-primary shrink-0" />
                            <span className="font-body-sm text-[11px]">{point}</span>
                          </motion.div>
                        ))}
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