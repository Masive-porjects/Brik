"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, AlertCircle, RefreshCw, ArrowLeft, X } from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";
import { GoogleIcon, SpotifyIcon, DiscordIcon, GitHubIcon } from "./SocialIcons";

export type SocialProvider = "google" | "spotify" | "discord" | "github";

interface SocialStatusModalProps {
  isOpen: boolean;
  provider: SocialProvider | null;
  status: "connecting" | "error";
  errorMessage?: string | null;
  onClose: () => void;
  onRetry?: () => void;
}

const PROVIDER_NAMES: Record<SocialProvider, string> = {
  google: "Google",
  spotify: "Spotify",
  discord: "Discord",
  github: "GitHub",
};

export default function SocialStatusModal({
  isOpen,
  provider,
  status,
  errorMessage,
  onClose,
  onRetry,
}: SocialStatusModalProps) {
  const { t } = useTranslation();
  const [phraseIndex, setPhraseIndex] = useState(0);

  const waitingPhrases = [
    t("auth.modalPhrase1"),
    t("auth.modalPhrase2"),
    t("auth.modalPhrase3"),
  ];

  // Cycle waiting phrases every 2.4s while connecting
  useEffect(() => {
    if (!isOpen || status !== "connecting") return;
    const timer = setInterval(() => {
      setPhraseIndex((prev) => (prev + 1) % waitingPhrases.length);
    }, 2400);
    return () => clearInterval(timer);
  }, [isOpen, status, waitingPhrases.length]);

  if (!isOpen) return null;

  const providerName = provider ? PROVIDER_NAMES[provider] || provider : "Red Social";

  const renderIcon = () => {
    switch (provider) {
      case "google":
        return <GoogleIcon className="size-8" />;
      case "spotify":
        return <SpotifyIcon className="size-8" />;
      case "discord":
        return <DiscordIcon className="size-8" />;
      case "github":
        return <GitHubIcon className="size-8" />;
      default:
        return null;
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 bg-black/75 backdrop-blur-xl"
        />

        {/* Modal Card */}
        <motion.div
          initial={{ opacity: 0, scale: 0.94, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.94, y: 15 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="relative w-full max-w-[380px] p-6 rounded-3xl border shadow-2xl overflow-hidden z-10 text-center"
          style={{
            background: "var(--bg-glass-elevated)",
            borderColor: "var(--border-strong)",
            boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7), inset 0 1px 0 rgba(255, 255, 255, 0.1)",
          }}
        >
          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            className="absolute top-4 right-4 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1 rounded-full hover:bg-[var(--surface-elevated)] cursor-pointer"
            aria-label="Cerrar modal"
          >
            <X size={16} />
          </button>

          {/* Status content */}
          {status === "connecting" ? (
            <div className="py-2 flex flex-col items-center">
              {/* Animated Provider Icon in glowing halo */}
              <div className="relative mb-4 flex items-center justify-center">
                <div className="absolute inset-0 rounded-2xl bg-[var(--accent-primary)]/20 blur-xl animate-pulse" />
                <div className="relative size-16 rounded-2xl border border-[var(--border-strong)] bg-[var(--surface-elevated)] flex items-center justify-center shadow-lg">
                  {renderIcon()}
                </div>
                <div className="absolute -bottom-1 -right-1 size-6 rounded-full bg-[var(--bg-app)] border border-[var(--border-strong)] flex items-center justify-center">
                  <Loader2 size={13} className="animate-spin text-[var(--accent-primary)]" />
                </div>
              </div>

              <h3 className="text-base font-bold text-[var(--text-primary)] mb-1">
                {t(
                  "auth.modalConnectingTitle",
                  { provider: providerName },
                  "Conectando con {provider}"
                )}
              </h3>

              {/* Dynamic cycling phrases */}
              <div className="h-6 flex items-center justify-center overflow-hidden">
                <AnimatePresence mode="wait">
                  <motion.p
                    key={phraseIndex}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25 }}
                    className="text-xs text-[var(--text-secondary)] font-medium"
                  >
                    {waitingPhrases[phraseIndex]}
                  </motion.p>
                </AnimatePresence>
              </div>

              <p className="text-[11px] text-[var(--text-muted)] mt-4">
                {t(
                  "auth.modalRedirectNotice",
                  "Se abrirá la ventana segura del proveedor para autorizar tu cuenta."
                )}
              </p>
            </div>
          ) : (
            /* Error State */
            <div className="py-2 flex flex-col items-center">
              {/* Error Badge with Provider Icon */}
              <div className="relative mb-3 flex items-center justify-center">
                {provider ? (
                  <div className="relative">
                    <div className="size-16 rounded-2xl border border-red-500/40 bg-[var(--surface-elevated)] flex items-center justify-center shadow-lg">
                      {renderIcon()}
                    </div>
                    <div className="absolute -bottom-1 -right-1 size-6 rounded-full bg-red-500 text-white flex items-center justify-center shadow-md">
                      <AlertCircle size={14} />
                    </div>
                  </div>
                ) : (
                  <div className="size-14 rounded-2xl border border-red-500/30 bg-red-500/10 flex items-center justify-center text-red-400 shadow-lg">
                    <AlertCircle size={28} />
                  </div>
                )}
              </div>

              <h3 className="text-base font-bold text-[var(--text-primary)] mb-1">
                {t("auth.modalErrorTitle")}
              </h3>

              <p className="text-xs text-[var(--text-secondary)] mb-4 max-w-[310px] leading-relaxed">
                {(() => {
                  if (!errorMessage) {
                    return t("auth.oauthErrorGeneric");
                  }
                  const lower = errorMessage.toLowerCase();
                  if (
                    lower.includes("multiple accounts") ||
                    lower.includes("linking domain") ||
                    lower.includes("account_exists")
                  ) {
                    return t("auth.oauthMultipleAccounts");
                  }
                  if (lower.includes("unverified") || lower.includes("verification")) {
                    return t("auth.oauthEmailVerificationRequired");
                  }
                  if (
                    lower.includes("database error") ||
                    lower.includes("saving new user")
                  ) {
                    return t("auth.oauthDatabaseError");
                  }
                  return errorMessage;
                })()}
              </p>

              {/* Action Buttons */}
              <div className="w-full space-y-2 pt-1">
                {onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="w-full py-2.5 px-4 rounded-xl font-semibold text-xs text-[var(--bg-base)] bg-[var(--accent-primary)] hover:brightness-110 active:scale-[0.99] transition-all flex items-center justify-center gap-2 shadow-lg shadow-[var(--accent-primary)]/20 cursor-pointer"
                  >
                    <RefreshCw size={14} />
                    <span>
                      {t(
                        "auth.modalRetry",
                        { provider: providerName },
                        "Reintentar con {provider}"
                      )}
                    </span>
                  </button>
                )}

                <button
                  type="button"
                  onClick={onClose}
                  className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] text-[var(--text-primary)] transition-all flex items-center justify-center gap-2 cursor-pointer"
                >
                  <ArrowLeft size={14} />
                  <span>{t("auth.modalTryAnother", "Probar de otra forma")}</span>
                </button>
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
