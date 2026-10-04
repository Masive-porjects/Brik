"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import LicenseGuard from "@/components/LicenseGuard";
import { useTranslation } from "@/i18n";
import {
  useMastering,
  MasteringHeader,
  MasteringOverlays,
  SelectWorkflowModal,
} from "@/features/mastering";
import { UploadView } from "@/features/upload";
import { LibraryView, ResumeSessionModal } from "@/features/remastering-history";
import { useAuth } from "@/features/auth";
import { fetchLatestUserTrack, type Track } from "@/features/tracks";
import { useMasteringJob } from "@/features/mastering";

export default function UploadPage() {
  const router = useRouter();
  const { user } = useAuth();
  const { t } = useTranslation();
  const workflow = useMastering();

  // ── Nuevo hook: submeter job asíncrono y hacer polling ──────────────────
  const {
    state,
    jobId,
    result,
    error: jobError,
    progress,
    isComplete,
    isTerminal,
    submit,
    reset,
  } = useMasteringJob({
    payload: {
      track_id: "",
      preset_id: "universal",
      is_async: true, // Fase 6: encolar en background queue
    },
    onComplete: (res) => {
      console.log("✅ Mastering job completado:", res);
    },
    onError: (err) => {
      console.error("❌ Mastering job falló:", err);
    },
  });

  const [libraryOpen, setLibraryOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [latestTrack, setLatestTrack] = useState<Track | null>(null);
  const [hasSavedTracks, setHasSavedTracks] = useState(false);
  const [resumeModalOpen, setResumeModalOpen] = useState(false);
  const [workflowModalOpen, setWorkflowModalOpen] = useState(false);
  const [isNavigatingToStudio, setIsNavigatingToStudio] = useState(false);
  const [pendingTrackTitle, setPendingTrackTitle] = useState<string>("");
  const hasCheckedLatestRef = useRef(false);

  // Signed out: drop the returning-user state in the same commit instead of
  // resetting it from an effect one render later.
  if (!user) {
    if (latestTrack !== null) setLatestTrack(null);
    if (hasSavedTracks) setHasSavedTracks(false);
    if (resumeModalOpen) setResumeModalOpen(false);
  }

  // Check for returning user's latest project without forcing blindly into mastering
  useEffect(() => {
    if (!user) return;
    if (hasCheckedLatestRef.current) return;
    hasCheckedLatestRef.current = true;

    fetchLatestUserTrack(user.id).then((track) => {
      if (track) {
        setLatestTrack(track);
        setHasSavedTracks(true);
        if (!workflow.session) {
          setResumeModalOpen(true);
        }
      } else {
        setLatestTrack(null);
        setHasSavedTracks(false);
        setResumeModalOpen(false);
      }
    });
  }, [user, workflow.session]);

  const handleFileSelected = async (file: File) => {
    setPendingTrackTitle(file.name.replace(/\.[^/.]+$/, ""));
    await workflow.handleFileSelected(file);
    // After audio upload and spectral analysis completes, show the mode choice modal
    setWorkflowModalOpen(true);
    // Auto-submit the async job after workflow is confirmed (para testing E2E)
    // We wait a tick for the modal state to settle, then submit
    setTimeout(() => {
      submit();
    }, 500);
  };

  const handleConfirmWorkflow = (mode: "manual" | "ai") => {
    setIsNavigatingToStudio(true);
    router.push(`/mezclas?mode=${mode}`);
  };

  const handleResumeProject = async (track: Track) => {
    setResumeModalOpen(false);
    window.open(`/mezclas?track=${track.id}`, "_blank");
  };

  const handleSelectTrackFromLibrary = async (track: Track) => {
    setLibraryOpen(false);
    window.open(`/mezclas?track=${track.id}`, "_blank");
  };

  // Render job status UI when we have a terminal result
  const jobStatusUI = isComplete && result ? (
    <div className="mt-4 p-3 rounded-xl"
         style={{
           background: "var(--bg-glass)",
           border: "1px solid var(--border-subtle)",
         }}>
      <p className="text-sm font-medium text-[var(--text-primary)]">
        {isTerminal ? "Job completado" : "Job en proceso"}
      </p>
      {jobId && <p className="text-xs text-[var(--text-muted)] mt-1">Job ID: {jobId}</p>}
      {progress >= 0 && <p className="text-xs text-[var(--text-muted)] mt-1">Progreso: {progress}%</p>}
      {result.download_url && (
        <a
          href={result.download_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-[var(--accent-primary)] underline"
        >
          ↓ Descargar master WAV
        </a>
      )}
      {jobError && <p className="mt-2 text-sm text-[var(--accent-error)]">{jobError}</p>}
    </div>
  ) : null;

  return (
    <LicenseGuard>
      <main className="h-screen flex flex-col bg-[var(--bg-app)] text-[var(--text-primary)] overflow-hidden font-sans relative selection:bg-[var(--accent-primary)] selection:text-white">
        {/* Global Overlays & Modals */}
        <MasteringOverlays
          currentView="upload"
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
          currentView="upload"
          session={workflow.session}
          processing={workflow.processing}
          loading={workflow.loading}
          masteringMode="manual"
          setMasteringMode={() => {}}
          onBackToUpload={() => {}}
          mobileMenuOpen={mobileMenuOpen}
          setMobileMenuOpen={setMobileMenuOpen}
          autosaveStatus={workflow.autosaveStatus}
          hasSavedTracks={hasSavedTracks}
        />

        {/* Upload Workspace */}
        <div className="flex-1 flex min-h-0 items-center justify-center p-4">
          <UploadView
            loading={workflow.loading}
            uploadBurst={workflow.uploadBurst}
            onError={(title, message) => workflow.setErrorModal({ title, message })}
            onFileSelected={handleFileSelected}
          />
        </div>

        {/* Job Status UI (async job queue E2E testing) */}
        {jobStatusUI}

        {/* User Songs Library / History Modal */}
        <LibraryView
          isOpen={libraryOpen}
          onClose={() => setLibraryOpen(false)}
          currentTrackId={workflow.currentTrack?.id}
          onSelectTrack={handleSelectTrackFromLibrary}
          onNewUpload={() => {
            setLibraryOpen(false);
            setResumeModalOpen(false);
          }}
          onTracksCountChange={(count) => setHasSavedTracks(count > 0)}
        />

        {/* Prompt to Resume Latest Project for Returning Users */}
        <ResumeSessionModal
          isOpen={resumeModalOpen}
          track={latestTrack}
          isLoading={workflow.isLoadingTrackProject}
          onContinue={handleResumeProject}
          onNewTrack={() => {
            setResumeModalOpen(false);
          }}
          onOpenLibrary={() => {
            setResumeModalOpen(false);
            setLibraryOpen(true);
          }}
        />

        {/* Modal to choose workflow mode (Manual vs AI Assistant) upon new upload */}
        <SelectWorkflowModal
          isOpen={workflowModalOpen}
          trackTitle={pendingTrackTitle}
          onConfirm={handleConfirmWorkflow}
          isLoading={isNavigatingToStudio}
          canDismiss={false}
        />
      </main>
    </LicenseGuard>
  );
}