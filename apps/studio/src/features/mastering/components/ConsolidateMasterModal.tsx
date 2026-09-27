"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Download,
  Sliders,
  CheckCircle2,
  X,
  FileAudio,
  Radio,
  AlertCircle,
} from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import { GhostIcon } from "@/presentation/components/ThemeToggle";
import { MusicNote } from "@/presentation/components/Player";
import type { Track, MasterRecord } from "@/features/tracks";
import type { MasteringParameters } from "@/lib/api";

interface ConsolidateMasterModalProps {
  isOpen: boolean;
  onClose: () => void;
  track: Track | null;
  params: MasteringParameters;
  activePresetId: string | null;
  isConsolidating: boolean;
  onConfirm: (options: { name: string; format: "wav" | "mp3" }) => Promise<MasterRecord | null>;
}

export default function ConsolidateMasterModal({
  isOpen,
  onClose,
  track,
  params,
  activePresetId,
  isConsolidating,
  onConfirm,
}: ConsolidateMasterModalProps) {
  const { t } = useTranslation();

  const [masterName, setMasterName] = useState("");
  const [format, setFormat] = useState<"wav" | "mp3">("wav");
  const [successRecord, setSuccessRecord] = useState<MasterRecord | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (track) {
      const presetSuffix = activePresetId ? ` (${activePresetId})` : "";
      setMasterName(`${track.title} - Master Final${presetSuffix}`);
      setSuccessRecord(null);
      setErrorMessage(null);
    }
  }, [track, activePresetId, isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!masterName.trim() || isConsolidating) return;
    setErrorMessage(null);

    try {
      const result = await onConfirm({
        name: masterName.trim(),
        format,
      });

      if (result) {
        setSuccessRecord(result);
        setTimeout(() => {
          onClose();
          setSuccessRecord(null);
        }, 1600);
      } else {
        setErrorMessage(
          t(
            "mastering.consolidateError",
            "No se pudo guardar la mezcla en la nube de Supabase. Revisa tu conexión o intenta nuevamente."
          )
        );
      }
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : t(
              "mastering.consolidateError",
              "No se pudo guardar la mezcla en la nube de Supabase. Revisa tu conexión o intenta nuevamente."
            )
      );
    }
  };

  return (
    <AnimatePresence>
      {isOpen && track && (
        <motion.div
          key="consolidate-modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22, ease: "easeOut" }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-2xl bg-black/80"
          role="dialog"
          aria-modal="true"
          aria-labelledby="consolidate-modal-title"
        >
          <motion.div
            key="consolidate-modal-card"
            initial={{ scale: 0.94, opacity: 0, y: 16 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.94, opacity: 0, y: 16 }}
            transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
            className="relative flex flex-col w-full max-w-lg rounded-3xl border overflow-hidden p-6 sm:p-7 shadow-2xl"
            style={{
              background:
                "linear-gradient(135deg, rgba(28, 36, 38, 0.96) 0%, rgba(16, 22, 23, 0.98) 100%)",
              borderColor: "rgba(255, 255, 255, 0.12)",
              boxShadow:
                "0 32px 80px -15px rgba(0, 0, 0, 0.9), 0 0 0 1px rgba(255, 255, 255, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
            }}
          >
            {/* Ambient Mystical Light Gradients */}
            <div
              className="pointer-events-none absolute -top-24 -left-20 size-64 rounded-full blur-3xl opacity-20"
              style={{ background: "var(--accent-primary)" }}
              aria-hidden="true"
            />
            <div
              className="pointer-events-none absolute -bottom-24 -right-20 size-64 rounded-full blur-3xl opacity-15"
              style={{ background: "var(--accent-secondary)" }}
              aria-hidden="true"
            />

            {/* Ambient Floating Notes in Modal Corners */}
            <div className="pointer-events-none absolute top-4 right-14 opacity-25" aria-hidden="true">
              <MusicNote color="#4ecdc4" size={14} />
            </div>
            <div className="pointer-events-none absolute bottom-4 left-6 opacity-20" aria-hidden="true">
              <MusicNote color="#ffb347" size={12} />
            </div>
            <div className="pointer-events-none absolute top-14 left-4 opacity-15" aria-hidden="true">
              <GhostIcon size={16} />
            </div>

            {/* Header */}
            <div className="relative z-10 flex items-center justify-between pb-4 border-b border-[var(--border-subtle)]">
              <div className="flex items-center gap-3">
                {/* WaveIA Brand Mascot with Orbiting Notes */}
                <div className="relative size-11 rounded-2xl bg-gradient-to-br from-emerald-500/20 via-[var(--accent-primary)]/15 to-transparent border border-emerald-500/30 flex items-center justify-center shadow-lg shadow-emerald-500/10 text-[var(--accent-primary)]">
                  <GhostIcon size={22} />
                  <span className="absolute -top-1 -right-1 animate-bounce">
                    <MusicNote color="#4ecdc4" size={10} />
                  </span>
                  <span className="absolute -bottom-1 -left-1 opacity-70">
                    <MusicNote color="#7b68ee" size={9} />
                  </span>
                </div>
                <div>
                  <h3
                    id="consolidate-modal-title"
                    className="text-base font-bold tracking-tight text-[var(--text-primary)]"
                  >
                    {t("mastering.consolidateTitle", "Definir Mezcla Final")}
                  </h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    {t(
                      "mastering.consolidateSubtitle",
                      "Exporta tu master definitivo a la nube de Supabase"
                    )}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={onClose}
                disabled={isConsolidating}
                className="size-8 rounded-full flex items-center justify-center text-[var(--text-muted)] hover:text-white hover:bg-white/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label={t("common.close", "Cerrar")}
              >
                <X size={16} />
              </button>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="relative z-10 mt-5 space-y-4">
              {/* Master Name Input */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
                  {t("mastering.masterNameLabel", "Nombre de la Mezcla / Master")}
                </label>
                <input
                  type="text"
                  value={masterName}
                  onChange={(e) => setMasterName(e.target.value)}
                  disabled={isConsolidating}
                  required
                  className="w-full px-4 py-2.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-hover)] text-sm font-medium text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)] transition-all placeholder:text-[var(--text-muted)] disabled:opacity-50"
                  placeholder="ej: Astrosoul - Mezcla Spotify Oficial"
                />
              </div>

              {/* Format Selection */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
                  {t("mastering.formatLabel", "Formato de Exportación")}
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setFormat("wav")}
                    disabled={isConsolidating}
                    className={`flex items-center gap-3 p-3 rounded-2xl border text-left transition-all cursor-pointer disabled:cursor-not-allowed ${
                      format === "wav"
                        ? "border-emerald-500/50 bg-emerald-500/10 shadow-sm shadow-emerald-500/10 ring-1 ring-emerald-500/30"
                        : "border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)]"
                    }`}
                  >
                    <FileAudio
                      className={`size-5 shrink-0 ${
                        format === "wav" ? "text-emerald-400" : "text-[var(--text-muted)]"
                      }`}
                    />
                    <div>
                      <div className="text-xs font-bold text-[var(--text-primary)]">WAV (24-bit)</div>
                      <div className="text-[10px] text-[var(--text-muted)]">Sin compresión / Estudio</div>
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setFormat("mp3")}
                    disabled={isConsolidating}
                    className={`flex items-center gap-3 p-3 rounded-2xl border text-left transition-all cursor-pointer disabled:cursor-not-allowed ${
                      format === "mp3"
                        ? "border-emerald-500/50 bg-emerald-500/10 shadow-sm shadow-emerald-500/10 ring-1 ring-emerald-500/30"
                        : "border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)]"
                    }`}
                  >
                    <Radio
                      className={`size-5 shrink-0 ${
                        format === "mp3" ? "text-emerald-400" : "text-[var(--text-muted)]"
                      }`}
                    />
                    <div>
                      <div className="text-xs font-bold text-[var(--text-primary)]">MP3 (320 kbps)</div>
                      <div className="text-[10px] text-[var(--text-muted)]">Streaming / Compartir</div>
                    </div>
                  </button>
                </div>
              </div>

              {/* Recipe summary badge */}
              <div className="p-3.5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)]/60 text-xs space-y-1.5 backdrop-blur-md">
                <div className="flex items-center justify-between text-[var(--text-secondary)] font-medium">
                  <span className="flex items-center gap-1.5">
                    <Sliders size={13} className="text-[var(--accent-secondary)]" />
                    <span>{t("mastering.activePreset", "Perfil activo:")}</span>
                  </span>
                  <span className="font-bold text-[var(--text-primary)] capitalize">
                    {activePresetId || t("mastering.customSetting", "Ajuste Personalizado")}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-[var(--text-muted)]">
                  <span>{t("mastering.targetLoudness", "Objetivo sonoridad:")}</span>
                  <span>
                    {params.target_lufs_db ?? -14} LUFS · Ceiling {params.limiter_ceiling_db ?? -1.0} dB
                  </span>
                </div>
              </div>

              {/* Error feedback banner inside modal */}
              {errorMessage && (
                <div className="p-3.5 rounded-2xl bg-red-500/15 border border-red-500/30 flex items-start gap-3 text-xs text-red-200 animate-in fade-in">
                  <AlertCircle className="size-4 text-red-400 shrink-0 mt-0.5" />
                  <div className="flex-1 space-y-0.5">
                    <div className="font-bold text-red-300">
                      {t("common.error", "Error al consolidar")}
                    </div>
                    <p className="text-[11px] text-red-200/90 leading-relaxed">
                      {errorMessage}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setErrorMessage(null)}
                    className="p-1 rounded-md hover:bg-white/10 text-red-300 transition-colors cursor-pointer"
                    aria-label={t("common.close", "Cerrar")}
                  >
                    <X size={13} />
                  </button>
                </div>
              )}

              {/* Success banner */}
              {successRecord && (
                <div className="p-3.5 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 flex items-center gap-2.5 text-xs text-emerald-300 font-semibold animate-in fade-in">
                  <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
                  <span>
                    {t(
                      "mastering.consolidateSuccess",
                      "¡Mezcla final subida a Supabase y descargada con éxito!"
                    )}
                  </span>
                </div>
              )}

              {/* Actions */}
              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isConsolidating}
                  className="px-4 py-2.5 rounded-xl text-xs font-semibold text-[var(--text-secondary)] hover:text-white hover:bg-white/5 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {errorMessage ? t("common.close", "Cerrar") : t("common.cancel", "Cancelar")}
                </button>

                <button
                  type="submit"
                  disabled={isConsolidating || !masterName.trim()}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black text-xs font-bold shadow-lg shadow-emerald-500/20 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
                >
                  {isConsolidating ? (
                    <>
                      <span className="size-3.5 border-2 border-black border-t-transparent rounded-full animate-spin" />
                      <span>{t("mastering.consolidateSaving", "Guardando en la nube...")}</span>
                    </>
                  ) : (
                    <>
                      <Download size={14} />
                      <span>
                        {errorMessage
                          ? t("mastering.retrySave", "Reintentar Guardado")
                          : t("mastering.consolidateAction", "Consolidar y Guardar")}
                      </span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
