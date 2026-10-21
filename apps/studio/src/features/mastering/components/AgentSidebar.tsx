"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import gsap from "gsap";
import { ChevronLeft, ChevronRight, Ghost, Sparkles } from "lucide-react";

import { useTranslation } from "@/i18n";

import AgentPanel, { type DecisionPhase } from "./AgentPanel";

/** Expanded rail width (px). Exported so the dock can offset itself. */
export const AGENT_SIDEBAR_WIDTH = 400;
/** Collapsed rail width (px). */
export const AGENT_SIDEBAR_COLLAPSED = 56;
/** Gap between the rail and the floating ghost, in px. */
const GHOST_GAP = 14;
/** Levitation amplitude and beat, in px / seconds. */
const GHOST_LIFT_PX = -7;
const GHOST_CYCLE_S = 1.7;

interface AgentSidebarProps {
  sessionId: string | null;
  disabled?: boolean;
  /** Expanded state. Owned by the page so the floating dock can follow. */
  open: boolean;
  onToggle: () => void;
}

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
   Right rail that hosts Brik next to the DAW. It is a layout sibling of
   the main column, not a fixed overlay: it takes real horizontal space,
   so the waveform on the left keeps its own scroll and nothing overlaps.
   Collapses to a narrow rail that still shows the header toggle, and a
   levitating ghost anchored to the rail's left shoulder flips it open or
   shut from anywhere on the DAW. */
export default function AgentSidebar({
  sessionId,
  disabled,
  open,
  onToggle,
}: AgentSidebarProps) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<DecisionPhase>("idle");
  const ghostRef = useRef<HTMLSpanElement>(null);

  /* Levitation. GSAP owns the inner span's transform so framer-motion stays
     free to animate the button's `right` while the rail slides. */
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

  const collapseLabel = t("productor.sidebarCollapse");
  const expandLabel = t("productor.sidebarExpand");
  const toggleLabel = open ? collapseLabel : expandLabel;
  const tone = STATUS_TONE[phase];
  const busy = phase === "analyzing" || phase === "producing";

  return (
    <>
      <motion.button
        type="button"
        onClick={onToggle}
        initial={false}
        animate={{
          right: (open ? AGENT_SIDEBAR_WIDTH : AGENT_SIDEBAR_COLLAPSED) + GHOST_GAP,
        }}
        transition={{ type: "spring", stiffness: 320, damping: 34 }}
        aria-expanded={open}
        aria-controls="brik-rail"
        aria-label={toggleLabel}
        title={toggleLabel}
        data-testid="brik-ghost"
        className="fixed z-[45] grid size-11 place-items-center rounded-full border
          transition-colors duration-300 hover:border-[var(--accent-primary)]
          focus-visible:outline focus-visible:outline-2
          focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]"
        style={{
          top: "calc(50% - 22px)",
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
      </motion.button>

      <motion.aside
        id="brik-rail"
        initial={false}
        animate={{ width: open ? AGENT_SIDEBAR_WIDTH : AGENT_SIDEBAR_COLLAPSED }}
        transition={{ type: "spring", stiffness: 320, damping: 34 }}
        className="relative z-[2] flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-l"
        style={{
          background: "var(--bg-glass-elevated)",
          borderColor: "var(--border-strong)",
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
        }}
        aria-label={t("productor.sidebarTitle")}
      >
        <header
          className={`flex shrink-0 gap-2 border-b px-3 py-3 ${
            open ? "items-center" : "flex-col items-center"
          }`}
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

          {open && (
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
                  background: tone.background,
                  border: `1px solid ${tone.border}`,
                  color: tone.color,
                }}
                role="status"
                aria-live="polite"
              >
                <span
                  className={`size-1.5 rounded-full ${busy ? "animate-pulse" : ""}`}
                  style={{ background: tone.color }}
                />
                {t(`productor.status.${phase}`)}
              </span>
            </div>
          )}

          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-controls="brik-rail"
            aria-label={toggleLabel}
            title={toggleLabel}
            data-testid="brik-rail-toggle"
            className="grid size-7 shrink-0 place-items-center rounded-lg border transition-colors
              hover:border-[var(--accent-primary)] hover:text-[var(--text-primary)]
              focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent-primary)]"
            style={{
              background: "var(--surface-hover)",
              borderColor: "var(--border-subtle)",
              color: "var(--text-secondary)",
            }}
          >
            {open ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
          </button>
        </header>

        {open && (
          <div className="min-h-0 flex-1 overflow-hidden px-3 py-3">
            <AgentPanel
              sessionId={sessionId}
              disabled={disabled}
              compact
              onPhaseChange={setPhase}
            />
          </div>
        )}
      </motion.aside>
    </>
  );
}
