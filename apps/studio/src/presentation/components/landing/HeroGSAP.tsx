"use client";

import { useHeroGSAP } from "@/hooks/useHeroGSAP";
import { useTranslation } from "@/i18n";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, PlayCircle } from "lucide-react";
import BigGhostWithNotes from "@/presentation/components/BigGhostWithNotes";

export default function HeroGSAP() {
  const { t } = useTranslation();
  const refs = useHeroGSAP();

  return (
    <section id="hero" className="relative w-full overflow-hidden px-4 sm:px-8 lg:px-12 pt-40 lg:pt-48 pb-24 max-w-[1200px] mx-auto min-h-[90vh] flex items-center">
      {/* Background Layers - registered via ref array for parallax */}
      <div
        ref={(el) => { refs.bgLayersRef.current[0] = el; }}
        className="absolute -top-40 -left-40 w-[800px] h-[800px] rounded-full bg-primary/5 blur-[200px] pointer-events-none"
        aria-hidden="true"
        style={{ willChange: "transform" }}
      />
      <div
        ref={(el) => { refs.bgLayersRef.current[1] = el; }}
        className="absolute top-1/4 -right-32 w-[500px] h-[500px] rounded-full bg-secondary-container/5 blur-[180px] pointer-events-none"
        aria-hidden="true"
        style={{ willChange: "transform" }}
      />
      <div
        ref={(el) => { refs.bgLayersRef.current[2] = el; }}
        className="absolute bottom-20 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-gradient-to-r from-primary/3 via-transparent to-secondary/3 blur-[150px] pointer-events-none"
        aria-hidden="true"
        style={{ willChange: "transform" }}
      />

      <div className="relative z-10 w-full grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-start">
        {/* LEFT: CONTENT - 7/12 */}
        <div className="lg:col-span-7 flex flex-col gap-8">
          {/* Eyebrow - 1 línea técnica */}
          <span
            ref={refs.eyebrowRef}
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#1a1b20]/80 text-primary font-label-technical text-[10px] tracking-widest uppercase border border-primary/20"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" aria-hidden="true" />
            {t("landing.hero.eyebrow", "Mastering Spectral DSP · 13 Etapas · 8× Oversampling")}
          </span>

          {/* Title - SplitText reveal, GSAP-style typography + word-break fix */}
          <h1
            ref={refs.titleRef}
            className="font-sans text-4xl sm:text-5xl md:text-6xl lg:text-7xl xl:text-8xl leading-[0.95] tracking-tight text-[#F4F4EB] max-w-[28ch] break-keep"
            style={{
              wordBreak: "keep-all",
              overflowWrap: "normal",
              hyphens: "none",
            }}
          >
            {t("landing.hero.title", "El master ya no es un problema.")}
            <span className="bg-gradient-to-r from-primary via-primary-container to-secondary bg-clip-text text-transparent ml-1">
              {" "}{t("landing.hero.titleGradient", "Deja que el sonido cobre vida del más allá.")}
            </span>
          </h1>

          {/* Subtitle - Benefit-driven, 1 línea */}
          <p
            ref={refs.subtitleRef}
            className="font-sans text-base sm:text-lg leading-relaxed text-[#bcc9c7] max-w-xl"
          >
            {t("landing.hero.subtitleClean", "Sube tu mezcla. Obtén un master listo para streaming en segundos.")}
          </p>

          {/* CTA Primario + Ghost */}
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 pt-2">
            <motion.a
              ref={refs.ctaPrimaryRef}
              href="/upload"
              className="w-full sm:w-auto px-8 py-4 rounded-full bg-primary text-[#003734] font-sans font-bold shadow-[0_0_32px_rgba(110,233,224,0.4)] flex items-center justify-center gap-2 group cursor-pointer"
              whileHover={{ y: -3, scale: 1.02, boxShadow: "0 0 48px rgba(110,233,224,0.6)" }}
              whileTap={{ scale: 0.97 }}
              transition={{ duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] }}
            >
              <span>{t("landing.hero.ctaEnter", "Probar Brik Studio")}</span>
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </motion.a>

            <motion.a
              ref={refs.ctaGhostRef}
              href="#demo"
              className="w-full sm:w-auto px-7 py-4 rounded-full bg-[#1a1b20]/80 text-white font-sans font-semibold border border-white/10 hover:bg-[#292a2e] flex items-center justify-center gap-2 cursor-pointer"
              whileHover={{ y: -2, borderColor: "rgba(110,233,224,0.4)" }}
              whileTap={{ scale: 0.98 }}
            >
              <PlayCircle className="w-4 h-4 text-primary" />
              <span>{t("landing.hero.ctaListenDemo", "Ver demo A/B")}</span>
            </motion.a>
          </div>
        </div>

        {/* RIGHT: MONITOR CARD - 5/12, solo desktop */}
        <div className="hidden lg:block lg:col-span-5">
          <div 
            ref={refs.monitorRef} 
            className="relative w-full max-w-[440px] aspect-square rounded-2xl bg-[#1a1b20]/90 backdrop-blur-2xl p-5 flex flex-col justify-between shadow-2xl border border-white/10 overflow-hidden cursor-pointer"
            style={{ touchAction: "none", willChange: "transform" }}
          >
            {/* Glow reactivo - GSAP controlled */}
            <div 
              ref={refs.glowRef} 
              className="absolute inset-0 bg-gradient-to-tr from-primary/10 via-transparent to-secondary/10 pointer-events-none blur-[80px] opacity-10" 
              style={{ willChange: "opacity, transform, filter" }} 
            />

            {/* Orb Central */}
            <div ref={refs.orbRef} className="relative my-auto flex items-center justify-center py-4">
              <div className="relative w-64 h-64 rounded-full overflow-hidden shadow-[0_0_60px_rgba(110,233,224,0.25)] flex items-center justify-center bg-[#0d0e12] border border-primary/20">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  alt=""
                  className="w-full h-full object-cover scale-105 opacity-80 mix-blend-screen"
                  src="https://lh3.googleusercontent.com/aida-public/AB6AXuC-fmfq5NimQX-KKfJ4fWMewu5MlsJOqcAlQENP0biAEI3m4enl2vxmiVIMdHMa4MJP6ocm9Lhxm7Ny_alOeJpsRMlOIqSEiFcXCrLOH_RXyHUoM-arBOrQb2RAymPPLFuGyJqKkUbOeJ1Y1LYLPC2U9UUHzrim_b2MfANOaPOUBaWoU_mL6ifhA6VRJkYCkrQLeUhr1YJycN1fB0Ik4C2_sDgsbzjehg3iMKwaUrHldxSGlTT63HnP0dXJbc_P_HtNPg"
                />
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <BigGhostWithNotes size={64} radius={80} noteCount={6} />
                </div>
              </div>

              {/* Glyphs CSS-only (GPU) */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none" aria-hidden="true">
                <div className="w-80 h-80 rounded-full border border-primary/10" style={{ animation: "spin 30s linear infinite" }} />
                <div className="w-64 h-64 rounded-full border border-secondary/5" style={{ animation: "spin 20s linear infinite reverse" }} />
              </div>
            </div>

            {/* 1 métrica clave - Bottom */}
            <div className="z-10 px-3 py-2 bg-[#0d0e12]/60 rounded-lg backdrop-blur-md border border-white/5 text-center">
              <span className="font-label-technical text-[9px] text-[#869391] uppercase">{t("landing.hero.monitorMetric", "TARGET LOUDNESS")}</span>
              <span className="font-metric-val-lg text-xl text-primary font-bold ml-2">{t("landing.hero.monitorValue", "-14.0 LUFS")}</span>
            </div>
          </div>
        </div>
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