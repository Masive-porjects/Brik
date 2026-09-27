"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { AudioWaveform, Shield, KeyRound } from "lucide-react";
import { checkLicense, activateLicense } from "@/lib/api";
import FloatingNotes from "@/components/FloatingNotes";
import FloatingGhosts from "@/components/FloatingGhosts";
import BigGhostWithNotes from "@/components/BigGhostWithNotes";

interface LicenseGuardProps {
  children: React.ReactNode;
}

export default function LicenseGuard({ children }: LicenseGuardProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "locked" | "unlocked">("loading");
  const [error, setError] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [activating, setActivating] = useState(false);

  /* Check license on mount — siempre llama al backend con timeout de seguridad */
  useEffect(() => {
    let active = true;
    const fallbackTimer = setTimeout(() => {
      if (active) setStatus("unlocked");
    }, 1500);

    checkLicense()
      .then((res) => {
        clearTimeout(fallbackTimer);
        if (!active) return;
        if (res.licensed) {
          // Dev mode (sin AUDIOMIND_LICENSE_KEY) — paso libre
          setStatus("unlocked");
        } else {
          // Production — mostrar lock screen
          setStatus("locked");
        }
      })
      .catch(() => {
        clearTimeout(fallbackTimer);
        if (!active) return;
        // Fallback gracefully in local environment
        setStatus("unlocked");
      });

    return () => {
      active = false;
      clearTimeout(fallbackTimer);
    };
  }, []);

  /* GSAP fade-out when unlocking */
  useGSAP(
    () => {
      if (status === "unlocked" && overlayRef.current) {
        gsap.to(overlayRef.current, {
          opacity: 0,
          y: -12,
          duration: 0.6,
          ease: "power2.inOut",
          onComplete: () => {
            if (overlayRef.current) {
              overlayRef.current.style.display = "none";
            }
          },
        });
      }
    },
    { scope: overlayRef, dependencies: [status] },
  );

  /* GSAP crystal entrance — blur-fade-up the locked card */
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
    { scope: cardRef, dependencies: [status] },
  );

  /* Handle activation submit */
  const handleActivate = useCallback(async () => {
    if (!keyInput.trim()) return;
    setActivating(true);
    setError(null);

    try {
      const key = keyInput.trim();
      const res = await activateLicense(key);
      if (res.success) {
        // sessionStorage — vive solo en esta pestaña, se borra al cerrar
        sessionStorage.setItem("waveai_license_key", key);
        setStatus("unlocked");
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Error al activar la licencia",
      );
    } finally {
      setActivating(false);
    }
  }, [keyInput]);

  /* ── Loading state ────────────────────────────────── */
  if (status === "loading") {
    return (
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-[var(--bg-app)]">
        <div className="flex flex-col items-center gap-4">
          <AudioWaveform
            size={32}
            className="text-[var(--text-muted)] animate-pulse"
          />
          <p className="text-xs text-[var(--text-muted)]">Verificando licencia...</p>
        </div>
      </div>
    );
  }

  /* ── Unlocked — reveal children with fade-out ────── */
  if (status === "unlocked") {
    return (
      <>
        {/* Guard overlay — fades out once */}
        <div
          ref={overlayRef}
          className="fixed inset-0 z-[200] bg-[var(--bg-app)] pointer-events-none"
        />
        {children}
      </>
    );
  }

  /* ── Locked — fullscreen crystal guard ────────────── */
  return (
    <div
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

      {/* Ghost leaning on the form frame, waiting for the license,
          with musical notes orbiting around it */}
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

        {/* Glassmorphism card — translucent, blurred, NO visible border,
            so the ghost and notes show through */}
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
          <Shield size={28} className="text-[var(--accent-primary)] relative z-10" />
        </div>

        {/* Title */}
        <h1
          className="text-xl font-semibold text-[var(--text-primary)] mb-2 relative z-10"
          style={{ letterSpacing: "-0.02em" }}
        >
          Brikmaster Studio
        </h1>

        <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-6 relative z-10">
          Sistema Protegido. Ingresá tu clave de licencia para continuar.
        </p>

        {/* Input */}
        <div className="w-full flex items-center gap-2 mb-3 relative z-10">
          <div className="relative flex-1">
            <KeyRound
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
            />
            <input
              type="text"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleActivate();
              }}
              placeholder="Ingresá tu clave de licencia"
              disabled={activating}
              className="w-full pl-9 pr-3 py-2 text-sm text-[var(--text-primary)]
                bg-transparent border-b border-[var(--border-subtle)]
                placeholder:text-[var(--text-muted)]
                focus:outline-none focus:border-[var(--accent-primary)]
                disabled:opacity-40 transition-all duration-200"
              autoFocus
            />
          </div>
          <button
            onClick={handleActivate}
            disabled={activating || !keyInput.trim()}
            className="px-4 py-2.5 rounded-lg text-sm font-medium text-[var(--bg-primary)]
              transition-all duration-200
              disabled:opacity-30 disabled:cursor-not-allowed
              hover:brightness-110"
            style={{
              background: "var(--accent-primary)",
            }}
          >
            {activating ? "..." : "Activar"}
          </button>
        </div>

        {/* Error */}
        {error && (
          <p className="text-xs text-[var(--accent-error)] mb-3 max-w-xs relative z-10">
            {error}
          </p>
        )}

        {/* Credits */}
        <p className="text-[10px] text-[var(--text-muted)] mt-4 leading-relaxed relative z-10">
          Brikmaster Studio © {new Date().getFullYear()}
          <br />
          Creado por Waveman Paul Morales
        </p>
        </div>
      </div>
    </div>
  );
}
