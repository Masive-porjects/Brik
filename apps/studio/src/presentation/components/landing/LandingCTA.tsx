"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import gsap from "gsap";
import { ArrowRight, Terminal, ShieldCheck, Cpu, Sliders, Wifi } from "lucide-react";
import { useTranslation } from "@/i18n";
import Reveal from "./Reveal";

export default function LandingCTA() {
  const { t } = useTranslation();
  // Magnetic hover lives on a wrapper so GSAP's translate never fights the
  // button's own CSS scale transition. Desktop / fine-pointer only.
  const primaryCtaRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = primaryCtaRef.current;
    if (!el) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const xTo = gsap.quickTo(el, "x", { duration: 0.5, ease: "power3.out" });
    const yTo = gsap.quickTo(el, "y", { duration: 0.5, ease: "power3.out" });

    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      xTo(((e.clientX - (rect.left + rect.width / 2)) / (rect.width / 2)) * 10);
      yTo(((e.clientY - (rect.top + rect.height / 2)) / (rect.height / 2)) * 8);
    };
    const onLeave = () => {
      xTo(0);
      yTo(0);
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      gsap.set(el, { x: 0, y: 0 });
    };
  }, []);

  return (
    <Reveal as="section" className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)] relative overflow-hidden">
      <div className="max-w-[1440px] mx-auto relative rounded-3xl bg-gradient-to-b from-[var(--surface-active)] to-[var(--bg-glass)] p-8 sm:p-12 lg:p-20 shadow-[var(--shadow-heavy)] border border-[var(--border-subtle)] flex flex-col items-center text-center gap-8 overflow-hidden">
        {/* Glow flares inside card */}
        <div
          className="absolute -top-32 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-primary/15 rounded-full blur-[120px] pointer-events-none"
          aria-hidden="true"
        />

        {/* Badge */}
        <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-[var(--surface-active)] text-primary font-label-technical text-xs tracking-wider uppercase z-10 border border-primary/20 shadow-sm">
          <span className="w-2 h-2 rounded-full bg-primary animate-ping" />
          <span>{t("landing.cta.badge", "SISTEMA DE ACCESO DIRECTO ABIERTO")}</span>
        </div>

        {/* Heading & Subtitle */}
        <div className="flex flex-col gap-3 max-w-3xl z-10">
          <h2 className="font-display-xl text-3xl sm:text-5xl lg:text-[56px] lg:leading-[64px] text-[var(--text-primary)] tracking-tight">
            {t("landing.cta.title", "Eleva tu sonido al estándar cuántico de Brik")}
          </h2>
          <p className="font-body-lg text-[var(--text-secondary)] text-sm sm:text-base max-w-xl mx-auto leading-relaxed">
            {t(
              "landing.cta.subtitle",
              "Ingresa al entorno de producción definitivo donde la precisión matemática y el carácter espectral se fusionan para entregar masters definitivos."
            )}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-center gap-4 z-10 pt-2">
          <span ref={primaryCtaRef} className="flex w-full sm:w-auto will-change-transform">
            <Link
              href="/upload"
              className="w-full sm:w-auto px-8 py-4 rounded-full bg-primary text-[var(--color-on-primary)] font-body-lg font-bold hover:bg-primary-container transition-all transform hover:scale-105 active:scale-[0.98] shadow-[0_0_32px_rgba(110,233,224,0.4)] flex items-center justify-center gap-2 group cursor-pointer"
            >
              <span>{t("landing.cta.btnStudio", "Ingresar a Brik Studio")}</span>
              <span className="font-label-technical text-xs opacity-75">
                {t("landing.cta.btnStudioTag", "(/studio)")}
              </span>
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </Link>
          </span>

          <a
            href="#arquitectura-dsp"
            className="w-full sm:w-auto px-6 py-4 rounded-full bg-[var(--surface-active)]/90 text-[var(--text-primary)] font-body-md font-semibold hover:bg-[var(--surface-hover)] transition-all active:scale-[0.98] flex items-center justify-center gap-2 shadow-md border border-primary/20 cursor-pointer"
          >
            <Terminal className="w-4 h-4 text-primary" />
            <span>{t("landing.cta.btnSpecs", "Ver Especificación DSP (13 Etapas)")}</span>
          </a>
        </div>

        {/* Technical Guarantees Footer Tickers */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-4 text-[var(--text-muted)] font-label-technical text-xs z-10 w-full max-w-2xl">
          <div className="flex items-center justify-center gap-2 bg-[var(--bg-glass)]/60 py-2.5 px-3 rounded-lg border border-[var(--border-subtle)]">
            <ShieldCheck className="w-4 h-4 text-primary" />
            <span>{t("landing.cta.guarantees.artifacts", "Cero Artefactos")}</span>
          </div>
          <div className="flex items-center justify-center gap-2 bg-[var(--bg-glass)]/60 py-2.5 px-3 rounded-lg border border-[var(--border-subtle)]">
            <Cpu className="w-4 h-4 text-secondary" />
            <span>{t("landing.cta.guarantees.simd", "Rust SIMD 64-bit")}</span>
          </div>
          <div className="flex items-center justify-center gap-2 bg-[var(--bg-glass)]/60 py-2.5 px-3 rounded-lg border border-[var(--border-subtle)]">
            <Sliders className="w-4 h-4 text-primary" />
            <span>{t("landing.cta.guarantees.haas", "True Haas Estéreo")}</span>
          </div>
          <div className="flex items-center justify-center gap-2 bg-[var(--bg-glass)]/60 py-2.5 px-3 rounded-lg border border-[var(--border-subtle)]">
            <Wifi className="w-4 h-4 text-tertiary-container" />
            <span>{t("landing.cta.guarantees.instantWs", "WebSocket Instantáneo")}</span>
          </div>
        </div>
      </div>
    </Reveal>
  );
}
