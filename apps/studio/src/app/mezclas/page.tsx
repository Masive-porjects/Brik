"use client";

import { useState, useCallback, useEffect, useMemo, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import gsap from "gsap";
import { motion, AnimatePresence } from "framer-motion";
import { VIEW_TRANSITION, fadeUp } from "@/shared/motion";
import { API_BASE } from "@/adapters/api/config";
import LicenseGuard from "@/components/LicenseGuard";
import MobileDrawer from "@/components/MobileDrawer";
import ModuleDock from "@/components/dock/ModuleDock";
import type { MasteringTab } from "@/components/dock/types";
import ModuleSheet from "@/components/ModuleSheet";
import PaintedModule from "@/components/PaintedModule";
import Player from "@/components/Player";
import { ComingSoonNotice } from "@/components/ComingSoonNotice";
import { useIsMobile } from "@/shared/useIsMobile";
import { isPresetCompleted } from "@/lib/audioUtils";
import type { MixGateState } from "@/presentation/components/MixGateNotice";
import { getAudioUrl } from "@/lib/api";
import { useTranslation } from "@/i18n";
import { ChevronLeft, AlertCircle, X } from "lucide-react";
import {
  useMastering,
  MasteringHeader,
  MasteringOverlays,
  MasteringCanvas,
  AnalysisSidebar,
  MobileMasteringView,
  ConsolidateMasterModal,
  SelectWorkflowModal,
} from "@/features/mastering";
import { LibraryView } from "@/features/remastering-history";
import { fetchUserTracks, renameTrackDraft, getUserTracksCount, type Track } from "@/features/tracks";
import { useAuth } from "@/features/auth";

const TABS: { key: MasteringTab; label: string }[] = [
  { key: "mezcla", label: "Mezcla de Audio" },
  { key: "modules", label: "Masterizar Audio" },
  { key: "splitter", label: "Splitter" },
  { key: "vocal", label: "Vocal" },
  { key: "songstarter", label: "Beats" },
  { key: "genres", label: "Guía de Géneros" },
  { key: "pipeline", label: "Cadena de Master" },
  { key: "analysis", label: "Análisis" },
  { key: "stereo", label: "Estéreo" },
  { key: "live", label: "Live Engine" },
  { key: "album", label: "Álbum" },
];

function MezclasContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const trackIdParam = searchParams.get("track");
  const modeParam = searchParams.get("mode");
  const isMobile = useIsMobile();
  const { t } = useTranslation();
  const { user } = useAuth();

  const workflow = useMastering();

  const [masteringMode, setMasteringMode] = useState<"manual" | "ai">("manual");
  const [currentTab, setCurrentTab] = useState<MasteringTab | null>(null);
  const [sheetTab, setSheetTab] = useState<MasteringTab | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [consolidateModalOpen, setConsolidateModalOpen] = useState(false);
  const [workflowModalOpen, setWorkflowModalOpen] = useState(false);
  const [hasSavedTracks, setHasSavedTracks] = useState(true);

  useEffect(() => {
    if (modeParam === "manual" || modeParam === "ai") {
      setMasteringMode(modeParam);
    }
  }, [modeParam]);

  useEffect(() => {
    if (user?.id) {
      getUserTracksCount(user.id).then((count) => {
        setHasSavedTracks(count > 0 || Boolean(workflow.currentTrack));
      });
    }
  }, [user?.id, workflow.currentTrack]);

  // If a track parameter is in the URL and not loaded, load it from Supabase
  const loadedTrackRef = useRef<string | null>(null);
  useEffect(() => {
    if (!user || !trackIdParam || loadedTrackRef.current === trackIdParam) return;
    if (workflow.currentTrack?.id === trackIdParam && workflow.session) return;

    loadedTrackRef.current = trackIdParam;
    fetchUserTracks(user.id, { page: 1, pageSize: 50 })
      .then((res) => {
        const found = res.items.find((tr) => tr.id === trackIdParam);
        if (found) {
          workflow.handleLoadTrackProject(found);
        }
      })
      .catch((err) => {
        console.error("Error loading track from URL param:", err);
      });
  }, [user, trackIdParam, workflow]);

  // If user visits /mezclas without an active session or track, send to /upload
  useEffect(() => {
    if (
      !workflow.session &&
      !workflow.loading &&
      !workflow.processing &&
      !workflow.isLoadingTrackProject &&
      !trackIdParam
    ) {
      router.replace("/upload");
    }
  }, [workflow.session, workflow.loading, workflow.processing, workflow.isLoadingTrackProject, trackIdParam, router]);

  // Right panel collapse state
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [panelSyncTab, setPanelSyncTab] = useState<MasteringTab | null>(null);

  const needsRightPanel = currentTab === "analysis" || currentTab === "stereo";
  if (currentTab !== panelSyncTab) {
    setPanelSyncTab(currentTab);
    setRightPanelOpen(needsRightPanel);
  }

  // Player stretch/reposition when a dock tab is toggled
  const playerScaleRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!playerScaleRef.current) return;
    const stretch = currentTab === null ? 1 : 1.03;
    gsap.to(playerScaleRef.current, {
      scaleX: stretch,
      scaleY: 1,
      duration: 0.9,
      ease: "power3.inOut",
      overwrite: "auto",
    });
  }, [currentTab]);

  const handleModuleClick = useCallback((tab: MasteringTab) => {
    setCurrentTab((prev) => (prev === tab ? null : tab));
    setSheetTab(null);
  }, []);

  const handleHomeClick = useCallback(() => {
    workflow.handleBackToUpload();
    router.push("/upload");
  }, [workflow, router]);

  /* ── Gate de mezcla → master (T4) ───────────────────────
     Estado único compartido por los 3 call sites de `MasteringCanvas` (mobile,
     canvas desktop, ModuleSheet) y por la vista mobile. El veredicto y los
     textos traducidos los arma el workflow; el CTA navega al tab de mezcla
     (`handleModuleClick` es el mismo toggle de tabs en mobile y desktop). */
  const mixGate = useMemo<MixGateState>(
    () => ({
      blocked: workflow.isMixGateBlocked,
      status: workflow.mixStatus,
      attempted: workflow.mixGateAttempted,
      message: workflow.mixGateNotice,
      ctaLabel: workflow.mixGateCtaLabel,
      onGoToMix: () => handleModuleClick("mezcla"),
    }),
    [
      workflow.isMixGateBlocked,
      workflow.mixStatus,
      workflow.mixGateAttempted,
      workflow.mixGateNotice,
      workflow.mixGateCtaLabel,
      handleModuleClick,
    ],
  );

  const isMezclaTab = currentTab === "mezcla" || sheetTab === "mezcla";

  return (
    <LicenseGuard>
      <main className="h-screen flex flex-col bg-[var(--bg-app)] text-[var(--text-primary)] overflow-hidden font-sans relative selection:bg-[var(--accent-primary)] selection:text-white">
        {/* Global Overlays & Modals */}
        <MasteringOverlays
          currentView="mastering"
          session={workflow.session}
          params={workflow.params}
          setParams={workflow.setParams}
          errorModal={workflow.errorModal}
          setErrorModal={workflow.setErrorModal}
          overMasterWarning={workflow.overMasterWarning}
          onOverMasterConfirm={workflow.handleOverMasterConfirm}
          onOverMasterCancel={workflow.handleOverMasterCancel}
          loading={workflow.loading}
          uploadProgress={workflow.uploadProgress}
          processing={workflow.processing}
          processingProgress={workflow.progress}
        />

        {/* Header Bar */}
        <MasteringHeader
          currentView="mastering"
          session={workflow.session}
          processing={workflow.processing}
          loading={workflow.loading}
          masteringMode={masteringMode}
          setMasteringMode={setMasteringMode}
          onBackToUpload={handleHomeClick}
          mobileMenuOpen={mobileMenuOpen}
          setMobileMenuOpen={setMobileMenuOpen}
          onClearSheet={() => setSheetTab(null)}
          autosaveStatus={workflow.autosaveStatus}
          onOpenLibrary={() => setLibraryOpen(true)}
          onConsolidate={() => setConsolidateModalOpen(true)}
          draftName={workflow.currentTrack?.draft_name || workflow.currentTrack?.active_preset || "Mezcla Principal"}
          hasSavedTracks={Boolean(workflow.currentTrack || hasSavedTracks)}
          onOpenWorkflowModal={() => setWorkflowModalOpen(true)}
          onRenameDraft={async (newName) => {
            if (workflow.currentTrack) {
              try {
                await renameTrackDraft(workflow.currentTrack.id, newName);
                workflow.setCurrentTrack({ ...workflow.currentTrack, draft_name: newName });
              } catch (err) {
                console.error("Failed to rename draft:", err);
              }
            }
          }}
        />

        {/* Mobile Navigation Drawer */}
        <MobileDrawer
          open={mobileMenuOpen}
          onClose={() => setMobileMenuOpen(false)}
          session={workflow.session}
          onBackToUpload={handleHomeClick}
        />

        {/* Main Workspaces Layout */}
        <div className="flex-1 flex min-h-0">
          <main className="flex-1 h-full flex flex-col min-w-0 relative">
            <div className="flex flex-1 min-h-0 relative">
              <div className="flex-1 flex flex-col min-w-0 relative">
                {/* AI Mode Workspace */}
                <div
                  className={`${
                    masteringMode === "ai" && !isMezclaTab ? "flex" : "hidden"
                  } flex-1 min-h-0 items-center justify-center overflow-y-auto px-4 py-5 md:px-6 md:py-8`}
                  aria-hidden={masteringMode !== "ai" || isMezclaTab}
                >
                  <motion.div
                    className="flex h-full max-h-[min(42rem,100%)] min-h-[28rem] w-full max-w-2xl flex-col"
                    initial={VIEW_TRANSITION.initial}
                    animate={VIEW_TRANSITION.animate}
                    transition={VIEW_TRANSITION.transition}
                  >
                    <div
                      className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-3xl border shadow-2xl backdrop-blur-2xl"
                      style={{
                        background: "var(--bg-glass-elevated)",
                        borderColor: "var(--border-strong)",
                        boxShadow: "var(--shadow-card)",
                      }}
                    >
                      <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-6 py-4">
                        <div className="flex items-center gap-2">
                          <span className="size-2 rounded-full bg-[var(--accent-primary)] animate-pulse" />
                          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                            {t("nav.chat", "Asistente IA")}
                          </h2>
                        </div>
                        <button
                          type="button"
                          onClick={() => setMasteringMode("manual")}
                          className="flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                        >
                          <ChevronLeft size={13} />
                          <span>{t("common.backToMainFlow", "Volver al flujo principal")}</span>
                        </button>
                      </div>

                      <div className="flex-1 min-h-0 p-4 flex items-center justify-center">
                        <ComingSoonNotice
                          title={t("nav.chat", "Asistente IA")}
                          message={t(
                            "mastering.aiComingSoon",
                            "El asistente con recomendaciones inteligentes llega pronto. Mientras tanto, masteriza en modo Manual con las guías de género."
                          )}
                        />
                      </div>
                    </div>
                  </motion.div>
                </div>

                {/* Manual Mode Workspace */}
                <div
                  className={`${
                    masteringMode === "manual" || isMezclaTab ? "flex" : "hidden"
                  } flex-1 min-h-0 relative`}
                  aria-hidden={masteringMode !== "manual" && !isMezclaTab}
                >
                  {isMobile ? (
                    <MobileMasteringView
                      session={workflow.session}
                      currentTab={currentTab}
                      sheetTab={sheetTab}
                      setCurrentTab={setCurrentTab}
                      activePresetId={workflow.activePresetId}
                      processing={workflow.processing}
                      masterBurst={workflow.masterBurst}
                      error={workflow.error}
                      onPresetSelect={workflow.handlePresetSelect}
                      onProcess={workflow.handleProcess}
                      onDownload={workflow.handleDownload}
                      mixGate={mixGate}
                      renderTabContent={(tab) => (
                        <MasteringCanvas
                          tab={tab}
                          session={workflow.session}
                          params={workflow.params}
                          setParams={workflow.setParams}
                          activePresetId={workflow.activePresetId}
                          onPresetSelect={workflow.handlePresetSelect}
                          onProcess={workflow.handleProcess}
                          onReset={workflow.handleReset}
                          processing={workflow.processing}
                          stemState={workflow.stemState}
                          setStemState={workflow.setStemState}
                          onStemSplit={workflow.handleStemSplit}
                          onVocalProcess={workflow.handleVocalProcess}
                          vocalProcessing={workflow.vocalProcessing}
                          vocalProcessed={workflow.vocalProcessed}
                          masteringMode={masteringMode}
                          onNavigateTab={handleModuleClick}
                          onMixSettled={workflow.handleMixSettled}
                          mixGate={mixGate}
                        />
                      )}
                    />
                  ) : (
                    <motion.div
                      className="flex-1 flex flex-col min-h-0 relative"
                      initial={VIEW_TRANSITION.initial}
                      animate={VIEW_TRANSITION.animate}
                      transition={VIEW_TRANSITION.transition}
                    >
                      {/* Desktop Player */}
                      {!isMezclaTab && (
                        <motion.div
                          layout="position"
                          transition={{ type: "spring", stiffness: 40, damping: 12 }}
                          className={`relative z-[1] px-4 lg:px-6 pt-4 pb-2 ${
                            currentTab === null
                              ? "flex-1 flex items-center justify-center min-h-0"
                              : "shrink-0"
                          }`}
                        >
                          {workflow.session && (
                            <div
                              ref={playerScaleRef}
                              className={`w-full origin-center ${
                                currentTab === null ? "max-w-5xl" : ""
                              }`}
                            >
                              <Player
                                originalUrl={getAudioUrl(workflow.session.session_id, "original")}
                                masteredUrl={
                                  isPresetCompleted(workflow.session, workflow.activePresetId)
                                    ? getAudioUrl(
                                        workflow.session.session_id,
                                        "mastered",
                                        workflow.activePresetId ?? undefined,
                                      )
                                    : null
                                }
                                disabled={workflow.processing}
                                presetId={workflow.activePresetId ?? undefined}
                                sessionId={workflow.session.session_id}
                                burstSignal={workflow.masterBurst}
                              />
                            </div>
                          )}
                        </motion.div>
                      )}

                      {/* Vocal Result Banner */}
                      {workflow.vocalProcessed && workflow.session && (
                        <div className="shrink-0 px-4 lg:px-6 py-2">
                          <div
                            className="flex items-center gap-3 rounded-xl px-4 py-2"
                            style={{
                              background: "rgba(94, 92, 230, 0.06)",
                              border: "1px solid rgba(94, 92, 230, 0.12)",
                            }}
                          >
                            <div className="w-1.5 h-1.5 rounded-full bg-[#5e5ce6] shadow-lg shadow-[rgba(94,92,230,0.3)]" />
                            <span className="text-xs text-[var(--text-secondary)]">
                              Voz procesada —{" "}
                              <a
                                href={`${API_BASE}/session/${workflow.session.session_id}/vocal/audio`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[#5e5ce6] hover:underline"
                              >
                                escuchar resultado vocal
                              </a>
                            </span>
                            <button
                              onClick={() => {
                                if (!workflow.session) return;
                                const a = document.createElement("a");
                                a.href = `${API_BASE}/session/${workflow.session.session_id}/vocal/audio`;
                                a.download = `${workflow.session.session_id}_vocal.wav`;
                                a.click();
                              }}
                              className="ml-auto text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                            >
                              {t("common.download", "Descargar")} WAV
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Scrollable Tab Canvas */}
                      <div
                        className={`relative z-[1] overflow-y-auto px-4 lg:px-6 pt-4 pb-40 ${
                          sheetTab !== null || currentTab === null ? "hidden" : "flex-1"
                        }`}
                      >
                        {workflow.error && (
                          <motion.div className="mb-4" {...fadeUp(0)}>
                            <div
                              className="p-4 rounded-2xl text-xs sm:text-sm flex items-center justify-between gap-3 shadow-lg"
                              style={{
                                background: "rgba(220, 38, 38, 0.12)",
                                border: "1px solid rgba(220, 38, 38, 0.28)",
                                color: "var(--accent-error)",
                              }}
                            >
                              <div className="flex items-center gap-2.5">
                                <AlertCircle size={17} className="shrink-0 text-red-400" />
                                <span>{workflow.error}</span>
                              </div>
                              <button
                                type="button"
                                onClick={() => workflow.setError(null)}
                                className="p-1 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-colors cursor-pointer"
                                aria-label={t("common.close", "Cerrar")}
                              >
                                <X size={15} />
                              </button>
                            </div>
                          </motion.div>
                        )}

                        <AnimatePresence mode="wait">
                          {currentTab !== null && (
                            <PaintedModule key={currentTab}>
                              <MasteringCanvas
                                tab={currentTab}
                                session={workflow.session}
                                params={workflow.params}
                                setParams={workflow.setParams}
                                activePresetId={workflow.activePresetId}
                                onPresetSelect={workflow.handlePresetSelect}
                                onProcess={workflow.handleProcess}
                                onReset={workflow.handleReset}
                                processing={workflow.processing}
                                stemState={workflow.stemState}
                                setStemState={workflow.setStemState}
                                onStemSplit={workflow.handleStemSplit}
                                onVocalProcess={workflow.handleVocalProcess}
                                vocalProcessing={workflow.vocalProcessing}
                                vocalProcessed={workflow.vocalProcessed}
                                masteringMode={masteringMode}
                                onNavigateTab={handleModuleClick}
                                onMixSettled={workflow.handleMixSettled}
                                mixGate={mixGate}
                              />
                            </PaintedModule>
                          )}
                        </AnimatePresence>
                      </div>

                      {/* Floating Bottom ModuleDock */}
                      {sheetTab === null && (
                        <ModuleDock
                          activeTab={currentTab}
                          onSelect={handleModuleClick}
                          processingProgress={workflow.processing ? workflow.progress : 0}
                          lufs={
                            workflow.session?.master_result?.integrated_lufs ??
                            workflow.session?.analysis?.integrated_lufs ??
                            null
                          }
                        />
                      )}
                    </motion.div>
                  )}
                </div>
              </div>
            </div>
          </main>

          {/* Analysis Sidebar Column */}
          {masteringMode === "manual" && !isMobile && (
            <AnalysisSidebar
              open={rightPanelOpen}
              onClose={() => setRightPanelOpen(false)}
              currentTab={currentTab}
              onSelectTab={handleModuleClick}
              session={workflow.session}
              params={workflow.params}
              activePresetId={workflow.activePresetId}
              onDownload={workflow.handleDownload}
              onFileSelected={workflow.handleFileSelected}
              onError={(title, message) => workflow.setErrorModal({ title, message })}
              loading={workflow.loading}
            />
          )}
        </div>

        {/* Floating Module Sheet Panel */}
        {sheetTab !== null && (
          <ModuleSheet
            open={sheetTab !== null}
            onClose={() => setSheetTab(null)}
            title={TABS.find((t) => t.key === sheetTab)?.label ?? "Módulo"}
            subtitle={
              sheetTab === "splitter"
                ? "Separar en stems"
                : sheetTab === "vocal"
                  ? "Cadena vocal pro"
                  : sheetTab === "songstarter"
                    ? "Generador de ideas"
                    : sheetTab === "genres"
                      ? "Guía de géneros"
                      : sheetTab === "mezcla"
                        ? "Mezclar stems en un bus"
                        : undefined
            }
          >
            <MasteringCanvas
              tab={sheetTab}
              session={workflow.session}
              params={workflow.params}
              setParams={workflow.setParams}
              activePresetId={workflow.activePresetId}
              onPresetSelect={workflow.handlePresetSelect}
              onProcess={workflow.handleProcess}
              onReset={workflow.handleReset}
              processing={workflow.processing}
              stemState={workflow.stemState}
              setStemState={workflow.setStemState}
              onStemSplit={workflow.handleStemSplit}
              onVocalProcess={workflow.handleVocalProcess}
              vocalProcessing={workflow.vocalProcessing}
              vocalProcessed={workflow.vocalProcessed}
              masteringMode={masteringMode}
              onNavigateTab={handleModuleClick}
              onMixSettled={workflow.handleMixSettled}
              mixGate={mixGate}
            />
          </ModuleSheet>
        )}

        {/* User Songs Library / History Modal */}
        <LibraryView
          isOpen={libraryOpen}
          onClose={() => setLibraryOpen(false)}
          currentTrackId={workflow.currentTrack?.id}
          onSelectTrack={(track) => {
            setLibraryOpen(false);
            window.open(`/mezclas?track=${track.id}`, "_blank");
          }}
          onTracksCountChange={(count) => setHasSavedTracks(count > 0 || Boolean(workflow.currentTrack))}
          onNewUpload={handleHomeClick}
        />

        {/* Consolidate Final Master Modal */}
        <ConsolidateMasterModal
          isOpen={consolidateModalOpen}
          onClose={() => setConsolidateModalOpen(false)}
          track={workflow.currentTrack}
          params={workflow.params}
          activePresetId={workflow.activePresetId}
          isConsolidating={workflow.isConsolidating}
          onConfirm={workflow.handleConsolidateMaster}
        />

        {/* Workflow Mode Explanation & Selector Modal */}
        <SelectWorkflowModal
          isOpen={workflowModalOpen}
          trackTitle={workflow.currentTrack?.title}
          onConfirm={(mode) => {
            setMasteringMode(mode);
            setWorkflowModalOpen(false);
          }}
          onClose={() => setWorkflowModalOpen(false)}
          canDismiss={true}
        />
      </main>
    </LicenseGuard>
  );
}

export default function MezclasPage() {
  return (
    <Suspense fallback={<div className="h-screen bg-[var(--bg-app)] animate-pulse" />}>
      <MezclasContent />
    </Suspense>
  );
}
