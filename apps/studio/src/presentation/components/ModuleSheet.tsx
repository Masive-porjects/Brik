"use client";

import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import IconButton from "@/components/ui/IconButton";

interface ModuleSheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

/* ── Module Modal (centered crystal glass) ─────────────
   Half-screen glass panel replaced by a centered modal
   with pronounced glassmorphism: heavy blur, saturation,
   frosted highlight edge. Opens and closes with the same
   smooth clip-path curtain so the motion is symmetric. */

export default function ModuleSheet({
  open,
  onClose,
  title,
  subtitle,
  children,
}: ModuleSheetProps) {
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
    <AnimatePresence mode="wait">
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="modal-backdrop"
            className="fixed inset-0 z-[110] bg-black/60 backdrop-blur-md"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            onClick={onClose}
          />

          {/* Centered wrapper — pointer-events-none so the
              backdrop catches clicks outside the panel */}
          <div className="fixed inset-0 z-[120] flex items-center justify-center p-4 sm:p-8 pointer-events-none">
            <motion.div
              key="modal-panel"
              role="dialog"
              aria-modal="true"
              aria-label={title}
              className="pointer-events-auto relative w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden rounded-2xl
                border shadow-[var(--shadow-heavy)]
                backdrop-blur-2xl backdrop-saturate-150"
              style={{
                background: "var(--bg-glass-elevated)",
                borderColor: "var(--border-strong)",
              }}
              initial={{ clipPath: "inset(0 0 100% 0)", opacity: 0 }}
              animate={{
                clipPath: "inset(0 0 0% 0)",
                opacity: 1,
                transition: {
                  clipPath: { duration: 0.55, ease: [0.65, 0, 0.35, 1] },
                  opacity: { duration: 0.25 },
                },
              }}
              exit={{
                clipPath: "inset(0 0 100% 0)",
                opacity: 0,
                transition: {
                  clipPath: { duration: 0.5, ease: [0.65, 0, 0.35, 1] },
                  opacity: { duration: 0.25 },
                },
              }}
            >
              {/* Frosted highlight edge (crystal rim light) */}
              <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent" />
              <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/[0.07] to-transparent" />

              {/* Header */}
              <motion.div
                className="relative shrink-0 flex items-center justify-between px-6 py-4 border-b border-[var(--border-subtle)]"
                initial={{ y: 12, opacity: 0 }}
                animate={{ y: 0, opacity: 1, transition: { delay: 0.2, duration: 0.35, ease: "easeOut" } }}
                exit={{ y: 12, opacity: 0, transition: { duration: 0.2 } }}
              >
                <div>
                  <h2
                    className="text-base font-semibold text-[var(--text-primary)]"
                    style={{ letterSpacing: "-0.02em" }}
                  >
                    {title}
                  </h2>
                  {subtitle && (
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">{subtitle}</p>
                  )}
                </div>
                <IconButton
                  label="Cerrar panel"
                  icon={X}
                  onClick={onClose}
                  className="shrink-0"
                />
              </motion.div>

              {/* Content */}
              <motion.div
                className="relative flex-1 overflow-y-auto px-6 py-5"
                initial={{ y: 16, opacity: 0 }}
                animate={{ y: 0, opacity: 1, transition: { delay: 0.3, duration: 0.35, ease: "easeOut" } }}
                exit={{ y: 16, opacity: 0, transition: { duration: 0.2 } }}
              >
                {children}
              </motion.div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}
