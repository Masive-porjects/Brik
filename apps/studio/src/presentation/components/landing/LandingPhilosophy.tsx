"use client";

import { motion } from "framer-motion";
import { Activity, Radio, ShieldCheck } from "lucide-react";
import { useTranslation } from "@/i18n";

export default function LandingPhilosophy() {
  const { t } = useTranslation();

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
      color: "primary",
      bgGlow: "bg-primary/5",
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
      color: "secondary",
      bgGlow: "bg-secondary/5",
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
      color: "tertiary-container",
      bgGlow: "bg-tertiary-container/10",
    },
  ];

  return (
    <section className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] border-y border-white/[0.04] relative">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
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
            <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
            <span>{t("landing.philosophy.paradigmChip", "PARADIGMA DSP NO DESTRUCTIVO")}</span>
          </div>
        </div>

        {/* 3 Phenomenon Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 lg:gap-8">
          {cards.map((card, idx) => {
            const Icon = card.icon;
            return (
              <motion.div
                key={card.fenomeno}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: idx * 0.1 }}
                className="group flex flex-col justify-between p-6 sm:p-8 rounded-2xl bg-[#1a1b20] hover:bg-[#1f1f24] border border-white/[0.05] hover:border-white/10 transition-all duration-300 shadow-xl relative overflow-hidden"
              >
                {/* Subtle corner light */}
                <div
                  className={`absolute top-0 right-0 w-32 h-32 ${card.bgGlow} rounded-bl-full pointer-events-none group-hover:scale-125 transition-transform duration-500`}
                />

                <div className="flex flex-col gap-5">
                  <div className="w-12 h-12 rounded-xl bg-[#292a2e] border border-white/5 flex items-center justify-center text-primary shadow-sm group-hover:border-primary/30 transition-colors">
                    <Icon className="w-6 h-6" />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <span className="font-label-technical text-[10px] text-primary uppercase tracking-wider">
                      {card.fenomeno}
                    </span>
                    <h3 className="font-headline-sm text-lg sm:text-xl font-bold text-[#e3e2e8]">
                      {card.title}
                    </h3>
                  </div>

                  <p className="font-body-md text-[#bcc9c7] text-xs sm:text-sm leading-relaxed">
                    {card.desc}
                  </p>
                </div>

                <div className="pt-6 mt-6 border-t border-white/5 flex items-center justify-between font-label-technical text-[10px] sm:text-xs text-[#869391]">
                  <span>{card.metricLabel}</span>
                  <span className="text-primary font-bold">{card.metricVal}</span>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
