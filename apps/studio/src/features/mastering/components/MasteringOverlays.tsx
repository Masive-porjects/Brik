"use client";

import ErrorModal from "@/presentation/components/ErrorModal";
import OverMasterWarning from "@/presentation/components/OverMasterWarning";
import FloatingDeliveryPanel from "@/presentation/components/FloatingDeliveryPanel";
import FloatingReportCard from "@/presentation/components/FloatingReportCard";
import AmbientLayer from "@/presentation/components/AmbientLayer";
import ProcessingOverlay from "@/presentation/components/ProcessingOverlay";
import type { MasteringParameters, SessionData } from "@/lib/api";

interface MasteringOverlaysProps {
  currentView: "upload" | "mastering";
  session: SessionData | null;
  params: MasteringParameters;
  setParams: React.Dispatch<React.SetStateAction<MasteringParameters>>;
  errorModal: { title: string; message: string } | null;
  setErrorModal: (modal: { title: string; message: string } | null) => void;
  overMasterWarning: {
    open: boolean;
    confidence: number;
    analyzedSession: SessionData;
    mappedParams: MasteringParameters;
  } | null;
  onOverMasterConfirm: () => void;
  onOverMasterCancel: () => void;
  loading: boolean;
  uploadProgress: number;
  processing: boolean;
  processingProgress: number;
}

export default function MasteringOverlays({
  currentView,
  session,
  params,
  setParams,
  errorModal,
  setErrorModal,
  overMasterWarning,
  onOverMasterConfirm,
  onOverMasterCancel,
  loading,
  uploadProgress,
  processing,
  processingProgress,
}: MasteringOverlaysProps) {
  return (
    <>
      {/* Overlay de procesamiento global */}
      <ProcessingOverlay
        visible={loading || processing}
        phase={loading ? "upload" : "process"}
        progress={loading ? uploadProgress : processingProgress}
      />

      {/* Modal de error global */}
      <ErrorModal
        open={errorModal !== null}
        onClose={() => setErrorModal(null)}
        title={errorModal?.title ?? "Error"}
        message={errorModal?.message ?? ""}
      />

      {/* Advertencia de sobre-masterización */}
      <OverMasterWarning
        open={overMasterWarning?.open ?? false}
        confidence={overMasterWarning?.confidence ?? 0}
        onConfirm={onOverMasterConfirm}
        onCancel={onOverMasterCancel}
      />

      {/* Overlays flotantes: entrega y reporte en modo mastering */}
      {currentView === "mastering" && (
        <FloatingDeliveryPanel params={params} onChange={setParams} />
      )}
      {currentView === "mastering" && session?.mastering_report && (
        <FloatingReportCard
          report={session.mastering_report}
          mode={session.parameters?.processing_mode ?? "master"}
          platform={session.parameters?.platform_target ?? null}
        />
      )}

      {/* Capa ambiental */}
      <AmbientLayer />
    </>
  );
}
