"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { X, Upload, Music, Disc3 } from "lucide-react";
import IconButton from "@/components/ui/IconButton";
import type { SessionData } from "@/lib/api";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import ThemeToggle from "@/components/ThemeToggle";
import { DOCK_MODULES, type MasteringTab } from "@/components/dock/types";
import { useFeatures } from "@/shared/hooks/useFeatures";
import { useTranslation } from "@/i18n/useTranslation";

interface MobileDrawerProps {
  open: boolean;
  onClose: () => void;
  session: SessionData | null;
  onBackToUpload: () => void;
  currentTab?: MasteringTab | null;
  onSelectTab?: (tab: MasteringTab) => void;
  onOpenLibrary?: () => void;
}

/* ── Mobile Drawer ─────────────────────────────────────
   Slide-in panel rendered via Portal to document.body so no parent
   backdrop-filter can clip `position: fixed`. Shows current session,
   all studio modules, library, and settings. */
export default function MobileDrawer({
  open,
  onClose,
  session,
  onBackToUpload,
  currentTab = null,
  onSelectTab,
  onOpenLibrary,
}: MobileDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();
  const { filterDockModules } = useFeatures();
  const enabledModules = filterDockModules(DOCK_MODULES);

  /* Close on ESC */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[9999] h-[100dvh] w-screen">
          {/* Backdrop */}
          <motion.div
            key="drawer-backdrop"
            className="fixed inset-0 z-[9998] bg-black/75 backdrop-blur-md"
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
            className="fixed inset-y-0 left-0 z-[9999] h-[100dvh] w-80 max-w-[86vw] flex flex-col bg-[#0f1015] text-[#f4f4f2] border-r border-white/10 shadow-2xl overflow-y-auto"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-5 pb-4 shrink-0">
              <div className="flex items-center gap-2.5">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{
                    background: "linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))",
                  }}
                >
                  <Music size={16} className="text-[#06201e]" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-[#f4f4f2]">
                    Brik
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
                size="lg"
              />
            </div>

            <div className="mx-5 h-px bg-white/10 shrink-0" />

            {/* Current session */}
            <div className="px-5 py-3.5 shrink-0">
              <p className="text-[9px] text-[var(--text-muted)] uppercase tracking-widest mb-2">
                Sesión actual
              </p>
              {session ? (
                <div className="p-3 rounded-xl bg-white/[0.04] border border-white/10">
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span className="text-xs font-medium text-[#f4f4f2] truncate">
                      {session.original_path?.split("/").pop()?.split("\\").pop() ?? "Audio"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-[10px] text-[var(--text-secondary)]">
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

            {/* Studio Modules Navigation */}
            {onSelectTab && (
              <>
                <div className="mx-5 h-px bg-white/10 shrink-0" />
                <div className="px-4 py-3 flex flex-col gap-1">
                  <p className="px-1 text-[9px] text-[var(--text-muted)] uppercase tracking-widest mb-1.5">
                    Módulos del estudio
                  </p>
                  {enabledModules.map((mod) => {
                    const Icon = mod.icon;
                    const active = currentTab === mod.key;
                    return (
                      <button
                        key={mod.key}
                        type="button"
                        onClick={() => {
                          onSelectTab(mod.key);
                          onClose();
                        }}
                        className={`flex items-center gap-3 px-3 py-2.5 min-h-[42px] rounded-xl text-xs font-semibold transition-all text-left cursor-pointer ${
                          active
                            ? "bg-primary/15 text-primary border border-primary/35"
                            : "text-[#e8e8e8] hover:bg-white/5 hover:text-primary"
                        }`}
                      >
                        <Icon size={15} />
                        <span>{t(`nav.${mod.key}`, mod.label)}</span>
                      </button>
                    );
                  })}
                </div>
              </>
            )}

            <div className="mx-5 h-px bg-white/10 shrink-0" />

            {/* Actions */}
            <div className="px-5 py-4 flex flex-col gap-3">
              {onOpenLibrary && (
                <button
                  type="button"
                  onClick={() => {
                    onOpenLibrary();
                    onClose();
                  }}
                  className="flex items-center gap-3 px-3 py-2.5 min-h-[42px] rounded-xl text-xs font-semibold text-[#e8e8e8] hover:text-primary hover:bg-white/5 border border-white/10 transition-all"
                >
                  <Disc3 size={14} className="text-primary" />
                  <span>{t("nav.myTracks", "Mis Canciones")}</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => {
                  onBackToUpload();
                  onClose();
                }}
                className="flex items-center gap-3 px-3 py-2.5 min-h-[42px] rounded-xl text-xs font-semibold text-[#e8e8e8] hover:text-primary hover:bg-white/5 border border-white/10 transition-all active:scale-[0.98]"
              >
                <Upload size={14} className="text-primary" />
                <span>Subir nuevo track</span>
              </button>

              <div className="flex items-center justify-between pt-2">
                <span className="text-xs text-[var(--text-secondary)]">{t("common.language")}</span>
                <LanguageSwitcher />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-secondary)]">{t("common.theme", "Tema")}</span>
                <ThemeToggle />
              </div>
            </div>

            {/* Footer */}
            <div className="mt-auto px-5 py-4 border-t border-white/10 shrink-0">
              <p className="text-[9px] text-[var(--text-muted)] text-center">
                Brik Studio — Mastering &amp; Mix IA
              </p>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body
  );
}
