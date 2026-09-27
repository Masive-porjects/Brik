"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Menu,
  X,
  Home as HomeIcon,
  SlidersHorizontal,
  Sparkles,
  Music2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Disc3,
  Pencil,
  Check,
} from "lucide-react";
import TrackChip from "@/presentation/components/TrackChip";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import { UserMenu } from "@/features/auth";
import { useTranslation } from "@/i18n/useTranslation";
import type { SessionData } from "@/lib/api";
import type { AutosaveStatus } from "../hooks/useAutosaveDraft";

interface MasteringHeaderProps {
  currentView: "upload" | "mastering";
  session: SessionData | null;
  processing: boolean;
  loading: boolean;
  masteringMode: "manual" | "ai";
  setMasteringMode: (mode: "manual" | "ai") => void;
  onBackToUpload: () => void;
  mobileMenuOpen: boolean;
  setMobileMenuOpen: (open: boolean) => void;
  onClearSheet?: () => void;
  autosaveStatus?: AutosaveStatus;
  onOpenLibrary?: () => void;
  onConsolidate?: () => void;
  draftName?: string | null;
  onRenameDraft?: (newName: string) => void;
  hasSavedTracks?: boolean;
  onOpenWorkflowModal?: () => void;
}

export default function MasteringHeader({
  currentView,
  session,
  processing,
  loading,
  masteringMode,
  setMasteringMode,
  onBackToUpload,
  mobileMenuOpen,
  setMobileMenuOpen,
  onClearSheet,
  autosaveStatus,
  onOpenLibrary,
  onConsolidate,
  draftName,
  onRenameDraft,
  hasSavedTracks = false,
  onOpenWorkflowModal,
}: MasteringHeaderProps) {
  const { t } = useTranslation();
  const [isEditingDraftName, setIsEditingDraftName] = useState(false);
  const [tempDraftName, setTempDraftName] = useState("");

  const handleSaveDraftName = () => {
    if (tempDraftName.trim() && tempDraftName.trim() !== draftName) {
      onRenameDraft?.(tempDraftName.trim());
    }
    setIsEditingDraftName(false);
  };

  return (
    <nav className="relative z-50 flex items-center justify-between px-4 lg:px-6 pt-safe py-3 shrink-0">
      <div className="flex items-center gap-2.5 flex-wrap">
        <div className="rounded-full px-4 py-2 glass">
          <span className="text-base font-semibold tracking-tight text-[var(--text-primary)]">
            Wave<span className="text-[var(--accent-primary)]">IA</span>
          </span>
        </div>

        {currentView !== "upload" && session && (
          <TrackChip
            originalPath={session.original_path}
            genre={session.analysis?.detected_genre}
            disabled={processing || loading}
            onChangeTrack={onBackToUpload}
          />
        )}

        {/* Editable Draft Version Chip */}
        {currentView === "mastering" && session && (
          <div className="hidden sm:flex items-center gap-1 px-3 py-1 rounded-full text-xs border border-[var(--border-subtle)] bg-[var(--surface-elevated)] backdrop-blur-md">
            <span className="text-[var(--text-muted)] text-[10px] uppercase font-bold tracking-wider mr-1">
              Borrador:
            </span>
            {isEditingDraftName ? (
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={tempDraftName}
                  onChange={(e) => setTempDraftName(e.target.value)}
                  onBlur={handleSaveDraftName}
                  onKeyDown={(e) => e.key === "Enter" && handleSaveDraftName()}
                  autoFocus
                  className="bg-transparent border-b border-[var(--accent-primary)] text-xs text-[var(--text-primary)] focus:outline-none px-1 w-28"
                />
                <button
                  type="button"
                  onClick={handleSaveDraftName}
                  className="p-0.5 text-emerald-400 hover:text-white"
                >
                  <Check size={11} />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setTempDraftName(draftName || "Mezcla Principal");
                  setIsEditingDraftName(true);
                }}
                title="Clic para renombrar este borrador"
                className="flex items-center gap-1.5 text-[var(--text-primary)] font-semibold hover:text-[var(--accent-primary)] transition-colors cursor-pointer"
              >
                <span className="truncate max-w-[130px]">
                  {draftName || "Mezcla Principal"}
                </span>
                <Pencil size={11} className="text-[var(--text-muted)]" />
              </button>
            )}
          </div>
        )}

        {/* Real-time Draft Autosave Indicator */}
        {currentView === "mastering" && autosaveStatus && autosaveStatus !== "idle" && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium backdrop-blur-md transition-all select-none"
            style={{
              backgroundColor:
                autosaveStatus === "saved"
                  ? "rgba(16, 185, 129, 0.1)"
                  : autosaveStatus === "saving"
                    ? "rgba(98, 126, 132, 0.12)"
                    : "rgba(245, 158, 11, 0.12)",
              borderColor:
                autosaveStatus === "saved"
                  ? "rgba(16, 185, 129, 0.25)"
                  : autosaveStatus === "saving"
                    ? "rgba(98, 126, 132, 0.25)"
                    : "rgba(245, 158, 11, 0.25)",
              borderWidth: 1,
            }}
          >
            {autosaveStatus === "saving" ? (
              <>
                <Loader2 size={11} className="animate-spin text-[var(--accent-primary)]" />
                <span className="text-[var(--text-secondary)]">
                  {t("mastering.savingDraft", "Guardando borrador...")}
                </span>
              </>
            ) : autosaveStatus === "saved" ? (
              <>
                <CheckCircle2 size={11} className="text-emerald-400" />
                <span className="text-emerald-400 font-medium">
                  {t("mastering.draftSaved", "Borrador en nube")}
                </span>
              </>
            ) : (
              <>
                <AlertCircle size={11} className="text-amber-400" />
                <span className="text-amber-400">
                  {t("mastering.draftError", "Error al guardar")}
                </span>
              </>
            )}
          </motion.div>
        )}
        {/* Workflow Mode Badge */}
        {currentView === "mastering" && onOpenWorkflowModal && (
          <button
            type="button"
            onClick={onOpenWorkflowModal}
            title={t("workflow.modeTooltip", "Clic para ver detalles del flujo actual")}
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:border-[var(--accent-primary)] hover:bg-[var(--surface-hover)] text-[var(--text-primary)] transition-all cursor-pointer select-none"
          >
            <SlidersHorizontal size={12} className="text-[var(--accent-primary)]" />
            <span className="font-semibold text-[11px]">{t("workflow.manualModeLabel", "Modo Manual")}</span>
            <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-[var(--accent-primary)]/10 text-[var(--accent-primary)] font-bold">
              {t("workflow.fullControlShort", "Control Total")}
            </span>
          </button>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {currentView === "mastering" && onConsolidate && (
          <button
            type="button"
            onClick={onConsolidate}
            disabled={processing || loading}
            title={t("mastering.defineFinalMix", "Definir Mezcla Final")}
            aria-label={t("mastering.defineFinalMix", "Definir Mezcla Final")}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-bold bg-gradient-to-r from-emerald-500/20 to-teal-500/20 border border-emerald-500/40 hover:border-emerald-400 text-emerald-300 hover:text-white transition-all shadow-sm shadow-emerald-500/10 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Disc3 size={14} className="text-emerald-400" />
            <span className="hidden sm:inline">{t("mastering.defineFinalMix", "Definir Mezcla Final")}</span>
          </button>
        )}

        {onOpenLibrary && hasSavedTracks && (
          <button
            type="button"
            onClick={onOpenLibrary}
            title={t("nav.myTracks", "Mis Canciones")}
            aria-label={t("nav.myTracks", "Mis Canciones")}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] hover:border-[var(--accent-primary)] text-[var(--text-primary)] transition-all shadow-xs cursor-pointer"
          >
            <Music2 size={14} className="text-[var(--accent-primary)]" />
            <span className="hidden sm:inline">{t("nav.myTracks", "Mis Canciones")}</span>
          </button>
        )}

        <ThemeToggle />
        <LanguageSwitcher />
        <UserMenu onOpenLibrary={hasSavedTracks ? onOpenLibrary : undefined} />

        {currentView === "mastering" && (
          <button
            onClick={onBackToUpload}
            title={t("nav.home", "Inicio")}
            aria-label={t("nav.home", "Inicio")}
            className="hidden rounded-full w-9 h-9 md:flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-all"
          >
            <HomeIcon size={18} />
          </button>
        )}

        <button
          className="lg:hidden rounded-full w-9 h-9 flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-all"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          <span
            className="transition-transform duration-300 inline-flex"
            style={{ transform: mobileMenuOpen ? "rotate(180deg)" : "rotate(0deg)" }}
          >
            {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
          </span>
        </button>
      </div>
    </nav>
  );
}
