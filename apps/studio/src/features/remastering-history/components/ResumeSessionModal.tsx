"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  Music2,
  Sparkles,
  CheckCircle2,
  Clock,
  ArrowRight,
  PlusCircle,
  FolderOpen,
  Radio,
  Sliders,
  AudioWaveform,
  Disc3,
} from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import { useAuth } from "@/features/auth";
import type { Track } from "@/features/tracks";

interface ResumeSessionModalProps {
  isOpen: boolean;
  track: Track | null;
  onContinue: (track: Track) => void;
  onNewTrack: () => void;
  onOpenLibrary: () => void;
  isLoading?: boolean;
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "--:--";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

export default function ResumeSessionModal({
  isOpen,
  track,
  onContinue,
  onNewTrack,
  onOpenLibrary,
  isLoading = false,
}: ResumeSessionModalProps) {
  const { t } = useTranslation();
  const { user, profile } = useAuth();

  if (!isOpen || !track) return null;

  const displayName =
    profile?.display_name ||
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "Productor";

  const hasDraft = !!track.draft_parameters;
  const hasMasters = track.masters && track.masters.length > 0;
  const isMastered = track.status === "completed" || hasMasters;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-2xl bg-black/75"
        role="dialog"
        aria-modal="true"
        aria-labelledby="resume-modal-title"
      >
        <motion.div
          initial={{ scale: 0.92, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.92, opacity: 0, y: 20 }}
          transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
          className="relative flex flex-col w-full max-w-md rounded-3xl border overflow-hidden p-6 sm:p-8"
          style={{
            background:
              "linear-gradient(135deg, rgba(32, 40, 42, 0.95) 0%, rgba(18, 24, 25, 0.98) 100%)",
            borderColor: "rgba(255, 255, 255, 0.12)",
            boxShadow:
              "0 36px 90px -15px rgba(0, 0, 0, 0.95), 0 0 0 1px rgba(255, 255, 255, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
          }}
        >
          {/* Luminous Ambient Highlights */}
          <div
            className="absolute -top-20 -left-20 size-52 rounded-full blur-3xl pointer-events-none opacity-30"
            style={{ background: "var(--accent-primary)" }}
          />
          <div
            className="absolute -bottom-24 -right-20 size-52 rounded-full blur-3xl pointer-events-none opacity-20"
            style={{ background: "var(--accent-secondary, #627e84)" }}
          />

          {/* Header */}
          <div className="relative flex items-center gap-3.5 mb-6">
            <div className="relative size-12 rounded-2xl flex items-center justify-center bg-gradient-to-br from-[var(--accent-primary)]/25 to-[var(--accent-secondary)]/10 border border-[var(--accent-primary)]/40 text-[var(--accent-primary)] shadow-lg shadow-[var(--accent-primary)]/15 shrink-0">
              <Disc3 size={24} className="animate-spin-slow" />
              <span className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full bg-emerald-400 ring-2 ring-[var(--bg-app)]" />
            </div>
            <div className="min-w-0">
              <h2
                id="resume-modal-title"
                className="text-lg font-bold tracking-tight text-[var(--text-primary)] truncate"
              >
                {t("resume.title", { name: displayName }, `¡Hola, ${displayName}!`)}
              </h2>
              <p className="text-xs text-[var(--text-secondary)]">
                {t("resume.subtitle", "¿Deseas continuar trabajando en tu última producción?")}
              </p>
            </div>
          </div>

          {/* Active Track Highlight Card (Vinyl Sleeve Aesthetics) */}
          <div
            className="relative flex flex-col gap-3 p-4 rounded-2xl border mb-6 transition-all duration-300"
            style={{
              background:
                "linear-gradient(180deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%)",
              borderColor: "rgba(255, 255, 255, 0.08)",
              boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 24px rgba(0,0,0,0.3)",
            }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <div className="size-11 rounded-xl flex items-center justify-center shrink-0 bg-black/40 border border-white/10 text-[var(--accent-primary)] shadow-inner">
                  {isMastered ? (
                    <CheckCircle2 size={20} className="text-emerald-400" />
                  ) : hasDraft ? (
                    <Sparkles size={20} className="text-amber-400" />
                  ) : (
                    <AudioWaveform size={20} className="text-[var(--accent-primary)]" />
                  )}
                </div>
                <div className="min-w-0">
                  <h3 className="text-sm font-bold text-[var(--text-primary)] truncate">
                    {track.title}
                  </h3>
                  <p className="text-[11px] text-[var(--text-muted)] truncate">
                    {track.original_filename}
                  </p>
                </div>
              </div>

              {/* Status Badge with soft glow */}
              {hasDraft ? (
                <span className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-amber-500/15 border border-amber-500/30 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
                  <span className="size-1.5 rounded-full bg-amber-400 animate-pulse" />
                  <span>{t("resume.draftBadge", "Borrador activo")}</span>
                </span>
              ) : isMastered ? (
                <span className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
                  <CheckCircle2 size={11} />
                  <span>{t("resume.masteredBadge", "Master listo")}</span>
                </span>
              ) : null}
            </div>

            {/* Track Specs Row */}
            <div className="flex items-center gap-2 pt-2.5 border-t border-white/5 text-[11px] text-[var(--text-secondary)] flex-wrap">
              <span className="inline-flex items-center gap-1 text-[var(--text-muted)]">
                <Clock size={11} />
                {formatDuration(track.duration_seconds)}
              </span>
              <span>•</span>
              {track.sample_rate && (
                <>
                  <span className="text-[var(--text-muted)]">
                    {(track.sample_rate / 1000).toFixed(1)} kHz
                  </span>
                  <span>•</span>
                </>
              )}
              {track.active_preset ? (
                <>
                  <span className="text-[var(--accent-primary)] font-medium">
                    Preset: {track.active_preset}
                  </span>
                  <span>•</span>
                </>
              ) : null}
              <span className="text-[var(--text-muted)]" suppressHydrationWarning>
                {formatDate(track.updated_at)}
              </span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-col gap-3">
            {/* Primary Button: Resume Project */}
            <button
              type="button"
              onClick={() => onContinue(track)}
              disabled={isLoading}
              className="group relative flex items-center justify-center gap-2.5 w-full py-3.5 px-5 rounded-2xl text-xs font-bold text-white transition-all duration-200 cursor-pointer overflow-hidden shadow-lg shadow-[var(--accent-primary)]/20 active:scale-[0.99] disabled:opacity-50"
              style={{
                background: "linear-gradient(135deg, var(--accent-primary) 0%, #44656b 100%)",
              }}
            >
              <Music2 size={16} className="transition-transform group-hover:scale-110" />
              <span>{t("resume.continueProject", "Continuar con este proyecto")}</span>
              <ArrowRight
                size={15}
                className="transition-transform group-hover:translate-x-1"
              />
            </button>

            {/* Secondary Button: New Audio */}
            <button
              type="button"
              onClick={onNewTrack}
              disabled={isLoading}
              className="flex items-center justify-center gap-2 w-full py-3 px-5 rounded-2xl text-xs font-semibold border border-white/10 bg-white/5 hover:bg-white/10 hover:border-white/20 text-[var(--text-primary)] transition-all duration-200 cursor-pointer active:scale-[0.99]"
            >
              <PlusCircle size={15} className="text-[var(--accent-primary)]" />
              <span>{t("resume.newAudio", "Subir un nuevo audio")}</span>
            </button>

            {/* Tertiary Link: Open Full Library */}
            <button
              type="button"
              onClick={onOpenLibrary}
              disabled={isLoading}
              className="mt-1 flex items-center justify-center gap-1.5 py-1 text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
            >
              <FolderOpen size={13} className="text-[var(--accent-primary)]" />
              <span>{t("resume.openLibrary", "O ver todas mis canciones guardadas")}</span>
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
