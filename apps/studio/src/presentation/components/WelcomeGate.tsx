"use client";

import { useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { AudioWaveform, ArrowRight } from "lucide-react";
import FloatingNotes from "@/components/FloatingNotes";
import FloatingGhosts from "@/components/FloatingGhosts";
import BigGhostWithNotes from "@/components/BigGhostWithNotes";

interface WelcomeGateProps {
  children: React.ReactNode;
}

/**
 * Welcome overlay (sin licencia — deja de pegarte contra /license/*).
 * Muestra "Bienvenido a WaveIA" y un botón Continuar que revela la
 * app (vista de adjuntar audio). No hay llamadas a la API acá: el demo
 * corre en modo desarrollo, sin clave de licencia.
 */
export default function WelcomeGate({ children }: WelcomeGateProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = useState(false);

  /* Entrance — crystal card blur-fade-up */
  useGSAP(
    () => {
      if (!cardRef.current) return;
      gsap.from(cardRef.current, {
        opacity: 0,
        y: 24,
        filter: "blur(8px)",
        duration: 0.7,
        ease: "power2.out",
      });
    },
    { scope: cardRef, dependencies: [revealed] },
  );

  /* Continue — fade out the overlay and reveal the app */
  const handleContinue = () => {
    if (!overlayRef.current) return;
    overlayRef.current.style.pointerEvents = "none";
    gsap.to(overlayRef.current, {
      opacity: 0,
      y: -12,
      duration: 0.6,
      ease: "power2.inOut",
      onComplete: () => {
        if (overlayRef.current) overlayRef.current.style.display = "none";
        setRevealed(true);
      },
    });
  };

  if (revealed) {
    return (
      <>
        {/* Overlay ya oculto — app visible */}
        {children}
      </>
    );
  }

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-[200] flex items-center justify-center overflow-hidden"
      style={{ background: "var(--bg-app)" }}
    >
      {/* Crystal atmosphere — soft radial accents over the base */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `
            radial-gradient(ellipse 70% 55% at 18% 12%, rgba(98, 126, 132, 0.16), transparent 62%),
            radial-gradient(ellipse 60% 50% at 88% 82%, rgba(130, 156, 161, 0.14), transparent 65%),
            radial-gradient(ellipse 45% 40% at 68% 8%, rgba(98, 126, 132, 0.1), transparent 60%)
          `,
        }}
      />

      {/* Ambient music notes floating in the air (below the card) */}
      <FloatingGhosts />
      <FloatingNotes />

      {/* Ghost leaning on the welcome card, with musical notes orbiting */}
      <div className="flex flex-col items-center relative z-10">
        <BigGhostWithNotes
          size={170}
          radius={130}
          noteCount={10}
          className="relative -mb-12"
          style={{
            opacity: 0.85,
            zIndex: 20,
            transform: "rotate(10deg)",
          }}
        />

        {/* Glassmorphism card — translucent, blurred, NO visible border */}
        <div
          ref={cardRef}
          className="relative w-full max-w-sm px-8 py-9 rounded-3xl flex flex-col items-center text-center overflow-hidden"
          style={{
            background: "rgba(26, 26, 32, 0.25)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.25)",
          }}
        >
          {/* Soft inner glow — no outer edges */}
          <div
            className="absolute inset-0 rounded-3xl pointer-events-none"
            style={{
              background: `
                radial-gradient(ellipse 80% 60% at 20% 10%, rgba(255,255,255,0.08), transparent 55%),
                radial-gradient(ellipse 70% 55% at 85% 90%, rgba(98,126,132,0.10), transparent 60%)
              `,
            }}
          />
          {/* Subtle shimmer sweep — stays inside the card */}
          <div
            className="absolute inset-0 rounded-3xl pointer-events-none opacity-30"
            style={{
              background: "linear-gradient(120deg, transparent 40%, rgba(255,255,255,0.08) 50%, transparent 60%)",
              animation: "shimmer 4s infinite",
            }}
          />

          {/* Icon */}
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6 relative z-10"
            style={{
              background: "rgba(98, 126, 132, 0.12)",
              border: "1px solid rgba(98, 126, 132, 0.22)",
              boxShadow: "0 0 28px rgba(98, 126, 132, 0.25)",
            }}
          >
            <AudioWaveform size={28} className="text-[var(--accent-primary)] relative z-10" />
          </div>

          {/* Title */}
          <h1
            className="text-xl font-semibold text-[var(--text-primary)] mb-2 relative z-10"
            style={{ letterSpacing: "-0.02em" }}
          >
            Bienvenido a WaveIA
          </h1>

          <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-6 relative z-10">
            Carga tu audio y empieza a masterizar.
          </p>

          {/* Continue */}
          <button
            onClick={handleContinue}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium text-[var(--bg-primary)]
              transition-all duration-200 hover:brightness-110 active:scale-[0.98] relative z-10"
            style={{
              background: "var(--accent-primary)",
            }}
            autoFocus
          >
            Continuar
            <ArrowRight size={16} className="relative z-10" />
          </button>

          {/* Credits */}
          <p className="text-[10px] text-[var(--text-muted)] mt-4 leading-relaxed relative z-10">
            WaveIA © {new Date().getFullYear()}
          </p>
        </div>
      </div>
    </div>
  );
}