"use client";

import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2 } from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import { GhostIcon } from "@/presentation/components/ThemeToggle";

interface SignOutModalProps {
  isOpen: boolean;
  displayName: string;
}

export default function SignOutModal({ isOpen, displayName }: SignOutModalProps) {
  const { t } = useTranslation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-[9999] flex items-center justify-center p-4 pointer-events-auto"
        >
          {/* Backdrop Blur */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="fixed inset-0 bg-black/70 backdrop-blur-md"
          />

          {/* Modal Card */}
          <motion.div
            initial={{ opacity: 0, scale: 0.92, y: 15 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            transition={{ type: "spring", stiffness: 350, damping: 25 }}
            className="relative w-full max-w-[360px] rounded-3xl p-6 sm:p-7 border shadow-2xl overflow-hidden text-center z-10"
            style={{
              background: "var(--bg-glass-elevated)",
              borderColor: "var(--border-strong)",
              boxShadow: "0 25px 60px -15px rgba(0,0,0,0.7), inset 0 1px 0 rgba(255,255,255,0.08)",
            }}
          >
            {/* Ambient Background Glow */}
            <div className="absolute -top-16 left-1/2 -translate-x-1/2 w-48 h-48 rounded-full bg-[var(--accent-primary)]/15 blur-3xl pointer-events-none" />

            {/* Ghost / Avatar Animation */}
            <div className="relative mb-4 flex items-center justify-center">
              <motion.div
                animate={{ y: [0, -5, 0] }}
                transition={{ duration: 2.8, repeat: Infinity, ease: "easeInOut" }}
                className="relative flex items-center justify-center"
              >
                {/* Outer Glow Ring */}
                <div className="absolute inset-0 size-16 rounded-full bg-[var(--accent-primary)]/20 blur-md animate-pulse" />
                <div className="relative size-16 rounded-2xl border border-[var(--border-strong)] bg-[var(--surface-elevated)] flex items-center justify-center shadow-lg text-[var(--accent-primary)]">
                  <GhostIcon size={34} />
                </div>
              </motion.div>
            </div>

            {/* Title & Greeting */}
            <h3 className="text-lg font-bold text-[var(--text-primary)] mb-1.5 tracking-tight">
              {t("auth.signingOutTitle", { name: displayName })}
            </h3>

            {/* Subtitle */}
            <p className="text-xs text-[var(--text-secondary)] mb-5 max-w-[270px] mx-auto leading-relaxed">
              {t("auth.signingOutSubtitle")}
            </p>

            {/* Undulating Audio Waveform Visualizer */}
            <div className="flex items-center justify-center gap-1.5 h-7 mb-4">
              {[0.4, 0.9, 0.6, 1.0, 0.5, 0.8, 0.3].map((height, i) => (
                <motion.span
                  key={i}
                  className="w-1 rounded-full bg-gradient-to-t from-[var(--accent-primary)] to-cyan-300"
                  animate={{
                    scaleY: [height * 0.4, height * 1.2, height * 0.4],
                  }}
                  transition={{
                    duration: 1.1,
                    repeat: Infinity,
                    ease: "easeInOut",
                    delay: i * 0.12,
                  }}
                  style={{
                    height: "100%",
                    transformOrigin: "center",
                  }}
                />
              ))}
            </div>

            {/* Status Indicator Pill */}
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-base)]/80 text-[11px] font-medium text-[var(--text-muted)]">
              <Loader2 size={12} className="animate-spin text-[var(--accent-primary)]" />
              <span>{t("auth.signingOutStatus")}</span>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body
  );
}
