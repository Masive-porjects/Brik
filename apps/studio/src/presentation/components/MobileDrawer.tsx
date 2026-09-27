"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Upload, Music } from "lucide-react";
import IconButton from "@/components/ui/IconButton";
import type { SessionData } from "@/lib/api";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeToggle from "@/components/ThemeToggle";
import { useTranslation } from "@/i18n/useTranslation";

interface MobileDrawerProps {
  open: boolean;
  onClose: () => void;
  session: SessionData | null;
  onBackToUpload: () => void;
}

/* ── Mobile Drawer ─────────────────────────────────────
   Slide-in panel from left. Shows current session info,
   quick actions, and settings. */
export default function MobileDrawer({
  open,
  onClose,
  session,
  onBackToUpload,
}: MobileDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();

  /* Close on ESC */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="drawer-backdrop"
            className="fixed inset-0 z-[130] bg-black/50 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />

          {/* Drawer panel */}
          <motion.div
            ref={panelRef}
            key="drawer-panel"
            className="fixed inset-y-0 left-0 z-[140] w-72 max-w-[85vw] flex flex-col"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
            style={{
              background: "var(--bg-glass-elevated)",
              borderRight: "1px solid var(--border-strong)",
              backdropFilter: "blur(20px)",
              WebkitBackdropFilter: "blur(20px)",
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-5 pb-4">
              <div className="flex items-center gap-2.5">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{
                    background: "linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))",
                  }}
                >
                  <Music size={16} className="text-white" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                    WaveIA
                  </h2>
                  <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-wider">
                    Studio
                  </p>
                </div>
              </div>
              <IconButton
                label="Cerrar menú"
                icon={X}
                onClick={onClose}
                size="md"
              />
            </div>

            {/* Divider */}
            <div className="mx-5 h-px bg-[var(--border-subtle)]" />

            {/* Current session */}
            <div className="px-5 py-4">
              <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest mb-3">
                Sesión actual
              </p>
              {session ? (
                <div
                  className="p-3 rounded-xl"
                  style={{
                    background: "var(--bg-glass)",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span className="text-xs font-medium text-[var(--text-primary)] truncate">
                      {session.original_path?.split("/").pop()?.split("\\").pop() ?? "Audio"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-[9px] text-[var(--text-muted)]">
                    {session.analysis && (
                      <span>{session.analysis.integrated_lufs.toFixed(1)} LUFS</span>
                    )}
                    {session.mastered_path && (
                      <span className="text-emerald-400">✓ Masterizado</span>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-[var(--text-muted)] italic">
                  Sin sesión activa
                </p>
              )}
            </div>

            {/* Divider */}
            <div className="mx-5 h-px bg-[var(--border-subtle)]" />

            {/* Actions */}
            <div className="px-5 py-4 flex flex-col gap-3">
              <div className="flex items-center justify-between pb-1">
                <span className="text-xs text-[var(--text-secondary)]">{t("common.language")}</span>
                <LanguageSwitcher />
              </div>
              <div className="flex items-center justify-between pb-1">
                <span className="text-xs text-[var(--text-secondary)]">{t("common.theme", "Tema")}</span>
                <ThemeToggle />
              </div>
              <button
                onClick={() => {
                  onBackToUpload();
                  onClose();
                }}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-medium
                  text-[var(--text-secondary)] hover:text-[var(--text-primary)]
                  hover:bg-[var(--surface-hover)] transition-all"
              >
                <Upload size={14} />
                Subir nuevo track
              </button>
            </div>

            {/* Footer */}
            <div className="mt-auto px-5 py-4 border-t border-[var(--border-subtle)]">
              <p className="text-[9px] text-[var(--text-muted)] text-center">
                WaveIA v0.1 — Mastering Profesional
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
