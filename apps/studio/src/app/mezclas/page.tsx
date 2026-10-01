"use client";

import { useState, useCallback, useEffect, useMemo, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import gsap from "gsap";
import { motion, AnimatePresence } from "framer-motion";
import { VIEW_TRANSITION, fadeUp } from "@/shared/motion";
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
import { ChevronLeft, AlertCircle, Loader2, X } from "lucide-react";
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
  { key: "songstarter", label: "Beats" },
  { key: "analysis", label: "Análisis" },
  { key: "stereo", label: "Estéreo" },
  { key: "album", label: "Álbum" },
];

type MasteringMode = "manual" | "ai";

function parseModeParam(value: string | null): MasteringMode | null {
  return value === "manual" || value === "ai" ? value : null;
}

function MezclasContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const trackIdParam = searchParams.get("track");
  const modeParam = searchParams.get("mode");
  const isMobile = useIsMobile();
  const { t } = useTranslation();
  const { user } = useAuth();

  const workflow = useMastering();

  const urlMode = parseModeParam(modeParam);
  const [masteringMode, setMasteringMode] = useState<MasteringMode>(() => urlMode ?? "manual");
  const [currentTab, setCurrentTab] = useState<MasteringTab | null>(null);
  const [sheetTab, setSheetTab] = useState<MasteringTab | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [consolidateModalOpen, setConsolidateModalOpen] = useState(false);
  const [workflowModalOpen, setWorkflowModalOpen] = useState(false);
  const [hasSavedTracks, setHasSavedTracks] = useState(true);

  /* `?mode=` only seeds the mode for the visit that /upload redirects into. Remember
     which param value has already been applied so an explicit user choice (workflow
     modal or "back to main flow") is never reverted by a later render. Adjusting state
     during render is React's sanctioned "derive from props" pattern: React re-renders
     immediately without committing, so the DOM output is unchanged. */
  const [appliedModeParam, setAppliedModeParam] = useState<string | null>(null);
  if (modeParam !== appliedModeParam) {
    setAppliedModeParam(modeParam);
    if (urlMode !== null) {
      setMasteringMode(urlMode);
    }
  }

  useEffect(() => {
    if (user?.id) {
      getUserTracksCount(user.id).then((count) => {
        setHasSavedTracks(count > 0 || Boolean(workflow.currentTrack));
      });
    }
  }, [user?.id, workflow.currentTrack]);

  /* Si un `?track=` viene en la URL y no está cargado, se busca en TODAS las páginas
     del usuario: antes sólo miraba las primeras 50 y un track más viejo quedaba
     en silencio (pantalla en blanco, sin error ni salida). Ahora además el estado
     es explícito para que la UI pueda explicar qué pasó.

     `idle` y `ready` se DERIVAN en vez de almacenarse: un setState síncrono dentro
     del efecto dispara renders en cascada (react-hooks/set-state-in-effect). El
     único estado guardado es el resultado asíncrono del fallback de búsqueda. */
  const [trackLookupOutcome, setTrackLookupOutcome] = useState<"missing" | "error" | null>(null);
  const loadedTrackRef = useRef<string | null>(null);

  const trackIsLoaded = Boolean(
    trackIdParam && workflow.currentTrack?.id === trackIdParam && workflow.session,
  );
  const trackLookup = !user || !trackIdParam
    ? "idle"
    : trackIsLoaded
      ? "ready"
      : (trackLookupOutcome ?? "loading");

  useEffect(() => {
    if (!user || !trackIdParam || trackIsLoaded) return;
    if (loadedTrackRef.current === trackIdParam) return;
    loadedTrackRef.current = trackIdParam;

    let cancelled = false;
    (async () => {
      try {
        const pageSize = 50;
        for (let page = 1; page <= 200; page++) {
          const res = await fetchUserTracks(user.id, { page, pageSize });
          if (cancelled) return;
          const found = res.items.find((tr) => tr.id === trackIdParam);
          if (found) {
            workflow.handleLoadTrackProject(found);
            return;
          }
          if (page >= res.totalPages) break;
        }
        if (!cancelled) setTrackLookupOutcome("missing");
      } catch (err) {
        console.error("Error loading track from URL param:", err);
        if (!cancelled) setTrackLookupOutcome("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, trackIdParam, trackIsLoaded, workflow]);

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
        {/* Estado explícito de resolución del `?track=`. Antes, si el track no
            aparecía en la primera página, no se renderizaba nada: pantalla en
            blanco que el usuario leía como un 404. */}
        {trackLookup !== "idle" && trackLookup !== "ready" && !workflow.session && (
          <div className="absolute inset-0 z-50 flex items-center justify-center p-6 bg-[var(--bg-app)]">
            <div className="w-full max-w-sm rounded-3xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] p-7 text-center">
              {trackLookup === "loading" ? (
                <>
                  <Loader2 size={22} className="mx-auto animate-spin text-[var(--accent-primary)]" aria-hidden="true" />
                  <p className="mt-4 text-sm text-[var(--text-secondary)]">
                    {t("mezclas.trackLoading")}
                  </p>
                </>
              ) : (
                <>
                  <AlertCircle size={22} className="mx-auto text-[var(--accent-error)]" aria-hidden="true" />
                  <h2 className="mt-4 text-base font-semibold text-[var(--text-primary)]">
                    {trackLookup === "missing"
                      ? t("mezclas.trackMissingTitle")
                      : t("mezclas.trackError")}
                  </h2>
                  {trackLookup === "missing" && (
                    <p className="mt-2 text-sm text-[var(--text-secondary)]">
                      {t("mezclas.trackMissingBody")}
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => router.replace("/upload")}
                    className="mt-6 w-full rounded-xl border border-[var(--accent-primary)] bg-[var(--accent-primary)]/10 px-4 py-2.5 text-sm font-semibold text-[var(--accent-primary)] transition-colors hover:bg-[var(--accent-primary)]/20"
                  >
                    {t("mezclas.trackMissingCta")}
                  </button>
                </>
              )}
            </div>
          </div>
        )}

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

                        {/* Sin `mode="wait"`: ese modo de framer-motion borra el nodo
                            DOM saliente y reinserta el entrante. Con React 19 la
                            referencia queda stale y el commit falla con
                            "NotFoundError: insertBefore" al abrir el tab de mezcla. */}
                        <AnimatePresence>
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
                : sheetTab === "songstarter"
                  ? "Generador de ideas"
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
