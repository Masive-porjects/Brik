"use client";

import { useState, useMemo, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Mail, Lock, Eye, EyeOff, ArrowRight, Loader2, AlertCircle, ArrowLeft } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useTranslation } from "@/i18n/useTranslation";
import { getLoginSchema, type LoginFormData } from "../schemas/authSchemas";
import SocialAuthButtons from "./SocialAuthButtons";
import SocialStatusModal, { type SocialProvider } from "./SocialStatusModal";

export default function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirect") || "/";
  const { t } = useTranslation();

  const [authMethod, setAuthMethod] = useState<"social" | "email">("social");
  const [showPassword, setShowPassword] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [errorModal, setErrorModal] = useState<{
    isOpen: boolean;
    provider: SocialProvider | null;
    message: string | null;
  }>({
    isOpen: false,
    provider: null,
    message: null,
  });

  useEffect(() => {
    const errorParam = searchParams.get("error");
    if (!errorParam) return;

    const providerParam = searchParams.get("provider");
    let detectedProvider: SocialProvider | null = null;
    if (
      providerParam &&
      ["google", "spotify", "discord", "github"].includes(providerParam.toLowerCase())
    ) {
      detectedProvider = providerParam.toLowerCase() as SocialProvider;
    } else {
      const lower = errorParam.toLowerCase();
      if (lower.includes("spotify")) detectedProvider = "spotify";
      else if (lower.includes("discord")) detectedProvider = "discord";
      else if (lower.includes("google")) detectedProvider = "google";
      else if (lower.includes("github")) detectedProvider = "github";
    }

    let message = decodeURIComponent(errorParam);
    if (
      errorParam === "account_exists_with_different_provider" ||
      errorParam.includes("multiple accounts") ||
      errorParam.includes("linking domain")
    ) {
      message = t("auth.oauthMultipleAccounts");
    } else if (
      errorParam.includes("provider_email_needs_verification") ||
      errorParam.toLowerCase().includes("unverified email")
    ) {
      message = t("auth.oauthEmailVerificationRequired");
    } else if (errorParam === "auth_callback_failed") {
      message = t("auth.oauthErrorGeneric");
    }

    setServerError(message);
    setErrorModal({
      isOpen: true,
      provider: detectedProvider,
      message,
    });
  }, [searchParams, t]);

  const handleCloseErrorModal = () => {
    setErrorModal({ isOpen: false, provider: null, message: null });
    setServerError(null);
    router.replace(
      redirectTo !== "/" ? `/login?redirect=${encodeURIComponent(redirectTo)}` : "/login"
    );
  };

  const schema = useMemo(() => getLoginSchema(t), [t]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormData>({
    resolver: zodResolver(schema),
    mode: "onChange",
    defaultValues: {
      email: "",
      password: "",
    },
  });

  const supabase = createClient();

  const onSubmit = async (data: LoginFormData) => {
    setServerError(null);

    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: data.email,
        password: data.password,
      });

      if (signInError) {
        setServerError(signInError.message);
        return;
      }

      router.push(redirectTo);
      router.refresh();
    } catch {
      setServerError(t("auth.errorGeneric", "Ocurrió un error inesperado al iniciar sesión."));
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="w-full max-w-[390px] mx-auto p-5 sm:p-6 rounded-3xl border shadow-2xl backdrop-blur-2xl relative overflow-hidden"
      style={{
        background: "var(--bg-glass-elevated)",
        borderColor: "var(--border-strong)",
        boxShadow: "0 24px 60px -15px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.08)",
      }}
    >
      <div className="text-center mb-3">
        <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider mb-1.5 border border-[var(--accent-primary)]/30 bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]">
          WaveIA Studio
        </div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[var(--text-primary)]">
          {t("auth.loginTitle", "Iniciar Sesión")}
        </h1>
        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
          {authMethod === "social"
            ? t("auth.loginSocialSubtitle", "Elige tu método preferido para ingresar")
            : t("auth.loginSubtitle", "Accede a tus proyectos y masters en la nube")}
        </p>
      </div>

      {serverError && (
        <div className="mb-2.5 p-2 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400 text-[11px] flex items-center gap-2">
          <AlertCircle size={14} className="shrink-0" />
          <span>{serverError}</span>
        </div>
      )}

      <AnimatePresence mode="wait">
        {authMethod === "social" ? (
          <motion.div
            key="social"
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 10 }}
            transition={{ duration: 0.2 }}
          >
            <SocialAuthButtons
              mode="login"
              redirectTo={redirectTo}
              onContinueWithEmail={() => setAuthMethod("email")}
            />
          </motion.div>
        ) : (
          <motion.div
            key="email"
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ duration: 0.2 }}
          >
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-2.5">
              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-1">
                  {t("auth.emailLabel", "Correo Electrónico")}
                </label>
                <div className="relative">
                  <Mail
                    size={15}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                  />
                  <input
                    type="email"
                    {...register("email")}
                    placeholder="producer@waveia.com"
                    className={`w-full pl-9 pr-3 py-1.5 text-xs rounded-xl border bg-[var(--surface-elevated)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none transition-all ${
                      errors.email
                        ? "border-red-500/50 focus:border-red-500"
                        : "border-[var(--border-subtle)] focus:border-[var(--accent-primary)]"
                    }`}
                  />
                </div>
                {errors.email && (
                  <p className="text-[10px] text-red-400 mt-1 pl-1">{errors.email.message}</p>
                )}
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-1">
                  {t("auth.passwordLabel", "Contraseña")}
                </label>
                <div className="relative">
                  <Lock
                    size={15}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                  />
                  <input
                    type={showPassword ? "text" : "password"}
                    {...register("password")}
                    placeholder="••••••••"
                    className={`w-full pl-9 pr-9 py-1.5 text-xs rounded-xl border bg-[var(--surface-elevated)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none transition-all ${
                      errors.password
                        ? "border-red-500/50 focus:border-red-500"
                        : "border-[var(--border-subtle)] focus:border-[var(--accent-primary)]"
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1 cursor-pointer"
                  >
                    {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                {errors.password && (
                  <p className="text-[10px] text-red-400 mt-1 pl-1">{errors.password.message}</p>
                )}
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full mt-1 py-2.5 px-4 rounded-xl font-semibold text-xs text-[var(--bg-base)] bg-[var(--accent-primary)] hover:brightness-110 active:scale-[0.99] transition-all flex items-center justify-center gap-2 shadow-lg shadow-[var(--accent-primary)]/20 disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
              >
                {isSubmitting ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <>
                    <span>{t("auth.loginButton", "Entrar")}</span>
                    <ArrowRight size={14} />
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={() => setAuthMethod("social")}
                className="w-full text-center text-[11px] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors pt-1 flex items-center justify-center gap-1 cursor-pointer"
              >
                <ArrowLeft size={12} />
                <span>{t("auth.backToSocialOptions", "Ver otras formas de ingreso")}</span>
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] text-center">
        <p className="text-[11px] text-[var(--text-secondary)]">
          {t("auth.dontHaveAccount", "¿No tienes una cuenta?")}{" "}
          <Link
            href={`/register${redirectTo !== "/" ? `?redirect=${encodeURIComponent(redirectTo)}` : ""}`}
            className="text-[var(--accent-primary)] hover:underline font-semibold"
          >
            {t("auth.createAccount", "Regístrate gratis")}
          </Link>
        </p>
      </div>

      {/* OAuth Callback Error Resolution Modal */}
      <SocialStatusModal
        isOpen={errorModal.isOpen}
        provider={errorModal.provider}
        status="error"
        errorMessage={errorModal.message}
        onClose={handleCloseErrorModal}
      />
    </motion.div>
  );
}
