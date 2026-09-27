"use client";

// ============================================================================
// TODO: FASE LANDING PAGE
// Esta ruta ("/") será el portal y landing page comercial completo de WaveIA.
// Dicho desarrollo se abordará en una fase dedicada futura.
// Por ahora, se mantiene esta pantalla limpia, estética y desacoplada
// que canaliza el flujo principal hacia "/upload" y "/mezclas".
// ============================================================================

import Link from "next/link";
import { motion } from "framer-motion";
import { Sparkles, ArrowRight, Music2, Sliders, ShieldCheck, Waves } from "lucide-react";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import { UserMenu, useAuth } from "@/features/auth";
import { useTranslation } from "@/i18n";
import { useMastering } from "@/features/mastering";
import { useIsMounted } from "@/shared/hooks";

export default function HomePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { session } = useMastering();
  const isMounted = useIsMounted();

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg-app)] text-[var(--text-primary)] font-sans relative overflow-x-hidden selection:bg-[var(--accent-primary)] selection:text-white">
      {/* Background Ambient Glow */}
      <div 
        className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[700px] h-[500px] rounded-full blur-[140px] opacity-25"
        style={{
          background: "radial-gradient(circle, var(--accent-primary) 0%, rgba(98, 126, 132, 0.15) 50%, transparent 80%)"
        }}
        aria-hidden="true"
      />

      {/* Top Navigation */}
      <header className="relative z-20 flex items-center justify-between px-6 py-4 max-w-7xl mx-auto w-full">
        <div className="flex items-center gap-3">
          <div className="rounded-full px-4 py-2 glass flex items-center gap-2 border border-[var(--border-subtle)]">
            <Waves className="w-5 h-5 text-[var(--accent-primary)] animate-pulse" />
            <span className="text-base font-bold tracking-tight">
              Wave<span className="text-[var(--accent-primary)]">IA</span>
            </span>
          </div>
          <span className="text-[10px] uppercase font-bold tracking-widest px-2 py-0.5 rounded-full bg-[var(--surface-elevated)] border border-[var(--border-subtle)] text-[var(--text-muted)]">
            Studio v1.0
          </span>
        </div>

        <div className="flex items-center gap-3">
          <LanguageSwitcher />
          <ThemeToggle />
          <UserMenu />
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1 flex flex-col items-center justify-center px-4 py-12 relative z-10 max-w-5xl mx-auto text-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="space-y-6"
        >
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium border border-[var(--border-strong)] bg-[var(--surface-elevated)] text-[var(--text-secondary)] shadow-sm">
            <Sparkles className="w-3.5 h-3.5 text-[var(--accent-secondary)]" />
            <span>{t("landing.badge", "Motor DSP de Masterización Profesional con IA")}</span>
          </div>

          {/* Heading */}
          <h1 className="text-4xl sm:text-6xl font-black tracking-tight leading-[1.1] text-balance max-w-3xl mx-auto">
            Lleva tu música al estándar comercial con{" "}
            <span className="bg-gradient-to-r from-[var(--text-primary)] via-[var(--accent-secondary)] to-[var(--accent-primary)] bg-clip-text text-transparent">
              precisión de estudio
            </span>
          </h1>

          {/* Subtitle */}
          <p className="text-base sm:text-lg text-[var(--text-secondary)] max-w-2xl mx-auto font-light leading-relaxed">
            {t(
              "landing.subtitle",
              "Sube tus tracks, ajusta parámetros analógicos de EQ, compresión y limitación o deja que nuestra IA optimice el balance tonal y sonoridad LUFS."
            )}
          </p>

          {/* Action CTAs */}
          <div className="pt-4 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/upload"
              target="_blank"
              rel="noopener noreferrer"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2.5 px-8 py-3.5 rounded-xl font-semibold text-sm bg-[var(--accent-primary)] hover:bg-[var(--accent-hover)] text-white shadow-[0_4px_24px_rgba(98,126,132,0.35)] transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
            >
              <span>{t("landing.ctaUpload", "Iniciar Estudio / Subir Audio")}</span>
              <ArrowRight className="w-4 h-4" />
            </Link>

            {isMounted && (
              <Link
                href="/mezclas"
                target="_blank"
                rel="noopener noreferrer"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl font-semibold text-sm border border-[var(--border-strong)] bg-[var(--surface-elevated)] hover:bg-[var(--surface-hover)] text-[var(--text-primary)] transition-all cursor-pointer"
              >
                <Music2 className="w-4 h-4 text-[var(--accent-secondary)]" />
                <span>{t("landing.ctaMezclas", "Ir al Panel de Mezclas / Master")}</span>
              </Link>
            )}
          </div>

          {/* Feature Highlights Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-12 text-left max-w-4xl mx-auto">
            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)]/60 backdrop-blur-md">
              <div className="size-10 rounded-xl bg-[var(--accent-primary)]/10 border border-[var(--accent-primary)]/20 flex items-center justify-center mb-3">
                <Sliders className="size-5 text-[var(--accent-primary)]" />
              </div>
              <h3 className="font-semibold text-sm mb-1 text-[var(--text-primary)]">DSP Analógico & IA</h3>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                Control de ecualización dinámica, compresión multibanda, calidez a válvulas y limitación True-Peak.
              </p>
            </div>

            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)]/60 backdrop-blur-md">
              <div className="size-10 rounded-xl bg-[var(--accent-secondary)]/10 border border-[var(--accent-secondary)]/20 flex items-center justify-center mb-3">
                <Music2 className="size-5 text-[var(--accent-secondary)]" />
              </div>
              <h3 className="font-semibold text-sm mb-1 text-[var(--text-primary)]">Historial & Masters</h3>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                Guarda borradores en tiempo real, compara versiones A/B y descarga masters de alta fidelidad.
              </p>
            </div>

            <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-emerald-500/10 border-emerald-500/20 flex flex-col justify-between">
              <div>
                <div className="size-10 rounded-xl bg-emerald-500/20 flex items-center justify-center mb-3">
                  <ShieldCheck className="size-5 text-emerald-400" />
                </div>
                <h3 className="font-semibold text-sm mb-1 text-[var(--text-primary)]">Target Streaming Ready</h3>
                <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                  Optimizado para Spotify (-14 LUFS), Apple Music (-16 LUFS) y clubs con total inmunidad al clipping.
                </p>
              </div>
            </div>
          </div>
        </motion.div>
      </main>

      {/* Clean Footer */}
      <footer className="relative z-10 py-6 border-t border-[var(--border-subtle)] text-center text-xs text-[var(--text-muted)]">
        <p>© {new Date().getFullYear()} WaveIA Studio. Todos los derechos reservados.</p>
      </footer>
    </div>
  );
}
