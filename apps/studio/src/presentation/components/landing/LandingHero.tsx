"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, PlayCircle, Cpu } from "lucide-react";
import { useTranslation } from "@/i18n";
import BigGhostWithNotes from "@/presentation/components/BigGhostWithNotes";

export default function LandingHero() {
  const { t } = useTranslation();

  return (
    <section className="relative w-full overflow-hidden px-4 sm:px-8 lg:px-12 pt-28 lg:pt-36 pb-20 max-w-[1440px] mx-auto">
      {/* Background Volumetric Flares */}
      <div
        className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-primary/10 blur-[130px] pointer-events-none"
        aria-hidden="true"
      />
      <div
        className="absolute top-1/3 -right-20 w-[420px] h-[420px] rounded-full bg-secondary-container/10 blur-[140px] pointer-events-none"
        aria-hidden="true"
      />

      <div className="w-full grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-center">
        {/* Left Column: Copy & Telemetry */}
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="lg:col-span-7 flex flex-col gap-6"
        >
          {/* Status Chips */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#292a2e] text-primary font-label-technical text-[10px] tracking-widest uppercase border border-primary/20 shadow-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-ping" />
              {t("landing.hero.badgeDsp", "DSP Core v2.4 Activo")}
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#292a2e] text-secondary font-label-technical text-[10px] tracking-widest uppercase border border-secondary/20 shadow-sm">
              <Cpu className="w-3.5 h-3.5 text-secondary" />
              {t("landing.hero.badgeNeural", "Motor Neuronal AudioMind")}
            </span>
            <span className="inline-flex items-center px-3 py-1 rounded-full bg-[#1a1b20] text-[#bcc9c7] font-label-technical text-[10px] border border-white/5">
              {t("landing.hero.badgeFormat", "96kHz / 64-bit FP Listo")}
            </span>
          </div>

          {/* Heading */}
          <div className="flex flex-col gap-3">
            <h1 className="font-display-xl text-3xl sm:text-5xl lg:text-[60px] lg:leading-[66px] text-[#e3e2e8] tracking-tight">
              {t("landing.hero.title", "El master ya no es un problema.")}{" "}
              <span className="bg-gradient-to-r from-primary via-primary-container to-secondary bg-clip-text text-transparent">
                {t("landing.hero.titleGradient", "Deja que el sonido cobre vida del más allá.")}
              </span>
            </h1>
            <p className="font-body-lg text-[#bcc9c7] text-sm sm:text-base leading-relaxed max-w-2xl">
              {t(
                "landing.hero.description",
                "Arquitectura de 13 etapas de procesamiento espectral en tiempo real. Eliminamos la planicie dimensional de tus mezclas mediante inteligencia tímbrica, balance psicoacústico Haas y fidelidad cuántica."
              )}
            </p>
          </div>

          {/* Telemetry Floating HUD */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-[#1a1b20]/80 backdrop-blur-xl p-4 rounded-xl border border-white/5 shadow-2xl">
            <div className="flex flex-col">
              <span className="font-label-technical text-[10px] text-[#869391] uppercase">
                {t("landing.hero.hud.loudness", "Target Loudness")}
              </span>
              <span className="font-metric-val-lg text-lg sm:text-2xl text-primary font-bold">
                {t("landing.hero.hud.loudnessVal", "-14.0")}{" "}
                <span className="text-xs font-normal opacity-80">LUFS</span>
              </span>
              <span className="font-label-technical text-[9px] text-primary/70">
                {t("landing.hero.hud.loudnessSub", "Cumple EBU R128")}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="font-label-technical text-[10px] text-[#869391] uppercase">
                {t("landing.hero.hud.truePeak", "True-Peak Ceiling")}
              </span>
              <span className="font-metric-val-lg text-lg sm:text-2xl text-secondary font-bold">
                {t("landing.hero.hud.truePeakVal", "-1.0")}{" "}
                <span className="text-xs font-normal opacity-80">dBTP</span>
              </span>
              <span className="font-label-technical text-[9px] text-secondary/70">
                {t("landing.hero.hud.truePeakSub", "Cero Intersample Peaks")}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="font-label-technical text-[10px] text-[#869391] uppercase">
                {t("landing.hero.hud.throughput", "DSP Throughput")}
              </span>
              <span className="font-metric-val-lg text-lg sm:text-2xl text-tertiary-container font-bold">
                {t("landing.hero.hud.throughputVal", "<420")}{" "}
                <span className="text-xs font-normal opacity-80">ms</span>
              </span>
              <span className="font-label-technical text-[9px] text-tertiary-container/70">
                {t("landing.hero.hud.throughputSub", "Pipeline Rust SIMD")}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="font-label-technical text-[10px] text-[#869391] uppercase">
                {t("landing.hero.hud.quantum", "Profundidad Cuántica")}
              </span>
              <span className="font-metric-val-lg text-lg sm:text-2xl text-[#e3e2e8] font-bold">
                {t("landing.hero.hud.quantumVal", "48")}{" "}
                <span className="text-xs font-normal opacity-80">kHz</span>
              </span>
              <span className="font-label-technical text-[9px] text-[#869391]">
                {t("landing.hero.hud.quantumSub", "24-bit PCM Impecable")}
              </span>
            </div>
          </div>

          {/* Action CTAs */}
          <div className="flex flex-wrap items-center gap-4 pt-2">
            <Link
              href="/upload"
              className="px-7 py-3.5 rounded-full bg-primary text-[#003734] font-body-lg font-bold hover:bg-primary-container transition-all transform hover:-translate-y-0.5 shadow-[0_0_28px_rgba(110,233,224,0.4)] flex items-center gap-2 group cursor-pointer"
            >
              <span>{t("landing.hero.ctaEnter", "Ingresar a Brik Studio")}</span>
              <span className="font-label-technical text-xs opacity-75 hidden sm:inline">
                {t("landing.nav.studioBadge", "(/studio)")}
              </span>
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </Link>

            <a
              href="#comparador"
              className="px-6 py-3.5 rounded-full bg-[#292a2e]/90 text-[#e3e2e8] font-body-md font-semibold hover:bg-[#38393e] transition-all flex items-center gap-2 shadow-md border border-white/5 cursor-pointer"
            >
              <PlayCircle className="w-4 h-4 text-primary" />
              <span>{t("landing.hero.ctaListenDemo", "Escuchar Demostración A/B")}</span>
            </a>
          </div>
        </motion.div>

        {/* Right Column: Visual Spectral Orb & Master Engine Telemetry */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.15, ease: "easeOut" }}
          className="lg:col-span-5 relative flex items-center justify-center"
        >
          <div className="relative w-full max-w-[480px] aspect-square rounded-2xl bg-[#1a1b20]/90 backdrop-blur-2xl p-5 flex flex-col justify-between shadow-2xl border border-white/10 overflow-hidden">
            <div
              className="absolute inset-0 bg-gradient-to-tr from-primary/10 via-transparent to-secondary/15 pointer-events-none"
              aria-hidden="true"
            />

            {/* Card Header HUD */}
            <div className="flex items-center justify-between z-10">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-primary animate-pulse" />
                <span className="font-label-technical text-xs text-[#e3e2e8] font-bold tracking-wider">
                  {t("landing.hero.ocularMonitor", "SPECTRAL OCULAR MONITOR")}
                </span>
              </div>
              <span className="font-label-technical text-[10px] text-secondary bg-[#343439] border border-secondary/20 px-2.5 py-0.5 rounded shadow-sm">
                {t("landing.hero.dualPrecision", "64-BIT DUAL PRECISION")}
              </span>
            </div>

            {/* Central Ectoplasmic Mascot & Resonance Target */}
            <div className="relative my-auto flex items-center justify-center py-4">
              <div className="relative w-64 h-64 sm:w-72 sm:h-72 rounded-full overflow-hidden shadow-[0_0_60px_rgba(110,233,224,0.25)] flex items-center justify-center bg-[#0d0e12] border border-primary/20">
                {/* Background visualizer image from design */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  alt="Brik Audio Visualizer Interface Dark Mode"
                  className="w-full h-full object-cover scale-105 opacity-80 mix-blend-screen"
                  src="https://lh3.googleusercontent.com/aida-public/AB6AXuC-fmfq5NimQX-KKfJ4fWMewu5MlsJOqcAlQENP0biAEI3m4enl2vxmiVIMdHMa4MJP6ocm9Lhxm7Ny_alOeJpsRMlOIqSEiFcXCrLOH_RXyHUoM-arBOrQb2RAymPPLFuGyJqKkUbOeJ1Y1LYLPC2U9UUHzrim_b2MfANOaPOUBaWoU_mL6ifhA6VRJkYCkrQLeUhr1YJycN1fB0Ik4C2_sDgsbzjehg3iMKwaUrHldxSGlTT63HnP0dXJbc_P_HtNPg"
                />

                {/* Overlaid WaveAI Ghost Mascot */}
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <BigGhostWithNotes size={64} radius={80} noteCount={6} />
                </div>

                <div className="absolute inset-0 bg-gradient-to-t from-[#121317] via-transparent to-transparent opacity-50" />
              </div>

              {/* Concentric Resonance Glyphs */}
              <div
                className="absolute inset-0 flex items-center justify-center pointer-events-none"
                aria-hidden="true"
              >
                <div
                  className="w-80 h-80 rounded-full border border-primary/20 animate-spin"
                  style={{ animationDuration: "28s" }}
                />
                <div
                  className="w-64 h-64 rounded-full border border-secondary/25 animate-spin"
                  style={{ animationDuration: "18s", animationDirection: "reverse" }}
                />
              </div>
            </div>

            {/* Bottom Live Stage Telemetry */}
            <div className="z-10 grid grid-cols-3 gap-2 bg-[#0d0e12]/80 p-3 rounded-lg backdrop-blur-md border border-white/5">
              <div>
                <span className="block font-label-technical text-[9px] text-[#869391] uppercase">
                  {t("landing.hero.telemetryCorrelation", "CORRELACIÓN")}
                </span>
                <span className="font-label-technical text-xs text-primary font-bold">
                  {t("landing.hero.telemetryCorrelationVal", "+0.94 ESTÉREO")}
                </span>
              </div>
              <div>
                <span className="block font-label-technical text-[9px] text-[#869391] uppercase">
                  {t("landing.hero.telemetryDynamicCrest", "CRESTA DINÁMICA")}
                </span>
                <span className="font-label-technical text-xs text-secondary font-bold">
                  {t("landing.hero.telemetryDynamicCrestVal", "11.8 dB PLR")}
                </span>
              </div>
              <div>
                <span className="block font-label-technical text-[9px] text-[#869391] uppercase">
                  {t("landing.hero.telemetryHaasPhase", "FASE HAAS")}
                </span>
                <span className="font-label-technical text-xs text-tertiary-container font-bold">
                  {t("landing.hero.telemetryHaasPhaseVal", "BLOQUEO EN FASE")}
                </span>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
