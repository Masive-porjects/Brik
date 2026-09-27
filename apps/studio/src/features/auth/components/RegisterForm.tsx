"use client";

import { useState, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Mail,
  Lock,
  User as UserIcon,
  Eye,
  EyeOff,
  ArrowRight,
  Loader2,
  AlertCircle,
  CheckCircle2,
  ArrowLeft,
  Check,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useTranslation } from "@/i18n/useTranslation";
import { getRegisterSchema, type RegisterFormData } from "../schemas/authSchemas";
import SocialAuthButtons from "./SocialAuthButtons";

export default function RegisterForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirect") || "/";
  const { t } = useTranslation();

  const [authMethod, setAuthMethod] = useState<"social" | "email">("social");
  const [showPassword, setShowPassword] = useState(false);
  const [serverErrorKey, setServerErrorKey] = useState<string | null>(null);
  const [serverErrorMessage, setServerErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const schema = useMemo(() => getRegisterSchema(t), [t]);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormData>({
    resolver: zodResolver(schema),
    mode: "onChange",
    defaultValues: {
      fullName: "",
      email: "",
      password: "",
    },
  });

  const watchedPassword = watch("password") || "";

  const passwordChecks = [
    { label: t("auth.pwdMinLen", "8+ carac."), valid: watchedPassword.length >= 8 },
    { label: t("auth.pwdUpper", "1 Mayús."), valid: /[A-Z]/.test(watchedPassword) },
    { label: t("auth.pwdLower", "1 Minús."), valid: /[a-z]/.test(watchedPassword) },
    { label: t("auth.pwdNumber", "1 Núm."), valid: /[0-9]/.test(watchedPassword) },
    { label: t("auth.pwdSpecial", "1 Símbolo"), valid: /[^A-Za-z0-9]/.test(watchedPassword) },
  ];

  const supabase = createClient();

  const onSubmit = async (data: RegisterFormData) => {
    setServerErrorKey(null);
    setServerErrorMessage(null);
    setSuccessMessage(null);

    try {
      const { data: authData, error: signUpError } = await supabase.auth.signUp({
        email: data.email,
        password: data.password,
        options: {
          data: {
            full_name: data.fullName.trim() || undefined,
          },
        },
      });

      if (signUpError) {
        const errorMsg = signUpError.message.toLowerCase();
        if (errorMsg.includes("already registered") || errorMsg.includes("already exists")) {
          setServerErrorKey("auth.emailAlreadyRegistered");
        } else {
          setServerErrorMessage(signUpError.message);
        }
        return;
      }

      // Supabase returns empty identities array when user already exists (preventing email enumeration)
      if (
        authData.user &&
        Array.isArray(authData.user.identities) &&
        authData.user.identities.length === 0
      ) {
        setServerErrorKey("auth.emailAlreadyRegistered");
        return;
      }

      if (authData.session) {
        // Immediate login if email confirmation is disabled
        router.push(redirectTo);
        router.refresh();
      } else {
        // Email confirmation required by project settings
        setSuccessMessage(t("auth.verificationEmailSent"));
      }
    } catch {
      setServerErrorKey("auth.errorGeneric");
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
          {t("auth.registerTitle")}
        </h1>
        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
          {authMethod === "social"
            ? t("auth.registerSocialSubtitle")
            : t("auth.registerSubtitle")}
        </p>
      </div>

      {(serverErrorKey || serverErrorMessage) && (
        <div className="mb-2.5 p-2 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400 text-[11px] flex items-center gap-2">
          <AlertCircle size={14} className="shrink-0" />
          <span>{serverErrorKey ? t(serverErrorKey) : serverErrorMessage}</span>
        </div>
      )}

      {successMessage && (
        <div className="mb-2.5 p-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-[11px] flex items-center gap-2">
          <CheckCircle2 size={14} className="shrink-0" />
          <span>{successMessage}</span>
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
              mode="register"
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
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-2">
              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-0.5">
                  {t("auth.nameLabel", "Nombre o Alias")}
                </label>
                <div className="relative">
                  <UserIcon
                    size={15}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                  />
                  <input
                    type="text"
                    {...register("fullName")}
                    placeholder="Sound Producer"
                    className={`w-full pl-9 pr-3 py-1.5 text-xs rounded-xl border bg-[var(--surface-elevated)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none transition-all ${
                      errors.fullName
                        ? "border-red-500/50 focus:border-red-500"
                        : "border-[var(--border-subtle)] focus:border-[var(--accent-primary)]"
                    }`}
                  />
                </div>
                {errors.fullName && (
                  <p className="text-[10px] text-red-400 mt-0.5 pl-1">
                    {errors.fullName.message}
                  </p>
                )}
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-0.5">
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
                  <p className="text-[10px] text-red-400 mt-0.5 pl-1">{errors.email.message}</p>
                )}
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[var(--text-secondary)] mb-0.5">
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

                {/* Micro-requisitos interactivos de contraseña */}
                <div className="flex flex-wrap gap-1 mt-1">
                  {passwordChecks.map((chk) => (
                    <span
                      key={chk.label}
                      className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[9px] font-medium transition-all ${
                        chk.valid
                          ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                          : "bg-[var(--surface-base)] text-[var(--text-muted)] border border-[var(--border-subtle)]"
                      }`}
                    >
                      {chk.valid ? (
                        <Check size={9} className="shrink-0 stroke-[2.5]" />
                      ) : (
                        <span className="size-1 rounded-full bg-current opacity-50 shrink-0" />
                      )}
                      <span>{chk.label}</span>
                    </span>
                  ))}
                </div>

                {errors.password && (
                  <p className="text-[10px] text-red-400 mt-1 pl-1">
                    {errors.password.message}
                  </p>
                )}
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full mt-1.5 py-2.5 px-4 rounded-xl font-semibold text-xs text-[var(--bg-base)] bg-[var(--accent-primary)] hover:brightness-110 active:scale-[0.99] transition-all flex items-center justify-center gap-2 shadow-lg shadow-[var(--accent-primary)]/20 disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
              >
                {isSubmitting ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <>
                    <span>{t("auth.registerButton", "Crear Cuenta")}</span>
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
                <span>{t("auth.backToSocialOptions", "Ver otras formas de registro")}</span>
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] text-center">
        <p className="text-[11px] text-[var(--text-secondary)]">
          {t("auth.alreadyHaveAccount", "¿Ya tienes una cuenta?")}{" "}
          <Link
            href={`/login${redirectTo !== "/" ? `?redirect=${encodeURIComponent(redirectTo)}` : ""}`}
            className="text-[var(--accent-primary)] hover:underline font-semibold"
          >
            {t("auth.signInLink", "Inicia sesión")}
          </Link>
        </p>
      </div>
    </motion.div>
  );
}
