"use client";

import { motion } from "framer-motion";
import { fadeUp } from "@/shared/motion";
import Player from "@/presentation/components/Player";
import MobilePresetStrip from "@/presentation/components/MobilePresetStrip";
import MixGateNotice, {
  type MixGateState,
} from "@/presentation/components/MixGateNotice";
import type { MasteringParameters, SessionData } from "@/lib/api";
import { getAudioUrl } from "@/lib/api";
import { isPresetCompleted } from "@/lib/audioUtils";
import type { MasteringTab } from "@/presentation/components/dock/types";
import { useTranslation } from "@/i18n/useTranslation";

interface MobileMasteringViewProps {
  session: SessionData | null;
  currentTab: MasteringTab | null;
  sheetTab: MasteringTab | null;
  setCurrentTab: (tab: MasteringTab | null) => void;
  activePresetId: string | null;
  processing: boolean;
  masterBurst: number;
  error: string | null;
  onPresetSelect: (p: MasteringParameters, id?: string) => Promise<void>;
  onProcess: () => Promise<void>;
  onDownload: (format: "wav" | "mp3") => void;
  renderTabContent: (tab: MasteringTab) => React.ReactNode;
  /** Gate de mezcla (T4): aviso accionable sobre el botón de masterizar.
   *  En mobile el CTA abre el tab de mezcla, que en esta vista se llama igual
   *  que en desktop ("mezcla"). */
  mixGate?: MixGateState;
}

export default function MobileMasteringView({
  session,
  currentTab,
  sheetTab,
  setCurrentTab,
  activePresetId,
  processing,
  masterBurst,
  error,
  onPresetSelect,
  onProcess,
  onDownload,
  renderTabContent,
  mixGate,
}: MobileMasteringViewProps) {
  const { t } = useTranslation();

  return (
    <>
      {/* Player en la parte superior — visible siempre excepto en pestaña Mezcla */}
      {currentTab !== "mezcla" && sheetTab !== "mezcla" && (
        <div className="relative z-[1] shrink-0 px-4 pt-3 pb-1">
          {session && (
            <Player
              originalUrl={getAudioUrl(session.session_id, "original")}
              masteredUrl={
                isPresetCompleted(session, activePresetId)
                  ? getAudioUrl(
                      session.session_id,
                      "mastered",
                      activePresetId ?? undefined,
                    )
                  : null
              }
              disabled={processing}
              presetId={activePresetId ?? undefined}
              sessionId={session.session_id}
              burstSignal={masterBurst}
            />
          )}
        </div>
      )}

      {/* Contenido móvil según pestaña activa o flujo predeterminado */}
      {currentTab !== null && currentTab !== "modules" ? (
        <div className="relative z-[1] flex-1 overflow-y-auto px-4 pt-3 pb-28 pb-safe">
          {renderTabContent(currentTab)}
        </div>
      ) : (
        <div className="relative z-[1] flex-1 overflow-y-auto px-4 pt-3 pb-8 pb-safe">
          {/* Banner de error */}
          {error && (
            <motion.div className="mb-3" {...fadeUp(0)}>
              <div
                className="p-3 rounded-xl text-xs"
                style={{
                  background: "rgba(220, 38, 38, 0.08)",
                  border: "1px solid rgba(220, 38, 38, 0.2)",
                  color: "var(--accent-error)",
                }}
              >
                {error}
              </div>
            </motion.div>
          )}

          {/* Selector horizontal de presets */}
          <div className="mb-4">
            <MobilePresetStrip
              activePresetId={activePresetId}
              onSelect={onPresetSelect}
              disabled={processing}
            />
          </div>

          {/* Gate de mezcla (T4): mismo banner que en desktop, sobre el botón
              de masterizar (ver `MixGateNotice`). */}
          <MixGateNotice gate={mixGate} className="mb-3" />

          {/* Botón prominente de procesamiento */}
          <button
            onClick={onProcess}
            disabled={processing || !session}
            className="w-full py-3.5 rounded-2xl text-sm font-semibold
              transition-all duration-300 ease-out
              disabled:opacity-40 disabled:cursor-not-allowed
              hover:brightness-110 active:scale-[0.98]"
            style={{
              background: processing
                ? "rgba(98, 126, 132, 0.06)"
                : "linear-gradient(135deg, rgba(98,126,132,0.2), rgba(98,126,132,0.08))",
              border: "1px solid rgba(98,126,132,0.25)",
              color: "var(--accent-primary)",
            }}
          >
            {processing ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                {t("common.processing", "Procesando audio...")}
              </span>
            ) : (
              t("mastering.processWithPreset", "Procesar con este preset")
            )}
          </button>

          {/* Botones de descarga */}
          {session?.mastered_path && (
            <div className="mt-4 space-y-2">
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest text-center">
                {t("mastering.downloadMaster", "Descargar master")}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => onDownload("wav")}
                  className="flex-1 py-2.5 rounded-xl text-xs font-medium text-center
                    text-[var(--text-secondary)] hover:text-[var(--text-primary)]
                    bg-[var(--surface-hover)] hover:bg-[var(--surface-active)]
                    transition-all border border-[var(--border-subtle)]"
                >
                  WAV (24-bit)
                </button>
                <button
                  onClick={() => onDownload("mp3")}
                  className="flex-1 py-2.5 rounded-xl text-xs font-medium text-center
                    text-[var(--text-secondary)] hover:text-[var(--text-primary)]
                    bg-[var(--surface-hover)] hover:bg-[var(--surface-active)]
                    transition-all border border-[var(--border-subtle)]"
                >
                  MP3 (320kbps)
                </button>
              </div>
            </div>
          )}

          {/* Resumen de análisis compacto */}
          {session?.analysis && (
            <div
              className="mt-4 p-3 rounded-xl"
              style={{
                background: "var(--bg-glass)",
                border: "1px solid var(--border-subtle)",
                backdropFilter: "blur(12px)",
                WebkitBackdropFilter: "blur(12px)",
              }}
            >
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-2">
                {t("nav.analysis", "Análisis")}
              </p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="min-w-0">
                  <p className="text-xs font-mono text-[var(--text-primary)]">
                    {session.analysis.integrated_lufs.toFixed(1)}
                  </p>
                  <p className="text-[9px] text-[var(--text-muted)]">LUFS</p>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-mono text-[var(--text-primary)]">
                    {session.analysis.tempo_bpm.toFixed(0)}
                  </p>
                  <p className="text-[9px] text-[var(--text-muted)]">BPM</p>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-mono text-[var(--text-primary)] truncate">
                    {session.analysis.detected_genre !== "other"
                      ? session.analysis.detected_genre.replace("_", " ")
                      : "—"}
                  </p>
                  <p className="text-[9px] text-[var(--text-muted)]">
                    {t("report.genre", "Género")}
                  </p>
                </div>
              </div>
              {session.analysis.is_already_mastered && (
                <div
                  className="mt-2 p-2 rounded-lg text-[10px] leading-relaxed"
                  style={{
                    background: "rgba(255,159,10,0.08)",
                    border: "1px solid rgba(255,159,10,0.2)",
                    color: "#fbbf24",
                  }}
                >
                  ⚠️ {t("report.alreadyMasteredNotice", "Audio ya masterizado — riesgo de sobremasterización")}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Botón flotante para regresar al flujo principal */}
      {currentTab !== null && currentTab !== "modules" && (
        <button
          onClick={() => setCurrentTab("modules")}
          className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50
            px-4 py-2 rounded-full text-xs font-medium
            bg-[var(--bg-glass-elevated)] border border-[var(--border-strong)]
            text-[var(--text-secondary)] hover:text-[var(--text-primary)]
            shadow-lg backdrop-blur-md transition-all"
        >
          {t("common.backToMainFlow", "← Volver al flujo principal")}
        </button>
      )}
    </>
  );
}
