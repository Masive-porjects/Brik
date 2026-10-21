"use client";

import { motion, AnimatePresence } from "framer-motion";
import { ChevronLeft, ChevronRight, Sparkles, Bot } from "lucide-react";
import { useTranslation } from "@/i18n";

import AgentPanel from "./AgentPanel";

interface AgentSidebarProps {
  sessionId: string | null;
  disabled?: boolean;
  /** Callback when user wants to switch back to manual mode */
  onSwitchToManual?: () => void;
}

/**
 * AgentSidebar — Collapsible right sidebar for the AI Producer (Productor IA).
 *
 * Inspired by Moises Studio: fixed right drawer that slides in/out.
 * Contains the full AgentPanel workflow in a compact vertical layout.
 * Width: 400px desktop, full-width mobile.
 */
export default function AgentSidebar({
  sessionId,
  disabled,
  onSwitchToManual,
}: AgentSidebarProps) {
  const { t } = useTranslation();
  const SIDEBAR_WIDTH = 400;

  return (
    <AnimatePresence>
      <motion.aside
        initial={{ x: SIDEBAR_WIDTH }}
        animate={{ x: 0 }}
        exit={{ x: SIDEBAR_WIDTH }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="fixed right-0 top-0 bottom-0 z-30 flex flex-col"
        style={{
          width: SIDEBAR_WIDTH,
          maxWidth: "100vw",
          background: "var(--bg-glass-elevated)",
          borderLeft: "1px solid var(--border-strong)",
          boxShadow: "var(--shadow-heavy)",
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
        }}
        role="complementary"
        aria-label={t("nav.productor", "Productor IA")}
      >
        {/* Drag handle / resize indicator */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize opacity-0 hover:opacity-30 transition-opacity"
          aria-hidden="true"
        />

        {/* Sidebar Content */}
        <div className="flex flex-col h-full overflow-hidden">
          {/* Header */}
          <header className="flex items-center justify-between border-b border-[var(--border-subtle)] px-4 py-3 shrink-0">
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5">
                <div className="relative">
                  <Bot size={18} className="text-[var(--accent-primary)]" />
                  <span className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-[var(--accent-primary)] animate-pulse" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-[var(--text-primary)] leading-tight">
                    {t("nav.productor", "Productor IA")}
                  </h2>
                  <p className="text-[10px] text-[var(--text-muted)] leading-none">
                    {t("productor.subtitle", "El agente escucha, separa, mezcla y masteriza por su cuenta")}
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              {/* Collapse toggle */}
              <button
                type="button"
                className="p-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-hover)] transition-colors"
                aria-label="Colapsar panel"
                aria-expanded="true"
                onClick={() => window.dispatchEvent(new CustomEvent("agent-sidebar:toggle"))}
              >
                <ChevronRight size={16} />
              </button>

              {/* Switch to manual mode */}
              {onSwitchToManual && (
                <button
                  type="button"
                  onClick={onSwitchToManual}
                  className="flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-hover)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)] hover:border-[var(--border-hover)]"
                >
                  <ChevronLeft size={13} />
                  <span>{t("common.backToMainFlow", "Volver al flujo principal")}</span>
                </button>
              )}
            </div>
          </header>

          {/* Content Area */}
          <div className="flex-1 min-h-0 overflow-y-auto p-4">
            {sessionId ? (
              <AgentPanel sessionId={sessionId} disabled={disabled} />
            ) : (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
                className="flex flex-col items-center justify-center h-full text-center"
              >
                <Sparkles size={48} className="text-[var(--accent-primary)] mb-4" />
                <h3 className="text-base font-semibold text-[var(--text-primary)] mb-2">
                  {t("productor.title", "Productor IA")}
                </h3>
                <p className="text-sm text-[var(--text-secondary)] max-w-xs">
                  {t("productor.loadAudioPrompt", "Carga un audio para usar el Productor IA.")}
                </p>
              </motion.div>
            )}
          </div>
        </div>
      </motion.aside>
    </AnimatePresence>
  );
}