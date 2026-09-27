"use client";

import { useState, useEffect, useCallback } from "react";
import { Mail, Loader2, AlertCircle } from "lucide-react";
import type { Provider } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { useTranslation } from "@/i18n/useTranslation";
import { GoogleIcon, SpotifyIcon, DiscordIcon, GitHubIcon } from "./SocialIcons";
import SocialStatusModal, { type SocialProvider } from "./SocialStatusModal";

const PROVIDER_SCOPES: Record<SocialProvider, string> = {
  spotify: "user-read-email user-read-private",
  google: "email profile openid",
  discord: "identify email",
  github: "read:user user:email",
};

interface SocialAuthButtonsProps {
  mode: "login" | "register";
  redirectTo?: string;
  onContinueWithEmail: () => void;
}

export default function SocialAuthButtons({
  mode,
  redirectTo = "/",
  onContinueWithEmail,
}: SocialAuthButtonsProps) {
  const { t } = useTranslation();
  const [loadingProvider, setLoadingProvider] = useState<SocialProvider | null>(null);
  const [modalState, setModalState] = useState<{
    isOpen: boolean;
    provider: SocialProvider | null;
    status: "connecting" | "error";
    errorMessage?: string | null;
  }>({
    isOpen: false,
    provider: null,
    status: "connecting",
  });

  const supabase = createClient();

  // Reset loader if user presses Back button in browser (bfcache fix)
  useEffect(() => {
    const handlePageShow = () => {
      setLoadingProvider(null);
      setModalState((prev) => ({ ...prev, isOpen: false }));
    };

    window.addEventListener("pageshow", handlePageShow);
    return () => window.removeEventListener("pageshow", handlePageShow);
  }, []);

  const handleOAuthSignIn = useCallback(
    async (provider: SocialProvider) => {
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem("waveia_last_auth_provider", provider);
        } catch {
          // Ignore storage errors
        }
      }
      setLoadingProvider(provider);
      setModalState({
        isOpen: true,
        provider,
        status: "connecting",
        errorMessage: null,
      });

      try {
        const redirectUrl = `${window.location.origin}/auth/callback?next=${encodeURIComponent(
          redirectTo
        )}`;

        const { error } = await supabase.auth.signInWithOAuth({
          provider: provider as Provider,
          options: {
            redirectTo: redirectUrl,
            scopes: PROVIDER_SCOPES[provider],
            queryParams: provider === "spotify" ? { show_dialog: "true" } : undefined,
          },
        });

        if (error) {
          setLoadingProvider(null);
          setModalState({
            isOpen: true,
            provider,
            status: "error",
            errorMessage: error.message,
          });
        }
      } catch {
        setLoadingProvider(null);
        setModalState({
          isOpen: true,
          provider,
          status: "error",
          errorMessage: t(
            "auth.oauthErrorGeneric",
            "Error al iniciar sesión con el proveedor seleccionado."
          ),
        });
      }
    },
    [redirectTo, supabase.auth, t]
  );

  const handleCloseModal = () => {
    setLoadingProvider(null);
    setModalState({
      isOpen: false,
      provider: null,
      status: "connecting",
      errorMessage: null,
    });
  };

  const handleRetry = () => {
    if (modalState.provider) {
      handleOAuthSignIn(modalState.provider);
    }
  };

  return (
    <>
      <div className="space-y-3">
        {/* Primary Social Options */}
        <div className="space-y-2">
          {/* Google */}
          <button
            type="button"
            disabled={!!loadingProvider}
            onClick={() => handleOAuthSignIn("google")}
            className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] hover:border-[var(--accent-primary)] text-xs font-semibold text-[var(--text-primary)] transition-all cursor-pointer disabled:opacity-50 shadow-sm"
          >
            {loadingProvider === "google" ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <GoogleIcon className="size-4 shrink-0" />
            )}
            <span>{t("auth.continueWithGoogle", "Continuar con Google")}</span>
          </button>

          {/* Secondary Social Options (Discord & GitHub) */}
          <div className="grid grid-cols-2 gap-2">
            {/* Discord */}
            <button
              type="button"
              disabled={!!loadingProvider}
              onClick={() => handleOAuthSignIn("discord")}
              className="flex items-center justify-center gap-2 py-2 px-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] hover:border-[#5865F2] text-xs font-medium text-[var(--text-primary)] transition-all cursor-pointer disabled:opacity-50"
            >
              {loadingProvider === "discord" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <DiscordIcon className="size-4 shrink-0" />
              )}
              <span>Discord</span>
            </button>

            {/* GitHub */}
            <button
              type="button"
              disabled={!!loadingProvider}
              onClick={() => handleOAuthSignIn("github")}
              className="flex items-center justify-center gap-2 py-2 px-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] hover:border-[var(--accent-primary)] text-xs font-medium text-[var(--text-primary)] transition-all cursor-pointer disabled:opacity-50"
            >
              {loadingProvider === "github" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <GitHubIcon className="size-4 shrink-0" />
              )}
              <span>GitHub</span>
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="relative my-3 flex items-center justify-center">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[var(--border-subtle)]" />
          </div>
          <span className="relative px-2 bg-[var(--surface-elevated)] text-[10px] uppercase font-bold tracking-wider text-[var(--text-muted)] rounded-full border border-[var(--border-subtle)]">
            {t("auth.orContinueWith", "o continúa con")}
          </span>
        </div>

        {/* Switch to email form button */}
        <button
          type="button"
          onClick={onContinueWithEmail}
          className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold border border-[var(--accent-primary)]/40 bg-[var(--accent-primary)]/10 hover:bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] transition-all flex items-center justify-center gap-2 cursor-pointer shadow-sm"
        >
          <Mail size={15} />
          <span>
            {mode === "login"
              ? t("auth.continueWithEmail", "Ingresar con Correo y Contraseña")
              : t("auth.registerWithEmail", "Registrarse con Correo Electrónico")}
          </span>
        </button>
      </div>

      {/* Modern Status Modal (Connecting or Error) */}
      <SocialStatusModal
        isOpen={modalState.isOpen}
        provider={modalState.provider}
        status={modalState.status}
        errorMessage={modalState.errorMessage}
        onClose={handleCloseModal}
        onRetry={handleRetry}
      />
    </>
  );
}
