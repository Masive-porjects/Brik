"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sliders,
  Filter,
  Wand2,
  Sparkles,
  SlidersHorizontal,
  Layers,
  Box,
  Disc,
  Speaker,
  Gauge,
  Activity,
  Grid,
  ShieldCheck,
  Cpu,
  ArrowRight,
  Power,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "@/i18n";
import { DSP_STAGES } from "./data";
import Reveal from "./Reveal";
import { DSPStage } from "./types";

const ICONS_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Sliders,
  Filter,
  Wand2,
  Sparkles,
  SlidersHorizontal,
  Layers,
  Box,
  Disc,
  Speaker,
  Gauge,
  Activity,
  Grid,
  ShieldCheck,
};

export default function LandingDSPChain() {
  const { t } = useTranslation();
  const [selectedStageId, setSelectedStageId] = useState<number>(7); // Default to Stage 7 (Board Render)
  const [activeTab, setActiveTab] = useState<"substages" | "spatial" | "telemetry">("substages");
  const [isBypassed, setIsBypassed] = useState<boolean>(false);
  const [isAutoCycle, setIsAutoCycle] = useState<boolean>(true);
  const [isHovered, setIsHovered] = useState<boolean>(false);

  const selectedStage: DSPStage =
    DSP_STAGES.find((s) => s.id === selectedStageId) || DSP_STAGES[6];

  const StageIcon = ICONS_MAP[selectedStage.icon] || Box;

  // Automatic cycling through the 13 DSP stages every 4.2 seconds WITHOUT window scrolling
  useEffect(() => {
    if (!isAutoCycle || isHovered) return;

    const interval = setInterval(() => {
      setSelectedStageId((prev) => (prev >= 13 ? 1 : prev + 1));
      setIsBypassed(false);
    }, 4200);

    return () => clearInterval(interval);
  }, [isAutoCycle, isHovered]);

  return (
    <Reveal
      as="section"
      className="w-full py-16 sm:py-20 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] border-b border-white/[0.04] relative"
      id="arquitectura-dsp"
    >
      <div className="max-w-[1440px] mx-auto flex flex-col gap-12">
        {/* Section Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div className="flex flex-col gap-2 max-w-3xl">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-primary animate-ping" />
              <span className="font-label-technical text-primary text-[10px] uppercase tracking-widest">
                {t("landing.chain.badge", "Matriz Algorítmica Lineal — 13 Etapas DSP")}
              </span>
            </div>
            <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
              {t("landing.chain.title", "Arquitectura DSP de 13 Etapas")}
            </h2>
            <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
              {t(
                "landing.chain.subtitle",
                "Cada muestra de audio atraviesa una cadena modular con cero alteración destructiva de fase. Haz clic en cualquier módulo para examinar los parámetros internos, sub-etapas y tensores en tiempo real."
              )}
            </p>
          </div>

          <div className="flex items-center gap-2 bg-[#1a1b20] border border-primary/20 px-4 py-2 rounded-lg self-start md:self-auto shadow-sm">
            <Cpu className="w-4 h-4 text-primary" />
            <span className="font-label-technical text-[10px] sm:text-xs text-[#e3e2e8]">
              {t("landing.chain.pipelineBadge", "PIPELINE RUST SIMD: CERO FUGAS INTERSAMPLE")}
            </span>
          </div>
        </div>

        {/* 13 Stages Two-Column Interactive Layout */}
        <div
          className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 items-start"
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
        >
          {/* Left Column: Stage list — vertical scroll on desktop, snap strip on mobile */}
          <div className="lg:col-span-5 flex flex-col gap-2 min-w-0 lg:max-h-[720px] lg:overflow-y-auto pr-0 lg:pr-1 custom-scroll">
            <div className="flex items-center justify-between px-2 pb-2 border-b border-white/10 sticky top-0 bg-[#0d0e12] z-10">
              <span className="font-label-technical text-[10px] text-[#869391] uppercase tracking-wider">
                {t("landing.chain.chainHeader", "CADENA SECUENCIAL (13 MÓDULOS)")}
              </span>
              {/* Interactive Auto-Cycle Badge / Button */}
              <button
                type="button"
                onClick={() => setIsAutoCycle((prev) => !prev)}
                className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-label-technical text-[9px] border transition-all cursor-pointer ${
                  isAutoCycle && !isHovered
                    ? "bg-primary/15 text-primary border-primary/40 shadow-[0_0_10px_rgba(110,233,224,0.25)]"
                    : isAutoCycle && isHovered
                    ? "bg-secondary/15 text-secondary border-secondary/40"
                    : "bg-[#292a2e] text-[#869391] border-white/10"
                }`}
                title={isAutoCycle ? "Haz clic para pausar el ciclo automático" : "Haz clic para reanudar el ciclo automático"}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    isAutoCycle && !isHovered
                      ? "bg-primary animate-pulse"
                      : isAutoCycle && isHovered
                      ? "bg-secondary"
                      : "bg-[#869391]"
                  }`}
                />
                <span>{t("landing.chain.autoCycle", "Ciclo Automático")}:</span>
                <span className="font-bold">
                  {isAutoCycle && isHovered
                    ? t("landing.chain.autoCyclePaused", "PAUSADO")
                    : isAutoCycle
                    ? t("landing.chain.autoCycleActive", "ACTIVO")
                    : t("landing.chain.autoCyclePaused", "PAUSADO")}
                </span>
                <RotateCcw className={`w-2.5 h-2.5 ml-0.5 ${isAutoCycle && !isHovered ? "animate-spin" : ""}`} style={{ animationDuration: "4s" }} />
              </button>
            </div>

            <div className="flex flex-row gap-2 pt-1 pb-2 overflow-x-auto scrollbar-hide snap-x snap-mandatory lg:grid lg:grid-cols-1 lg:gap-2 lg:overflow-visible lg:pb-0">
              {DSP_STAGES.map((stage) => {
                const isSelected = stage.id === selectedStageId;
                const IconComponent = ICONS_MAP[stage.icon] || Box;

                return (
                  <button
                    key={stage.id}
                    type="button"
                    onClick={() => {
                      setSelectedStageId(stage.id);
                      setIsBypassed(false);
                      // User manual interaction pauses auto-cycle for a moment
                      setIsHovered(true);
                      setTimeout(() => setIsHovered(false), 8000);
                    }}
                    className={`p-3.5 rounded-xl text-left transition-all duration-300 flex items-center justify-between gap-3 group cursor-pointer relative overflow-hidden shrink-0 snap-start w-[82%] sm:w-[60%] lg:w-auto min-h-[44px] ${
                      isSelected
                        ? "bg-[#1f1f24] border-2 border-primary shadow-[0_0_24px_rgba(110,233,224,0.22)] scale-[1.01]"
                        : "bg-[#1a1b20] hover:bg-[#1f1f24] border border-white/5 hover:border-primary/20"
                    }`}
                  >
                    {/* Animated cadence glow indicator on active stage */}
                    {isSelected && (
                      <motion.div
                        layoutId="activeStageGlow"
                        className="absolute inset-0 bg-primary/[0.04] pointer-events-none"
                        transition={{ type: "spring", stiffness: 350, damping: 30 }}
                      />
                    )}

                    <div className="flex items-center gap-3 relative z-10 min-w-0">
                      <span
                        className={`w-7 h-7 shrink-0 rounded-lg flex items-center justify-center font-label-technical text-xs font-bold transition-all ${
                          isSelected
                            ? "bg-primary text-[#003734] shadow-sm"
                            : "bg-[#292a2e] text-primary"
                        }`}
                      >
                        {stage.number}
                      </span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <h4
                            className={`font-headline-sm text-xs font-semibold transition-colors ${
                              isSelected
                                ? "text-primary"
                                : "text-[#e3e2e8] group-hover:text-primary"
                            }`}
                          >
                            {stage.name}
                          </h4>
                          {stage.substagesCount && (
                            <span className="font-label-technical text-[10px] bg-secondary/20 text-secondary border border-secondary/30 px-1.5 py-0.2 rounded font-bold">
                              {stage.substagesCount} SUB-ETAPAS
                            </span>
                          )}
                          {stage.modulesCount && (
                            <span className="font-label-technical text-[10px] bg-tertiary-container/20 text-tertiary-container border border-tertiary-container/30 px-1.5 py-0.2 rounded font-bold">
                              {stage.modulesCount} MÓDULOS
                            </span>
                          )}
                        </div>
                        <span className="font-label-technical text-[10px] text-[#869391]">
                          {stage.subtitle}
                        </span>
                      </div>
                    </div>
                    <IconComponent
                      className={`w-4 h-4 shrink-0 transition-colors relative z-10 ${
                        isSelected
                          ? "text-primary"
                          : "text-[#869391] group-hover:text-primary"
                      }`}
                    />
                  </button>
                );
              })}
            </div>
          </div>

          {/* Right Column: Stage Detail Inspector with AnimatePresence */}
          <div className="lg:col-span-7 min-w-0 bg-[#1a1b20] rounded-2xl p-4 sm:p-6 lg:p-8 border border-white/10 shadow-2xl flex flex-col gap-6 lg:sticky lg:top-24 min-h-0 lg:min-h-[580px]">
            <AnimatePresence mode="wait">
              <motion.div
                key={selectedStage.id}
                initial={{ opacity: 0, y: 12, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0, y: -12, filter: "blur(4px)" }}
                transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
                className="flex flex-col gap-6 flex-1"
              >
                {/* Inspector Top Bar */}
                <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/10">
                  <div className="flex items-center gap-3">
                    <span className="px-2.5 py-1 rounded font-label-technical text-xs font-bold bg-primary/20 text-primary border border-primary/30">
                      ETAPA {selectedStage.number} / 13
                    </span>
                    <div className="flex items-center gap-2">
                      <StageIcon className="w-5 h-5 text-primary" />
                      <h3 className="font-headline-md text-lg sm:text-xl font-bold text-[#e3e2e8]">
                        {selectedStage.name}
                      </h3>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setIsBypassed(!isBypassed)}
                      className={`px-3 py-1.5 rounded-lg font-label-technical text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer border ${
                        isBypassed
                          ? "bg-[#292a2e] text-[#869391] border-white/10"
                          : "bg-primary/20 text-primary border-primary/40 shadow-[0_0_10px_rgba(110,233,224,0.2)]"
                      }`}
                    >
                      <Power className="w-3.5 h-3.5" />
                      <span>
                        {isBypassed
                          ? t("landing.chain.bypassedState", "EN BYPASS")
                          : t("landing.chain.activeState", "ESTADO ACTIVO")}
                      </span>
                    </button>
                    <span className="font-label-technical text-[10px] text-[#869391] bg-[#292a2e] px-2.5 py-1 rounded border border-white/5">
                      {t("landing.chain.latency", "LATENCIA:")} {selectedStage.latency}
                    </span>
                  </div>
                </div>

            {/* Inspector Body */}
            <div className="flex flex-col gap-5">
              <p className="font-body-md text-[#bcc9c7] text-xs sm:text-sm leading-relaxed">
                {selectedStage.description}
              </p>

              {/* Sub-tabs Selector */}
              <div className="flex flex-wrap items-center gap-2 gap-y-2 pt-1 border-b border-white/5 pb-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("substages")}
                  className={`px-3 py-1.5 rounded-lg font-label-technical text-xs font-bold transition-all cursor-pointer ${
                    activeTab === "substages"
                      ? "bg-[#292a2e] text-primary border border-primary/40 shadow-sm"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.chain.tabSubstages", "Sub-etapas")}
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("spatial")}
                  className={`px-3 py-1.5 rounded-lg font-label-technical text-xs font-bold transition-all cursor-pointer ${
                    activeTab === "spatial"
                      ? "bg-[#292a2e] text-secondary border border-secondary/40 shadow-sm"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.chain.tabSpatial", "Bloque Espacial Haas")}
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("telemetry")}
                  className={`px-3 py-1.5 rounded-lg font-label-technical text-xs font-bold transition-all cursor-pointer ${
                    activeTab === "telemetry"
                      ? "bg-[#292a2e] text-tertiary-container border border-tertiary-container/40 shadow-sm"
                      : "text-[#869391] hover:text-[#e3e2e8]"
                  }`}
                >
                  {t("landing.chain.tabTelemetry", "Tensores & SIMD")}
                </button>
              </div>

              {/* Tab Content Display */}
              <AnimatePresence mode="wait">
                {activeTab === "substages" && (
                  <motion.div
                    key="substages"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.2 }}
                    className="grid grid-cols-1 md:grid-cols-2 gap-3"
                  >
                    {selectedStage.substages?.map((sub) => (
                      <div
                        key={sub.tag}
                        className={`p-3.5 rounded-xl bg-[#1f1f24] flex flex-col gap-1.5 border border-white/5 ${
                          sub.isWide ? "md:col-span-2 border-primary/30 bg-[#1f1f24]/90" : ""
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-label-technical text-xs text-primary font-bold">
                            {sub.tag}
                          </span>
                          <span className="font-label-technical text-[9px] text-[#869391] bg-[#292a2e] px-2 py-0.5 rounded">
                            {sub.meta}
                          </span>
                        </div>
                        <h5 className="font-headline-sm text-xs font-semibold text-[#e3e2e8]">
                          {sub.title}
                        </h5>
                        <p className="font-body-sm text-[11px] text-[#bcc9c7] leading-relaxed">
                          {sub.description}
                        </p>
                      </div>
                    ))}
                  </motion.div>
                )}

                {activeTab === "spatial" && selectedStage.spatialDetails && (
                  <motion.div
                    key="spatial"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.2 }}
                    className="flex flex-col gap-3 p-4 bg-[#1f1f24] rounded-xl border border-secondary/20"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-headline-sm text-xs font-bold text-secondary">
                        {selectedStage.spatialDetails.title}
                      </span>
                      <span className="font-label-technical text-[9px] bg-secondary/20 text-secondary px-2 py-0.5 rounded">
                        PSYCHOACOUSTIC STEREO
                      </span>
                    </div>
                    <p className="font-body-sm text-xs text-[#bcc9c7]">
                      {selectedStage.spatialDetails.description}
                    </p>
                    <div className="grid grid-cols-3 gap-2 pt-2 border-t border-white/5">
                      {selectedStage.spatialDetails.parameters.map((param) => (
                        <div key={param.label} className="p-2 bg-[#292a2e] rounded-lg flex flex-col">
                          <span className="font-label-technical text-[9px] text-[#869391]">
                            {param.label}
                          </span>
                          <span className="font-label-technical text-xs text-secondary font-bold">
                            {param.value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                )}

                {activeTab === "telemetry" && selectedStage.telemetryDetails && (
                  <motion.div
                    key="telemetry"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.2 }}
                    className="grid grid-cols-2 gap-3"
                  >
                    <div className="p-3 bg-[#1f1f24] rounded-xl border border-white/5 flex flex-col gap-1">
                      <span className="font-label-technical text-[10px] text-[#869391]">
                        MOTOR DSP
                      </span>
                      <span className="font-label-technical text-xs text-tertiary-container font-bold">
                        {selectedStage.telemetryDetails.engine}
                      </span>
                    </div>
                    <div className="p-3 bg-[#1f1f24] rounded-xl border border-white/5 flex flex-col gap-1">
                      <span className="font-label-technical text-[10px] text-[#869391]">
                        CONJUNTO INSTRUCCIONES
                      </span>
                      <span className="font-label-technical text-xs text-primary font-bold">
                        {selectedStage.telemetryDetails.instructionSet}
                      </span>
                    </div>
                    <div className="p-3 bg-[#1f1f24] rounded-xl border border-white/5 flex flex-col gap-1">
                      <span className="font-label-technical text-[10px] text-[#869391]">
                        PRECISIÓN INTERNA
                      </span>
                      <span className="font-label-technical text-xs text-[#e3e2e8] font-bold">
                        {selectedStage.telemetryDetails.precision}
                      </span>
                    </div>
                    <div className="p-3 bg-[#1f1f24] rounded-xl border border-white/5 flex flex-col gap-1">
                      <span className="font-label-technical text-[10px] text-[#869391]">
                        TAMAÑO DE BUFFER
                      </span>
                      <span className="font-label-technical text-xs text-secondary font-bold">
                        {selectedStage.telemetryDetails.bufferSize}
                      </span>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Bottom Real-time Telemetry Row */}
              <div className="grid grid-cols-3 gap-3 pt-3 border-t border-white/10">
                <div className="p-3 bg-[#1f1f24] rounded-lg flex flex-col">
                  <span className="font-label-technical text-[9px] text-[#869391]">
                    {t("landing.chain.thd", "DISTORSIÓN THD")}
                  </span>
                  <span className="font-metric-val-lg text-sm text-secondary font-bold">
                    {selectedStage.thd}
                  </span>
                </div>
                <div className="p-3 bg-[#1f1f24] rounded-lg flex flex-col">
                  <span className="font-label-technical text-[9px] text-[#869391]">
                    {t("landing.chain.phaseCorrelation", "CORRELACIÓN FASE")}
                  </span>
                  <span className="font-metric-val-lg text-sm text-primary font-bold">
                    {selectedStage.phaseCorrelation}
                  </span>
                </div>
                <div className="p-3 bg-[#1f1f24] rounded-lg flex flex-col">
                  <span className="font-label-technical text-[9px] text-[#869391]">
                    {t("landing.chain.overSampling", "SOBREMUESTREO")}
                  </span>
                  <span className="font-metric-val-lg text-sm text-tertiary-container font-bold">
                    {selectedStage.oversampling}
                  </span>
                </div>
              </div>

              {/* Bottom Actions */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                <span className="font-label-technical text-[10px] text-[#869391] min-w-0">
                  {t("landing.chain.tensorsComputed", "Tensores calculados en SSE/AVX-512 nativo")}
                </span>
                <Link
                  href="/upload"
                  className="shrink-0 px-4 py-2 rounded-lg bg-primary text-[#003734] font-body-sm text-xs font-bold hover:bg-primary-container transition-all flex items-center gap-1.5 shadow-[0_0_14px_rgba(110,233,224,0.3)] hover:scale-105 active:scale-95 cursor-pointer"
                >
                  <span>{t("landing.chain.loadInStudio", "Cargar en Brik Studio")}</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  </div>
</Reveal>
  );
}
