"use client";

import { RotateCcw } from "lucide-react";
import ModulePanel from "@/presentation/components/ModulePanel";
import GenreGuide from "@/presentation/components/GenreGuide";
import StemSplitter, { type StemSplitterState } from "@/presentation/components/StemSplitter";
import MixPanel from "@/presentation/components/MixPanel";
import MixGateNotice, {
  type MixGateState,
} from "@/presentation/components/MixGateNotice";
import VocalChain from "@/presentation/components/VocalChain";
import SongStarter from "@/presentation/components/SongStarter";
import AlbumMastering from "@/presentation/components/AlbumMastering";
import MasteringGuide from "@/presentation/components/MasteringGuide";
import type { MasteringTab } from "@/presentation/components/dock/types";
import type { MasteringParameters, SessionData, VocalChainParams, StemSplitResult } from "@/lib/api";
import { hasCompletedMix } from "@/lib/audioUtils";
import { useTranslation } from "@/i18n/useTranslation";

interface MasteringCanvasProps {
  tab: MasteringTab;
  session: SessionData | null;
  params: MasteringParameters;
  setParams: (p: MasteringParameters) => void;
  processing: boolean;
  activePresetId: string | null;
  onPresetSelect: (p: MasteringParameters, id?: string) => Promise<void>;
  onProcess: () => Promise<void>;
  onReset: () => Promise<void>;
  stemState: StemSplitterState;
  setStemState: React.Dispatch<React.SetStateAction<StemSplitterState>>;
  onStemSplit: () => Promise<StemSplitResult>;
  vocalProcessing: boolean;
  vocalProcessed: boolean;
  onVocalProcess: (p: VocalChainParams) => Promise<void>;
  masteringMode: "manual" | "ai";
  onNavigateTab: (tab: MasteringTab) => void;
  /** El mix terminó (éxito o fallo): el padre relee la sesión para
   *  sincronizar `session.mix_status` (T2) → `hasMix`. */
  onMixSettled?: () => void;
  /** Gate de mezcla (T4): solo se renderiza en el tab de master y solo
   *  bloquea cuando hay una mezcla iniciada sin audio entregado. */
  mixGate?: MixGateState;
}

export default function MasteringCanvas({
  tab,
  session,
  params,
  setParams,
  processing,
  activePresetId,
  onPresetSelect,
  onProcess,
  onReset,
  stemState,
  setStemState,
  onStemSplit,
  vocalProcessing,
  vocalProcessed,
  onVocalProcess,
  masteringMode,
  onNavigateTab,
  onMixSettled,
  mixGate,
}: MasteringCanvasProps) {
  const { t } = useTranslation();

  switch (tab) {
    case "modules":
      if (!session) {
        return (
          <p className="text-[var(--text-muted)] text-sm">
            {t("mastering.loadAudioPrompt", "Carga un audio para empezar.")}
          </p>
        );
      }
      return (
        <div className="w-full">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2
                className="text-lg font-semibold text-[var(--text-primary)]"
                style={{ letterSpacing: "-0.02em" }}
              >
                {t("nav.modules", "Masterizar Audio")}{" "}
                <span className="serif-accent">{t("common.pro", "Pro")}</span>
              </h2>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                {t("mastering.selectOrTweak", "Selecciona un perfil o ajusta fino abajo")}
              </p>
            </div>
            <button
              onClick={onReset}
              disabled={processing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)]
                disabled:opacity-30 disabled:cursor-not-allowed
                transition-all duration-200"
            >
              <RotateCcw size={13} />
              {t("common.reset", "Restablecer")}
            </button>
          </div>

          <ModulePanel
            params={params}
            onChange={setParams}
            disabled={processing}
            activePresetId={activePresetId}
            onPresetSelect={onPresetSelect}
          />

          {/* Gate de mezcla (T4): el botón queda habilitado a propósito —
              apretarlo muestra el aviso y lleva al tab de mezcla, en vez de
              masterizar en silencio o dejar el usuario sin explicación. */}
          <MixGateNotice gate={mixGate} className="mt-4" />

          <button
            onClick={onProcess}
            disabled={processing}
            className="w-full mt-4 py-3 rounded-2xl text-sm font-semibold
              transition-all duration-300 ease-out
              disabled:opacity-40 disabled:cursor-not-allowed
              hover:brightness-110"
            style={{
              background: processing
                ? "rgba(98, 126, 132, 0.06)"
                : "linear-gradient(135deg, rgba(98,126,132,0.15), rgba(98,126,132,0.06))",
              border: "1px solid rgba(98,126,132,0.2)",
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
              t("mastering.processButton", "Procesar con estos parámetros")
            )}
          </button>
        </div>
      );

    case "genres":
      return (
        <div className="w-full">
          <GenreGuide />
        </div>
      );

    case "splitter":
      if (!session) {
        return (
          <p className="text-[var(--text-muted)] text-sm">
            {t("splitter.loadAudioPrompt", "Carga un audio para usar el Splitter.")}
          </p>
        );
      }
      return (
        <div className="w-full">
          <StemSplitter
            state={stemState}
            onChange={setStemState}
            onSplit={onStemSplit}
            sessionId={session.session_id}
            disabled={processing}
          />
        </div>
      );

    case "mezcla":
      if (!session) {
        return (
          <p className="text-[var(--text-muted)] text-sm">
            {t("mezcla.loadAudioPrompt", "Carga un audio para usar la Mezcla de Audio.")}
          </p>
        );
      }
      return (
        <div className="w-full">
          <MixPanel
            sessionId={session.session_id}
            sessionMixPath={session.mix_path ?? null}
            sessionMixAnalysis={session.mix_analysis ?? null}
            audioDurationSeconds={session.analysis?.duration_seconds ?? null}
            genreHint={session.analysis?.detected_genre ?? null}
            disabled={processing}
            mode={masteringMode}
            /* Estado de mezcla del backend, no un flag local (T2/T3). */
            hasMix={hasCompletedMix(session)}
            onMixSettled={onMixSettled}
            onMasterize={() => onNavigateTab("modules")}
          />
        </div>
      );

    case "vocal":
      if (!session) {
        return (
          <p className="text-[var(--text-muted)] text-sm">
            {t("vocal.loadAudioPrompt", "Carga un audio para usar VoiceChain Pro.")}
          </p>
        );
      }
      return (
        <div className="w-full">
          <VocalChain
            sessionId={session.session_id}
            disabled={processing}
            processing={vocalProcessing}
            processed={vocalProcessed}
            onProcess={onVocalProcess}
          />
        </div>
      );

    case "songstarter":
      return (
        <div className="w-full">
          <SongStarter
            sessionId={session?.session_id ?? null}
            disabled={processing}
          />
        </div>
      );

    case "album":
      return (
        <div className="w-full">
          <AlbumMastering />
        </div>
      );

    case "pipeline":
      return (
        <div className="w-full">
          <MasteringGuide />
        </div>
      );

    default:
      return null;
  }
}
