"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  SlidersHorizontal,
  Sparkles,
  Lock,
  ArrowRight,
  CheckCircle2,
  X,
  Loader2,
} from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import { GhostIcon } from "@/presentation/components/ThemeToggle";
import { MusicNote } from "@/presentation/components/Player";

interface SelectWorkflowModalProps {
  isOpen: boolean;
  trackTitle?: string;
  onConfirm: (mode: "manual" | "ai") => void;
  onClose?: () => void;
  canDismiss?: boolean;
  isLoading?: boolean;
}

export default function SelectWorkflowModal({
  isOpen,
  trackTitle,
  onConfirm,
  onClose,
  canDismiss = false,
  isLoading = false,
}: SelectWorkflowModalProps) {
  const { t } = useTranslation();
  const [selectedMode, setSelectedMode] = useState<"manual" | "ai">("manual");

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          key="workflow-modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22, ease: "easeOut" }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-2xl bg-black/80"
          role="dialog"
          aria-modal="true"
          aria-labelledby="select-workflow-title"
        >
          <motion.div
            key="workflow-modal-card"
            initial={{ scale: 0.94, opacity: 0, y: 16 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.94, opacity: 0, y: 16 }}
            transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
            className="relative flex flex-col w-full max-w-2xl rounded-3xl border overflow-hidden p-6 sm:p-8 shadow-2xl"
            style={{
              background:
                "linear-gradient(135deg, rgba(26, 32, 34, 0.96) 0%, rgba(14, 18, 19, 0.98) 100%)",
              borderColor: "rgba(255, 255, 255, 0.12)",
              boxShadow:
                "0 36px 90px -15px rgba(0, 0, 0, 0.95), 0 0 0 1px rgba(255, 255, 255, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.15)",
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

            {/* Ambient WaveIA Floating Notes & Ghost Mascot Accent */}
            <div className="pointer-events-none absolute top-4 right-16 opacity-25" aria-hidden="true">
              <MusicNote color="#4ecdc4" size={14} />
            </div>
            <div className="pointer-events-none absolute bottom-4 left-6 opacity-20" aria-hidden="true">
              <MusicNote color="#ff5a5f" size={12} />
            </div>
            <div className="pointer-events-none absolute top-12 left-5 opacity-15" aria-hidden="true">
              <GhostIcon size={18} />
            </div>

            {/* Close button if dismissible */}
            {canDismiss && onClose && (
              <button
                type="button"
                onClick={onClose}
                className="absolute top-5 right-5 p-2 rounded-full text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-all cursor-pointer"
                aria-label={t("common.close", "Cerrar")}
              >
                <X size={18} />
              </button>
            )}

            {/* Header */}
            <div className="relative z-10 text-center mb-6">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-[var(--surface-elevated)] border border-[var(--border-subtle)] text-[var(--accent-primary)] mb-3 shadow-sm">
                <span className="text-[var(--accent-primary)]">
                  <GhostIcon size={14} />
                </span>
                <span>{t("workflow.stepBadge", "Configuración de Flujo")}</span>
                <span className="opacity-70 animate-bounce">
                  <MusicNote color="#4ecdc4" size={10} />
                </span>
              </div>

              <h2
                id="select-workflow-title"
                className="text-2xl sm:text-3xl font-extrabold text-[var(--text-primary)] tracking-tight mb-2"
              >
                {t("workflow.title", "¿Cómo deseas trabajar esta pista?")}
              </h2>

              {trackTitle && (
                <p className="text-xs text-[var(--text-muted)] truncate max-w-md mx-auto mb-2">
                  <span className="text-[var(--text-secondary)] font-medium">Track:</span> {trackTitle}
                </p>
              )}

              <p className="text-xs sm:text-sm text-[var(--text-secondary)] max-w-lg mx-auto font-light leading-relaxed">
                {t(
                  "workflow.subtitle",
                  "Elige la modalidad de masterización. Podrás cambiar entre perfiles analógicos una vez ingreses a la consola."
                )}
              </p>
            </div>

            {/* Options Grid */}
            <div className="relative z-10 grid grid-cols-1 md:grid-cols-2 gap-4 mb-7">
              {/* Option 1: Manual Mode (Active) */}
              <div
                onClick={() => setSelectedMode("manual")}
                role="radio"
                aria-checked={selectedMode === "manual"}
                tabIndex={0}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSelectedMode("manual")}
                className={`relative flex flex-col justify-between p-5 rounded-2xl border transition-all duration-300 cursor-pointer text-left ${
                  selectedMode === "manual"
                    ? "bg-[var(--surface-elevated)]/90 border-[var(--accent-primary)] shadow-[0_0_24px_rgba(98,126,132,0.25)] ring-1 ring-[var(--accent-primary)]"
                    : "bg-[var(--surface-elevated)]/40 border-[var(--border-subtle)] hover:border-[var(--border-strong)] opacity-85"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="size-10 rounded-xl flex items-center justify-center bg-[var(--accent-primary)]/15 border border-[var(--accent-primary)]/30 text-[var(--accent-primary)]">
                      <SlidersHorizontal size={20} />
                    </div>
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                      <CheckCircle2 size={11} />
                      <span>{t("workflow.activeBadge", "Disponible")}</span>
                    </span>
                  </div>

                  <h3 className="text-base font-bold text-[var(--text-primary)] mb-1 flex items-center gap-2">
                    <span>{t("workflow.manualTitle", "Modo Manual")}</span>
                    <span className="text-[10px] font-semibold text-[var(--accent-primary)] uppercase tracking-wider">
                      ({t("workflow.fullControl", "Control Total")})
                    </span>
                  </h3>

                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3">
                    {t(
                      "workflow.manualDescription",
                      "Tendrás acceso completo a los 5 módulos DSP analógicos (EQ 8 bandas, Compresor dinámico, Válvulas, Limitador True-Peak y Estéreo). El balance final responde 100% a tus decisiones y criterio acústico."
                    )}
                  </p>

                  <ul className="space-y-1.5 text-[11px] text-[var(--text-muted)] border-t border-white/5 pt-3">
                    <li className="flex items-center gap-1.5 text-emerald-400/90 font-medium">
                      <span className="size-1 rounded-full bg-emerald-400" />
                      <span>{t("workflow.manualBenefit1", "Control quirúrgico y presets de género")}</span>
                    </li>
                    <li className="flex items-center gap-1.5 text-[var(--text-secondary)]">
                      <span className="size-1 rounded-full bg-[var(--accent-primary)]" />
                      <span>{t("workflow.manualBenefit2", "Monitoreo A/B en tiempo real")}</span>
                    </li>
                    <li className="flex items-center gap-1.5 text-[var(--text-secondary)]">
                      <span className="size-1 rounded-full bg-[var(--accent-primary)]" />
                      <span>{t("workflow.manualBenefit3", "Historial de borradores automáticos")}</span>
                    </li>
                  </ul>
                </div>

                <div className="mt-4 pt-3 flex items-center justify-between border-t border-white/5">
                  <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-semibold">
                    {t("workflow.recommended", "Recomendado para producción")}
                  </span>
                  <div
                    className={`size-4 rounded-full border flex items-center justify-center ${
                      selectedMode === "manual"
                        ? "border-[var(--accent-primary)] bg-[var(--accent-primary)]"
                        : "border-white/30"
                    }`}
                  >
                    {selectedMode === "manual" && <div className="size-1.5 rounded-full bg-black" />}
                  </div>
                </div>
              </div>

              {/* Option 2: AI Assistant Mode (Disabled / Phase 6) */}
              <div
                className="relative flex flex-col justify-between p-5 rounded-2xl border border-white/5 bg-[var(--surface-elevated)]/20 opacity-60 text-left cursor-not-allowed select-none"
                role="radio"
                aria-checked={false}
                aria-disabled={true}
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="size-10 rounded-xl flex items-center justify-center bg-white/5 border border-white/10 text-[var(--text-muted)]">
                      <Sparkles size={20} />
                    </div>
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-white/5 border border-white/10 text-[var(--text-muted)]">
                      <Lock size={10} />
                      <span>{t("workflow.lockedBadge", "Próximamente • Fase 6")}</span>
                    </span>
                  </div>

                  <h3 className="text-base font-bold text-[var(--text-muted)] mb-1 flex items-center gap-2">
                    <span>{t("workflow.aiTitle", "Asistente IA Autónomo")}</span>
                  </h3>

                  <p className="text-xs text-[var(--text-muted)] leading-relaxed mb-3">
                    {t(
                      "workflow.aiDescription",
                      "Un agente neural analiza el espectro sonoro, densidad armónica y rango dinámico para aplicar sugerencias de ecualización y loudness LUFS de forma automatizada."
                    )}
                  </p>

                  <div className="p-2.5 rounded-xl bg-black/30 border border-white/5 text-[11px] text-[var(--text-muted)] leading-relaxed">
                    <span className="font-semibold text-amber-400/90 block mb-0.5">
                      {t("workflow.lockedNoticeTitle", "Módulo actualmente apagado:")}
                    </span>
                    <span>
                      {t(
                        "workflow.lockedNoticeMessage",
                        "La red de inferencia acústica se integrará en la fase de Agentes Inteligentes. Todo el flujo actual opera con precisión analógica en Modo Manual."
                      )}
                    </span>
                  </div>
                </div>

                <div className="mt-4 pt-3 flex items-center justify-between border-t border-white/5">
                  <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                    {t("workflow.statusLocked", "Bloqueado en esta versión")}
                  </span>
                  <Lock size={13} className="text-[var(--text-muted)]" />
                </div>
              </div>
            </div>

            {/* Action Button */}
            <div className="relative z-10 flex flex-col sm:flex-row items-center justify-end gap-3 pt-2 border-t border-white/5">
              {canDismiss && onClose && (
                <button
                  type="button"
                  onClick={onClose}
                  className="w-full sm:w-auto px-5 py-2.5 rounded-xl font-medium text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-all cursor-pointer"
                >
                  {t("common.cancel", "Cancelar")}
                </button>
              )}

              <button
                type="button"
                disabled={isLoading}
                onClick={() => onConfirm("manual")}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-7 py-3 rounded-xl font-bold text-xs bg-[var(--accent-primary)] hover:bg-[var(--accent-hover)] text-white shadow-[0_4px_20px_rgba(98,126,132,0.35)] transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer disabled:opacity-85 disabled:cursor-wait"
              >
                {isLoading ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    <span>{t("workflow.enteringStudio", "Ingresando a la Consola...")}</span>
                  </>
                ) : (
                  <>
                    <span>{t("workflow.continueManual", "Continuar al Estudio en Modo Manual")}</span>
                    <ArrowRight size={15} />
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
