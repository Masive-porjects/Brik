"use client";

import { ChevronRight } from "lucide-react";
import SignalChain from "@/presentation/components/SignalChain";
import AnalysisPanel from "@/presentation/components/AnalysisPanel";
import StereoField from "@/presentation/components/StereoField";
import ShareCard from "@/presentation/components/ShareCard";
import { ComingSoonNotice } from "@/presentation/components/ComingSoonNotice";
import DropZone from "@/presentation/components/DropZone";
import type { MasteringParameters, SessionData } from "@/lib/api";
import { getAudioUrl } from "@/lib/api";
import type { MasteringTab } from "@/presentation/components/dock/types";
import { useTranslation } from "@/i18n/useTranslation";

interface AnalysisSidebarProps {
  open: boolean;
  onClose: () => void;
  currentTab: MasteringTab | null;
  onSelectTab: (tab: MasteringTab) => void;
  session: SessionData | null;
  params: MasteringParameters;
  activePresetId: string | null;
  onDownload: (format: "wav" | "mp3") => void;
  onFileSelected: (file: File) => void;
  onError: (title: string, message: string) => void;
  loading: boolean;
}

export default function AnalysisSidebar({
  open,
  onClose,
  currentTab,
  onSelectTab,
  session,
  params,
  activePresetId,
  onDownload,
  onFileSelected,
  onError,
  loading,
}: AnalysisSidebarProps) {
  const { t } = useTranslation();

  return (
    <aside
      className={`shrink-0 border-l border-[var(--border-subtle)] bg-[var(--bg-app)]/80 backdrop-blur-md transition-all duration-300 ease-out overflow-hidden ${
        open ? "w-80 lg:w-96" : "w-0"
      }`}
    >
      <div className="w-80 lg:w-96 h-full flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)] shrink-0">
          <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-widest">
            {t("report.panelTitle", "Panel de Análisis")}
          </span>
          <button
            onClick={onClose}
            aria-label={t("common.close", "Cerrar")}
            className="w-6 h-6 rounded-md hover:bg-[var(--surface-hover)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all cursor-pointer"
          >
            <ChevronRight size={14} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {currentTab === "pipeline" ? (
            <>
              <SignalChain params={params} />
              {session?.mastered_path && (
                <div className="rounded-xl border border-dashed border-[var(--border-subtle)] p-3 text-center mt-4">
                  <p className="text-[10px] text-[var(--text-muted)]">
                    {t(
                      "analysis.viewFullPrompt",
                      "¿Quieres ver el análisis completo y descargar?",
                    )}
                  </p>
                  <button
                    onClick={() => onSelectTab("analysis")}
                    className="mt-1 text-[10px] font-medium text-[var(--accent-primary)] hover:underline"
                  >
                    {t("analysis.openAnalysis", "Abrir Análisis →")}
                  </button>
                </div>
              )}
            </>
          ) : currentTab === "analysis" ? (
            <>
              <AnalysisPanel
                analysis={session?.analysis ?? null}
                presetId={activePresetId ?? undefined}
                masterResult={session?.master_result ?? null}
                validation={session?.validation ?? null}
              />

              {/* Botones de Descarga */}
              {session?.mastered_path && (
                <div className="space-y-2">
                  <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">
                    {t("common.download", "Descargar")}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => onDownload("wav")}
                      className="flex-1 py-2.5 rounded-lg text-xs font-medium text-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--surface-hover)] hover:bg-[var(--surface-active)] transition-all border border-[var(--border-subtle)]"
                    >
                      WAV
                    </button>
                    <button
                      onClick={() => onDownload("mp3")}
                      className="flex-1 py-2.5 rounded-lg text-xs font-medium text-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--surface-hover)] hover:bg-[var(--surface-active)] transition-all border border-[var(--border-subtle)]"
                    >
                      MP3
                    </button>
                    <ShareCard
                      sessionId={session.session_id}
                      originalPath={session.original_path}
                      presetId={activePresetId}
                      analysis={session.analysis}
                      masterResult={session.master_result ?? null}
                    />
                  </div>
                </div>
              )}
            </>
          ) : currentTab === "stereo" ? (
            <>
              {session?.mastered_path ? (
                <StereoField
                  audioUrl={getAudioUrl(
                    session.session_id,
                    "mastered",
                    activePresetId ?? undefined,
                  )}
                />
              ) : (
                <div className="rounded-xl border border-dashed border-[var(--border-subtle)] p-4 text-center">
                  <p className="text-xs leading-relaxed text-[var(--text-muted)]">
                    {t(
                      "stereo.needMasteredFirst",
                      "Primero necesitas masterizar un track para ver el campo estéreo.",
                    )}
                  </p>
                </div>
              )}
            </>
          ) : currentTab === "live" ? (
            <ComingSoonNotice
              title="Live Engine"
              message={t(
                "live.comingSoonNotice",
                "El motor de efectos en vivo llega pronto. Por ahora, masterizá y escuchá el resultado en Análisis.",
              )}
            />
          ) : (
            <div className="rounded-xl border border-dashed border-[var(--border-subtle)] p-4 text-center">
              <p className="text-xs leading-relaxed text-[var(--text-muted)]">
                {t("analysis.dockHintPrefix", "Abre el módulo")}{" "}
                <span className="text-[var(--text-secondary)]">
                  {t("nav.analysis", "Análisis")}
                </span>{" "}
                {t(
                  "analysis.dockHintSuffix",
                  "desde el dock para ver los resultados y descargar tu master.",
                )}
              </p>
              <button
                onClick={() => onSelectTab("analysis")}
                className="mt-2 text-xs font-medium text-[var(--accent-primary)] hover:underline cursor-pointer"
              >
                {t("analysis.openAnalysisShort", "Abrir Análisis")}
              </button>
            </div>
          )}

          {/* Subir otro track */}
          <div>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mb-2">
              {t("upload.uploadAnother", "Subir otro track")}
            </p>
            <DropZone
              onFileSelected={onFileSelected}
              onError={onError}
              disabled={loading}
              compact
            />
          </div>
        </div>
      </div>
    </aside>
  );
}
