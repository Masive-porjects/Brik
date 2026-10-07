"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, PlayCircle, Cpu } from "lucide-react";
import { useTranslation } from "@/i18n";
import BigGhostWithNotes from "@/presentation/components/BigGhostWithNotes";
import { transitions, easings } from "@/shared/lib/animations";
import { useStaggerText, staggerVariants, staggerChildVariants } from "@/shared/hooks/useStaggerText";

export default function LandingHero() {
  const { t } = useTranslation();

  // Stagger del título principal
  const titleParts = useStaggerText(t("landing.hero.title", "El master ya no es un problema."));
  const gradientParts = useStaggerText(t("landing.hero.titleGradient", "Deja que el sonido cobre vida del más allá."));

  return (
    <section className="relative w-full overflow-hidden px-4 sm:px-8 lg:px-12 pt-28 lg:pt-36 pb-20 max-w-[1440px] mx-auto">
      {/* Background Volumetric Flares (GPU-only) */}
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 1.2, ease: easings.expoOut }}
        className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-primary/10 blur-[130px] pointer-events-none"
        style={{ willChange: "transform, opacity" }}
        aria-hidden="true"
      />
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 1.2, delay: 0.2, ease: easings.expoOut }}
        className="absolute top-1/3 -right-20 w-[420px] h-[420px] rounded-full bg-secondary-container/10 blur-[140px] pointer-events-none"
        style={{ willChange: "transform, opacity" }}
        aria-hidden="true"
      />

      <div className="w-full grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-center">
        {/* Left Column: Copy & Telemetry */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={transitions.heroEnter}
          className="lg:col-span-7 flex flex-col gap-6"
        >
          {/* Status Chips - Stagger */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transitions.heroEnterDelayed(0.1)}
            className="flex flex-wrap items-center gap-2"
          >
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#292a2e] text-primary font-label-technical text-[10px] tracking-widest uppercase border border-primary/20 shadow-sm">
              <motion.span
                animate={{ scale: [1, 1.3, 1], opacity: [0.5, 1, 0.5] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                className="w-1.5 h-1.5 rounded-full bg-primary"
              />
              {t("landing.hero.badgeDsp", "DSP Core v2.4 Activo")}
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#292a2e] text-secondary font-label-technical text-[10px] tracking-widest uppercase border border-secondary/20 shadow-sm">
              <Cpu className="w-3.5 h-3.5 text-secondary" />
              {t("landing.hero.badgeNeural", "Motor Neuronal AudioMind")}
            </span>
            <span className="inline-flex items-center px-3 py-1 rounded-full bg-[#1a1b20] text-[#bcc9c7] font-label-technical text-[10px] border border-white/5">
              {t("landing.hero.badgeFormat", "96kHz / 64-bit FP Listo")}
            </span>
          </motion.div>

          {/* Heading - Stagger por palabras */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transitions.heroEnterDelayed(0.15)}
            className="flex flex-col gap-3"
          >
            <h1 className="font-display-xl text-3xl sm:text-5xl lg:text-[60px] lg:leading-[66px] text-[#e3e2e8] tracking-tight">
              <motion.span
                variants={staggerVariants}
                initial="hidden"
                animate="visible"
                style={{ willChange: "opacity, transform" }}
              >
                {titleParts.map(({ content, delay, isWhitespace }, i) => (
                  <motion.span
                    key={i}
                    variants={staggerChildVariants}
                    style={{ transitionDelay: delay }}
                  >
                    {isWhitespace ? " " : content}
                  </motion.span>
                ))}
              </motion.span>
              {" "}
              <motion.span
                className="bg-gradient-to-r from-primary via-primary-container to-secondary bg-clip-text text-transparent"
                variants={staggerVariants}
                initial="hidden"
                animate="visible"
              >
                {gradientParts.map(({ content, delay, isWhitespace }, i) => (
                  <motion.span
                    key={i}
                    variants={staggerChildVariants}
                    style={{ transitionDelay: delay }}
                  >
                    {isWhitespace ? " " : content}
                  </motion.span>
                ))}
              </motion.span>
            </h1>

            <motion.p
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={transitions.heroEnterDelayed(0.35)}
              className="font-body-lg text-[#bcc9c7] text-sm sm:text-base leading-relaxed max-w-2xl"
            >
              {t(
                "landing.hero.description",
                "Arquitectura de 13 etapas de procesamiento espectral en tiempo real. Eliminamos la planicie dimensional de tus mezclas mediante inteligencia tímbrica, balance psicoacústico Haas y fidelidad cuántica."
              )}
            </motion.p>
          </motion.div>

          {/* Telemetry HUD - Stagger grid */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transitions.heroEnterDelayed(0.4)}
            className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-[#1a1b20]/80 backdrop-blur-xl p-4 rounded-xl border border-white/5 shadow-2xl"
          >
            {[
              { label: "landing.hero.hud.loudness", val: "landing.hero.hud.loudnessVal", unit: "LUFS", sub: "landing.hero.hud.loudnessSub", color: "text-primary" },
              { label: "landing.hero.hud.truePeak", val: "landing.hero.hud.truePeakVal", unit: "dBTP", sub: "landing.hero.hud.truePeakSub", color: "text-secondary" },
              { label: "landing.hero.hud.throughput", val: "landing.hero.hud.throughputVal", unit: "ms", sub: "landing.hero.hud.throughputSub", color: "text-tertiary-container" },
              { label: "landing.hero.hud.quantum", val: "landing.hero.hud.quantumVal", unit: "kHz", sub: "landing.hero.hud.quantumSub", color: "text-[#e3e2e8]" },
            ].map((item, i) => (
              <motion.div
                key={item.label}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transitions.scrollReveal, delay: 0.4 + i * 0.06 }}
                className="flex flex-col"
              >
                <span className="font-label-technical text-[10px] text-[#869391] uppercase">{t(item.label)}</span>
                <span className={`font-metric-val-lg text-lg sm:text-2xl ${item.color} font-bold`}>
                  {t(item.val)} <span className="text-xs font-normal opacity-80">{t(item.unit)}</span>
                </span>
                <span className="font-label-technical text-[9px] opacity-70">{t(item.sub)}</span>
              </motion.div>
            ))}
          </motion.div>

          {/* Action CTAs - Stagger */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transitions.heroEnterDelayed(0.5)}
            className="flex flex-wrap items-center gap-4 pt-2"
          >
            <motion.a
              href="/upload"
              className="px-7 py-3.5 rounded-full bg-primary text-[#003734] font-body-lg font-bold shadow-[0_0_28px_rgba(110,233,224,0.4)] flex items-center gap-2 group cursor-pointer"
              whileHover={{ y: -2, scale: 1.02, boxShadow: "0 0 40px rgba(110,233,224,0.55)" }}
              whileTap={{ scale: 0.98 }}
              transition={transitions.cardHover}
            >
              <span>{t("landing.hero.ctaEnter", "Ingresar a Brik Studio")}</span>
              <span className="font-label-technical text-xs opacity-75 hidden sm:inline">{t("landing.nav.studioBadge", "(/studio)")}</span>
              <motion.span
                animate={{ x: [0, 4, 0] }}
                transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
              >
                <ArrowRight className="w-4 h-4" />
              </motion.span>
            </motion.a>

            <motion.a
              href="#comparador"
              className="px-6 py-3.5 rounded-full bg-[#292a2e]/90 text-[#e3e2e8] font-body-md font-semibold shadow-md border border-white/5 cursor-pointer"
              whileHover={{ y: -2, backgroundColor: "#38393e" }}
              whileTap={{ scale: 0.98 }}
              transition={transitions.cardHover}
            >
              <PlayCircle className="w-4 h-4 text-primary" />
              <span>{t("landing.hero.ctaListenDemo", "Escuchar Demostración A/B")}</span>
            </motion.a>
          </motion.div>
        </motion.div>

        {/* Right Column: Visual Orb */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.15, ease: easings.expoOut }}
          className="lg:col-span-5 relative flex items-center justify-center"
        >
          <div className="relative w-full max-w-[480px] aspect-square rounded-2xl bg-[#1a1b20]/90 backdrop-blur-2xl p-5 flex flex-col justify-between shadow-2xl border border-white/10 overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-tr from-primary/10 via-transparent to-secondary/15 pointer-events-none" aria-hidden="true" />

            {/* Card Header */}
            <div className="flex items-center justify-between z-10">
              <motion.div
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={transitions.heroEnterDelayed(0.25)}
                className="flex items-center gap-2"
              >
                <motion.span
                  animate={{ scale: [1, 1.2, 1], opacity: [0.6, 1, 0.6] }}
                  transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
                  className="w-2.5 h-2.5 rounded-full bg-primary"
                />
                <span className="font-label-technical text-xs text-[#e3e2e8] font-bold tracking-wider">
                  {t("landing.hero.ocularMonitor", "SPECTRAL OCULAR MONITOR")}
                </span>
              </motion.div>
              <span className="font-label-technical text-[10px] text-secondary bg-[#343439] border border-secondary/20 px-2.5 py-0.5 rounded shadow-sm">
                {t("landing.hero.dualPrecision", "64-BIT DUAL PRECISION")}
              </span>
            </div>

            {/* Central Orb */}
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.9, delay: 0.3, ease: easings.expoOut }}
              className="relative my-auto flex items-center justify-center py-4"
            >
              <div className="relative w-64 h-64 sm:w-72 sm:h-72 rounded-full overflow-hidden shadow-[0_0_60px_rgba(110,233,224,0.25)] flex items-center justify-center bg-[#0d0e12] border border-primary/20">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  alt="Brik Audio Visualizer Interface Dark Mode"
                  className="w-full h-full object-cover scale-105 opacity-80 mix-blend-screen"
                  src="https://lh3.googleusercontent.com/aida-public/AB6AXuC-fmfq5NimQX-KKfJ4fWMewu5MlsJOqcAlQENP0biAEI3m4enl2vxmiVIMdHMa4MJP6ocm9Lhxm7Ny_alOeJpsRMlOIqSEiFcXCrLOH_RXyHUoM-arBOrQb2RAymPPLFuGyJqKkUbOeJ1Y1LYLPC2U9UUHzrim_b2MfANOaPOUBaWoU_mL6ifhA6VRJkYCkrQLeUhr1YJycN1fB0Ik4C2_sDgsbzjehg3iMKwaUrHldxSGlTT63HnP0dXJbc_P_HtNPg"
                />
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <BigGhostWithNotes size={64} radius={80} noteCount={6} />
                </div>
                <div className="absolute inset-0 bg-gradient-to-t from-[#121317] via-transparent to-transparent opacity-50" />
              </div>

              {/* Resonance Glyphs - CSS animation (GPU) */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none" aria-hidden="true">
                <div className="w-80 h-80 rounded-full border border-primary/20" style={{ animation: "spin 28s linear infinite" }} />
                <div className="w-64 h-64 rounded-full border border-secondary/25" style={{ animation: "spin 18s linear infinite reverse" }} />
              </div>
            </motion.div>

            {/* Bottom Telemetry */}
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={transitions.heroEnterDelayed(0.55)}
              className="z-10 grid grid-cols-3 gap-2 bg-[#0d0e12]/80 p-3 rounded-lg backdrop-blur-md border border-white/5"
            >
              {[
                { label: "landing.hero.telemetryCorrelation", val: "landing.hero.telemetryCorrelationVal", color: "text-primary" },
                { label: "landing.hero.telemetryDynamicCrest", val: "landing.hero.telemetryDynamicCrestVal", color: "text-secondary" },
                { label: "landing.hero.telemetryHaasPhase", val: "landing.hero.telemetryHaasPhaseVal", color: "text-tertiary-container" },
              ].map((item, i) => (
                <motion.div
                  key={item.label}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...transitions.scrollReveal, delay: 0.55 + i * 0.05 }}
                >
                  <span className="block font-label-technical text-[9px] text-[#869391] uppercase">{t(item.label)}</span>
                  <span className={`font-label-technical text-xs ${item.color} font-bold`}>{t(item.val)}</span>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </motion.div>
      </div>

      <style jsx global>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </section>
  );
}