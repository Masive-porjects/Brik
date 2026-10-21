"use client";

import { motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Sparkles } from "lucide-react";

import { useTranslation } from "@/i18n";

import AgentPanel from "./AgentPanel";

/** Expanded rail width (px). Exported so the dock can offset itself. */
export const AGENT_SIDEBAR_WIDTH = 400;
/** Collapsed rail width (px). */
export const AGENT_SIDEBAR_COLLAPSED = 56;

interface AgentSidebarProps {
  sessionId: string | null;
  disabled?: boolean;
  /** Expanded state. Owned by the page so the floating dock can follow. */
  open: boolean;
  onToggle: () => void;
}

/* ── AgentSidebar ───────────────────────────────────────
   Right rail that hosts Brik (Productor IA) next to the DAW.
   It is a layout sibling of the main column, not a fixed overlay:
   it takes real horizontal space, so the waveform on the left keeps
   its own scroll and nothing ever overlaps. Collapses to a narrow
   rail that still shows the toggle. */
export default function AgentSidebar({
  sessionId,
  disabled,
  open,
  onToggle,
}: AgentSidebarProps) {
  const { t } = useTranslation();
  const collapseLabel = t("productor.sidebarCollapse");
  const expandLabel = t("productor.sidebarExpand");

  return (
    <motion.aside
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
          <h2
            className="min-w-0 flex-1 truncate text-sm font-semibold"
            style={{ color: "var(--text-primary)" }}
          >
            {t("productor.sidebarTitle")}
          </h2>
        )}

        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? collapseLabel : expandLabel}
          title={open ? collapseLabel : expandLabel}
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
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          <AgentPanel sessionId={sessionId} disabled={disabled} compact />
        </div>
      )}
    </motion.aside>
  );
}
