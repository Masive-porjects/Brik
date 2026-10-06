"use client";

import { useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Zap, Maximize2, Radio, ChevronDown, ArrowRight } from "lucide-react";
import { useTranslation } from "@/i18n";
import { PRESETS_LIST } from "./data";

const PRESET_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Sparkles,
  Zap,
  Maximize: Maximize2,
  Radio,
};

export default function LandingPresets() {
  const { t } = useTranslation();
  const [expandedPresetId, setExpandedPresetId] = useState<string | null>(null);

  const presets = [
    {
      ...PRESETS_LIST[0],
      genre: t("landing.presets.preset1.genre", "GÉNERO: TECHNO / CLUB"),
      title: t("landing.presets.preset1.title", "Pulido Espectral"),
      desc: t(
        "landing.presets.preset1.desc",
        "Realza la presencia aérea de las frecuencias altas y limpia el barro en la zona de 250Hz. Ideal para producciones electrónicas de alta velocidad."
      ),
      metric: t("landing.presets.preset1.metric", "CLARIDAD +4.5 dB"),
      dotColor: "bg-primary shadow-[0_0_10px_#6ee9e0]",
      textColor: "text-primary",
      specs: [
        { label: "TARGET LUFS", value: "-14.0 LUFS" },
        { label: "CORTE BAJOS", value: "28 Hz 24dB/oct" },
        { label: "SATURACIÓN", value: "+2.4 dB Armónicos" },
        { label: "OVERSAMPLING", value: "8x Lineal" },
      ],
    },
    {
      ...PRESETS_LIST[1],
      genre: t("landing.presets.preset2.genre", "GÉNERO: URBAN / TRAP"),
      title: t("landing.presets.preset2.title", "Brutal Transmutación"),
      desc: t(
        "landing.presets.preset2.desc",
        "Empuja la pared de sonoridad hasta el límite extremo (-9 LUFS de club) preservando el punch seco del subgrave 808 sin ahogo dinámico."
      ),
      metric: t("landing.presets.preset2.metric", "DENSIDAD MÁXIMA"),
      dotColor: "bg-secondary shadow-[0_0_10px_#ecb2ff]",
      textColor: "text-secondary",
      specs: [
        { label: "TARGET LUFS", value: "-9.0 LUFS" },
        { label: "RATIO COMP", value: "5:1 Ataque Rápido" },
        { label: "SUB PUNCH", value: "+3.5 dB @ 45 Hz" },
        { label: "OVERSAMPLING", value: "8x Lineal" },
      ],
    },
    {
      ...PRESETS_LIST[2],
      genre: t("landing.presets.preset3.genre", "GÉNERO: AMBIENT / SCORE"),
      title: t("landing.presets.preset3.title", "Cristalino de Ultratumba"),
      desc: t(
        "landing.presets.preset3.desc",
        "Expansión dimensional extrema de la imagen estéreo. Convierte sintetizadores etéreos y cuerdas orquestales en una experiencia envolvente de 360 grados."
      ),
      metric: t("landing.presets.preset3.metric", "ANCHO HAAS 160%"),
      dotColor: "bg-tertiary-container shadow-[0_0_10px_#ffa654]",
      textColor: "text-tertiary-container",
      specs: [
        { label: "HAAS DELAY", value: "14.2 ms Lateral" },
        { label: "APERTURA", value: "160% Decorrelada" },
        { label: "BRILLO AIRE", value: "+4.0 dB @ 12 kHz" },
        { label: "FASE MONO", value: "100% Protegida" },
      ],
    },
    {
      ...PRESETS_LIST[3],
      genre: t("landing.presets.preset4.genre", "GÉNERO: LO-FI / INDIE"),
      title: t("landing.presets.preset4.title", "Vintage Ectoplasma"),
      desc: t(
        "landing.presets.preset4.desc",
        "Inyección de distorsión armónica par a través de transformadores de consola británica y suave compresión óptica con sensación orgánica y cálida."
      ),
      metric: t("landing.presets.preset4.metric", "CALIDEZ VÁLVULA"),
      dotColor: "bg-primary shadow-[0_0_10px_#6ee9e0]",
      textColor: "text-primary",
      specs: [
        { label: "VÁLVULA SIM", value: "Triodo Clase A" },
        { label: "WARMTH", value: "+3.2 dB Calidez" },
        { label: "ÓPTICO COMP", value: "1.8:1 Suave" },
        { label: "RESPIRACIÓN", value: "Orgánica" },
      ],
    },
  ];

  return (
    <section className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#121317] relative" id="presets-fantasmagoricos">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <div className="flex flex-col gap-2 max-w-2xl">
          <span className="font-label-technical text-secondary text-[10px] uppercase tracking-widest">
            {t("landing.presets.badge", "Invocaciones Sónicas")}
          </span>
          <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
            {t("landing.presets.title", "Presets Fantasmagóricos de Brik")}
          </h2>
          <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
            {t(
              "landing.presets.subtitle",
              "Perfiles tímbricos calibrados para canalizar estéticas sonoras precisas con un solo clic en la consola."
            )}
          </p>
        </div>

        {/* Presets Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 items-stretch">
          {presets.map((preset, idx) => {
            const Icon = PRESET_ICONS[preset.icon] || Sparkles;
            const isExpanded = expandedPresetId === preset.id;

            return (
              <motion.div
                key={preset.id}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.45, delay: idx * 0.08 }}
                className={`p-6 rounded-2xl bg-[#1a1b20] hover:bg-[#1f1f24] border transition-all duration-300 h-full flex flex-col justify-between shadow-xl ${
                  isExpanded ? "border-primary/40 bg-[#1f1f24] shadow-[0_0_25px_rgba(110,233,224,0.12)]" : "border-white/5 hover:border-white/15"
                }`}
              >
                <div className="flex flex-col gap-4 flex-1">
                  <div className="flex items-center justify-between">
                    <span className={`w-3 h-3 rounded-full ${preset.dotColor}`} />
                    <span className="font-label-technical text-[9px] text-[#869391] uppercase">
                      {preset.genre}
                    </span>
                  </div>

                  <div className="flex flex-col gap-1.5 flex-1">
                    <h3
                      className={`font-headline-sm text-lg font-bold text-[#e3e2e8] transition-colors`}
                    >
                      {preset.title}
                    </h3>
                    <p className="font-body-sm text-xs text-[#bcc9c7] leading-relaxed flex-1">
                      {preset.desc}
                    </p>
                  </div>
                </div>

                <div className="pt-5 mt-auto border-t border-white/5 flex flex-col gap-3">
                  <div className={`font-label-technical text-xs ${preset.textColor} font-bold flex items-center justify-between`}>
                    <span>{preset.metric}</span>
                    <Icon className="w-4 h-4" />
                  </div>

                  {/* Open / Close Transition Toggle Button */}
                  <button
                    type="button"
                    onClick={() => setExpandedPresetId(isExpanded ? null : preset.id)}
                    className="w-full py-1.5 px-2.5 rounded-lg bg-[#292a2e]/60 hover:bg-[#292a2e] border border-white/5 hover:border-white/10 text-[#bcc9c7] hover:text-[#e3e2e8] font-label-technical text-[10px] flex items-center justify-between transition-colors cursor-pointer"
                  >
                    <span>
                      {isExpanded
                        ? t("landing.presets.hideDetails", "Ocultar calibración")
                        : t("landing.presets.viewDetails", "Ver calibración")}
                    </span>
                    <motion.div animate={{ rotate: isExpanded ? 180 : 0 }} transition={{ duration: 0.25 }}>
                      <ChevronDown className="w-3.5 h-3.5" />
                    </motion.div>
                  </button>

                  {/* Expandable Calibration Specs with AnimatePresence */}
                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                        className="overflow-hidden flex flex-col gap-3 pt-2"
                      >
                        <div className="grid grid-cols-2 gap-2 text-left">
                          {preset.specs.map((spec) => (
                            <div key={spec.label} className="p-2 bg-[#292a2e] rounded-lg flex flex-col">
                              <span className="font-label-technical text-[9px] text-[#869391] uppercase">
                                {spec.label}
                              </span>
                              <span className="font-label-technical text-[10px] text-[#e3e2e8] font-bold">
                                {spec.value}
                              </span>
                            </div>
                          ))}
                        </div>

                        <Link
                          href="/upload"
                          className="py-2 px-3 rounded-lg bg-primary text-[#003734] font-label-technical text-xs font-bold hover:bg-primary-container transition-all flex items-center justify-center gap-1.5 shadow-sm hover:scale-[1.02] active:scale-[0.98]"
                        >
                          <span>{t("landing.presets.loadPreset", "Usar preset en Studio")}</span>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </Link>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

