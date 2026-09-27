"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Music4, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "@/i18n";

export interface TrackChipProps {
  /** Ruta del archivo original que devolvió el backend. */
  originalPath?: string | null;
  /** Género detectado por el análisis, si ya llegó. */
  genre?: string | null;
  disabled?: boolean;
  onChangeTrack: () => void;
}

export default function TrackChip({
  genre,
  disabled = false,
  onChangeTrack,
}: TrackChipProps) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);

  const label = genre
    ? t(`trackChip.genres.${genre}`, genre.charAt(0).toUpperCase() + genre.slice(1))
    : undefined;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.25, 0.1, 0.25, 1] }}
      className="flex items-center gap-2 rounded-full border px-3 py-1.5 backdrop-blur-xl"
      style={{
        background: "var(--bg-glass)",
        borderColor: "var(--border-subtle)",
      }}
    >
      <Music4
        size={13}
        strokeWidth={1.75}
        aria-hidden
        style={{ color: "var(--accent-primary)" }}
      />

      <span
        className="max-w-[10rem] truncate text-xs font-medium tracking-tight"
        style={{ color: "var(--text-primary)" }}
      >
        {label ?? t("trackChip.yourTrack", "Tu track")}
      </span>

      <AnimatePresence mode="wait" initial={false}>
        {confirming ? (
          <motion.span
            key="confirm"
            initial={{ opacity: 0, width: 0 }}
            animate={{ opacity: 1, width: "auto" }}
            exit={{ opacity: 0, width: 0 }}
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            className="flex shrink-0 items-center gap-1 overflow-hidden whitespace-nowrap"
          >
            <button
              type="button"
              onClick={onChangeTrack}
              className="rounded-full px-2 py-0.5 text-[11px] font-medium transition-colors duration-200"
              style={{ background: "var(--accent-primary)", color: "var(--text-primary)" }}
            >
              {t("trackChip.confirmYes", "Sí, cambiar")}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-full px-2 py-0.5 text-[11px] transition-colors duration-200"
              style={{ color: "var(--text-muted)" }}
            >
              {t("trackChip.confirmNo", "No")}
            </button>
          </motion.span>
        ) : (
          <motion.button
            key="change"
            type="button"
            disabled={disabled}
            onClick={() => setConfirming(true)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            whileHover={disabled ? undefined : { rotate: -35 }}
            transition={{ duration: 0.25 }}
            aria-label={t("trackChip.changeTrack", "Cambiar de track")}
            title={t("trackChip.changeTrack", "Cambiar de track")}
            className="flex size-6 shrink-0 items-center justify-center rounded-full transition-colors
              duration-300 disabled:opacity-30"
            style={{ color: "var(--text-muted)" }}
          >
            <RefreshCw size={13} strokeWidth={1.75} />
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
