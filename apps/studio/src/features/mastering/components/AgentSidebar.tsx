"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { Ghost, Sparkles, X } from "lucide-react";

import { useTranslation } from "@/i18n";

import AgentPanel, { type DecisionPhase } from "./AgentPanel";

/** Levitation amplitude and beat, in px / seconds. */
const GHOST_LIFT_PX = -7;
const GHOST_CYCLE_S = 1.7;

/** Tone per engine state. Semantic colours, same palette the panel uses. */
const STATUS_TONE: Record<
  DecisionPhase,
  { color: string; background: string; border: string }
> = {
  idle: {
    color: "var(--text-muted)",
    background: "var(--surface-hover)",
    border: "var(--border-subtle)",
  },
  analyzing: {
    color: "#fbbf24",
    background: "rgba(251, 191, 36, 0.12)",
    border: "rgba(251, 191, 36, 0.28)",
  },
  verdict: {
    color: "#fbbf24",
    background: "rgba(251, 191, 36, 0.12)",
    border: "rgba(251, 191, 36, 0.28)",
  },
  producing: {
    color: "var(--accent-primary)",
    background: "rgba(0, 212, 170, 0.12)",
    border: "rgba(0, 212, 170, 0.28)",
  },
  completed: {
    color: "#30d158",
    background: "rgba(48, 209, 88, 0.12)",
    border: "rgba(48, 209, 88, 0.28)",
  },
  error: {
    color: "var(--accent-error)",
    background: "rgba(220, 38, 38, 0.12)",
    border: "rgba(220, 38, 38, 0.28)",
  },
};

/* ── AgentSidebar ───────────────────────────────────────
   Brik como widget de chat flotante (pop-up) en la esquina inferior derecha.
   No ocupa espacio del layout: el canvas de la forma de onda no se desplaza ni
   cambia de tamaño cuando el widget se abre. El botón fantasma permanece anclado
   debajo del widget y su levitación GSAP solo anima el icono interno. */
export default function AgentSidebar({
  sessionId,
  disabled,
}: {
  sessionId: string | null;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<DecisionPhase>("idle");
  const ghostRef = useRef<HTMLSpanElement>(null);

  /* Levitation. GSAP owns the inner span's transform. */
  useEffect(() => {
    const ghost = ghostRef.current;
    if (!ghost) return;
    const reduceMotion =
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    if (reduceMotion) return;

    const tween = gsap.to(ghost, {
      y: GHOST_LIFT_PX,
      duration: GHOST_CYCLE_S,
      ease: "sine.inOut",
      repeat: -1,
      yoyo: true,
    });

    return () => {
      tween.kill();
      gsap.set(ghost, { y: 0 });
    };
  }, []);

  const toggleLabel = open ? t("productor.sidebarCollapse") : t("productor.sidebarExpand");

  return (
    <>
      {/* Fantasma de activación — anclado debajo del widget, cerca de ENTREGA */}
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-label={toggleLabel}
        data-testid="brik-ghost"
        className="fixed bottom-6 right-6 z-[101] grid size-11 place-items-center rounded-full border
          transition-colors duration-300 hover:border-[var(--accent-primary)]
          focus-visible:outline focus-visible:outline-2
          focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]"
        style={{
          background: "var(--bg-glass-elevated)",
          borderColor: "var(--border-strong)",
          color: "var(--accent-primary)",
          boxShadow: "0 6px 20px rgba(0, 0, 0, 0.35)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
        }}
      >
        <span ref={ghostRef} className="grid place-items-center">
          <Ghost size={20} />
        </span>
      </button>

      {/* Widget de chat flotante — overlay independiente */}
      {open && (
        <div
          className="fixed bottom-[120px] right-6 z-[100] w-[350px] shadow-2xl rounded-2xl bg-white flex flex-col border border-[var(--border-subtle)]"
        >
          <header
            className="flex shrink-0 gap-2 border-b px-4 py-3 items-center justify-between"
            style={{ borderColor: "var(--border-subtle)" }}
          >
            <span
              className="grid size-7 shrink-0 place-items-center rounded-full"
              style={{
                background: "var(--surface-hover)",
                border: "1px solid var(--border-subtle)",
                color: "var(--accent-primary)",
              }}
            >
              <Sparkles size={15} />
            </span>

            <div className="min-w-0 flex-1">
              <h2
                className="truncate text-sm font-semibold leading-tight"
                style={{ color: "var(--text-primary)" }}
              >
                {t("productor.sidebarTitle")}
              </h2>
              <span
                className="mt-1 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold"
                style={{
                  background: STATUS_TONE[phase].background,
                  border: `1px solid ${STATUS_TONE[phase].border}`,
                  color: STATUS_TONE[phase].color,
                }}
                role="status"
                aria-live="polite"
              >
                <span
                  className={`size-1.5 rounded-full ${
                    phase === "analyzing" || phase === "producing"
                      ? "animate-pulse"
                      : ""
                  }`}
                  style={{ background: STATUS_TONE[phase].color }}
                />
                {t(`productor.status.${phase}`)}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label={t("common.close")}
              className="grid size-7 shrink-0 place-items-center rounded-lg border transition-colors
                hover:border-[var(--accent-primary)] hover:text-[var(--text-primary)]
                focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent-primary)]"
              style={{
                background: "var(--surface-hover)",
                borderColor: "var(--border-subtle)",
                color: "var(--text-secondary)",
              }}
            >
              <X size={15} />
            </button>
          </header>

          <div className="flex-1 min-h-0 overflow-hidden">
            <AgentPanel
              sessionId={sessionId}
              disabled={disabled}
              compact
              onPhaseChange={setPhase}
            />
          </div>
        </div>
      )}
    </>
  );
}
