"use client";

import { useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Sparkles, Sliders, Layers } from "lucide-react";
import { useTranslation } from "@/i18n";
import { GhostIcon } from "@/presentation/components/ThemeToggle";

const PROMPT_SCENARIOS = [
  { id: "prompt1" },
  { id: "prompt2" },
  { id: "prompt3" },
] as const;

type ScenarioId = (typeof PROMPT_SCENARIOS)[number]["id"];

/**
 * Floating glassmorphism chat showcase for BrikIA.
 * Explains how natural-language instructions unlock thousands of mix & master
 * combinations while building intrigue through interactive prompt previews.
 */
export default function LandingBrikIA() {
  const { t } = useTranslation();
  const [activeScenario, setActiveScenario] = useState<ScenarioId>("prompt1");

  return (
    <section
      id="brik-ia"
      className="relative w-full overflow-hidden bg-[var(--bg-app)] px-4 py-24 sm:px-8 lg:px-12 lg:py-32"
    >
      {/* Subtle ambient glow behind the floating glass chat */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[360px] w-[360px] sm:h-[460px] sm:w-[620px] rounded-full opacity-20 blur-[130px]"
        style={{
          background:
            "radial-gradient(circle, rgba(110,233,224,0.45) 0%, rgba(175,82,222,0.25) 55%, transparent 75%)",
        }}
      />

      <div className="relative z-10 mx-auto grid max-w-5xl grid-cols-1 items-center gap-12 lg:grid-cols-12">
        {/* Left column: intrigue & explanation */}
        <div className="flex flex-col gap-5 lg:col-span-5">
          <span className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3.5 py-1 text-[11px] font-semibold uppercase tracking-widest text-primary">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            {t("landing.brikIA.badge", "BrikIA · Productor Conversacional")}
          </span>

          <h2 className="text-balance text-3xl font-bold leading-tight tracking-tight text-[var(--text-primary)] sm:text-4xl">
            {t(
              "landing.brikIA.title",
              "Pídele el sonido que imaginas. BrikIA construye la ruta."
            )}
          </h2>

          <p className="text-sm leading-relaxed text-[var(--text-secondary)] sm:text-base">
            {t(
              "landing.brikIA.subtitle",
              "No estás atado a un botón fijo. Escríbele una instrucción y BrikIA traduce tu intención en miles de combinaciones posibles de stems, mezcla y masterización."
            )}
          </p>

          <ul className="mt-1 flex flex-col gap-3 text-xs sm:text-sm text-[var(--text-secondary)]">
            <li className="flex items-start gap-2.5">
              <Layers className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <span>
                {t(
                  "landing.brikIA.bullet1",
                  "Detecta si tu pista necesita separar voces, bajo o batería antes de tocar el master."
                )}
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <Sliders className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <span>
                {t(
                  "landing.brikIA.bullet2",
                  "Combina saturación, imagen estéreo, control dinámico y balance por canal a partir de tus palabras."
                )}
              </span>
            </li>
          </ul>

          <p className="text-xs italic text-[var(--text-muted)]">
            {t(
              "landing.brikIA.intrigue",
              "¿Qué pasa cuando le pides algo que ningún preset estándar tiene? Entra al estudio y descúbrelo con tu propia pista."
            )}
          </p>
        </div>

        {/* Right column: Floating Glassmorphism Chat Window */}
        <div className="lg:col-span-7">
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="relative mx-auto w-full max-w-xl rounded-3xl border border-white/15 bg-white/[0.04] p-4 sm:p-6 shadow-[0_24px_80px_rgba(0,0,0,0.65)] backdrop-blur-2xl"
          >
            {/* Chat Header */}
            <div className="flex items-center justify-between border-b border-white/10 pb-3.5">
              <div className="flex items-center gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-2xl border border-primary/30 bg-primary/15 text-primary shadow-[0_0_16px_rgba(110,233,224,0.25)]">
                  <GhostIcon size={18} />
                </span>
                <div className="flex flex-col">
                  <span className="text-sm font-bold text-[var(--text-primary)]">
                    {t("landing.brikIA.chatHeader", "BrikIA")}
                  </span>
                  <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-primary">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                    {t("landing.brikIA.chatStatus", "Escuchando intención · Miles de rutas DSP")}
                  </span>
                </div>
              </div>

              <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] font-medium text-[var(--text-muted)]">
                {t("landing.brikIA.tryPromptsLabel", "Prueba una instrucción")}
              </span>
            </div>

            {/* Interactive prompt selector pills */}
            <div className="mt-3.5 flex flex-wrap gap-2">
              {PROMPT_SCENARIOS.map((item) => {
                const isSelected = activeScenario === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActiveScenario(item.id)}
                    aria-pressed={isSelected}
                    className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition-all ${
                      isSelected
                        ? "border-primary bg-primary/15 text-primary shadow-[0_0_14px_rgba(110,233,224,0.2)]"
                        : "border-white/10 bg-white/[0.03] text-[var(--text-secondary)] hover:border-white/25 hover:text-[var(--text-primary)]"
                    }`}
                  >
                    {t(`landing.brikIA.scenarios.${item.id}.chip`)}
                  </button>
                );
              })}
            </div>

            {/* Conversation Stream */}
            <AnimatePresence mode="wait">
              <motion.div
                key={activeScenario}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22 }}
                className="mt-4 flex flex-col gap-3.5"
              >
                {/* User instruction bubble */}
                <div className="ml-auto max-w-[88%] rounded-2xl rounded-br-sm border border-primary/25 bg-primary/10 px-4 py-3 text-left text-xs sm:text-sm leading-relaxed text-[var(--text-primary)]">
                  “{t(`landing.brikIA.scenarios.${activeScenario}.userPrompt`)}”
                </div>

                {/* BrikIA glass response bubble */}
                <div className="mr-auto flex max-w-[92%] flex-col gap-2.5 rounded-2xl rounded-bl-sm border border-white/12 bg-black/40 px-4 py-3.5 text-left backdrop-blur-xl">
                  <div className="flex items-center gap-2 text-[11px] font-semibold text-primary">
                    <GhostIcon size={14} />
                    <span>{t("landing.brikIA.agentReplyLabel", "Diagnóstico y ruta generada")}</span>
                  </div>
                  <p className="text-xs sm:text-sm leading-relaxed text-[var(--text-secondary)]">
                    {t(`landing.brikIA.scenarios.${activeScenario}.agentReply`)}
                  </p>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {(["tag1", "tag2", "tag3"] as const).map((tagKey) => (
                      <span
                        key={tagKey}
                        className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-primary"
                      >
                        {t(`landing.brikIA.scenarios.${activeScenario}.${tagKey}`)}
                      </span>
                    ))}
                  </div>
                </div>
              </motion.div>
            </AnimatePresence>

            {/* Simulated Composer Input Bar that leads to Studio */}
            <div className="mt-4 flex items-center justify-between gap-2 rounded-2xl border border-white/12 bg-black/50 px-3.5 py-2.5 backdrop-blur-md">
              <span className="truncate text-xs text-[var(--text-muted)]">
                {t(
                  "landing.brikIA.inputPlaceholder",
                  "Escribe cómo quieres que suene tu mezcla en el estudio…"
                )}
              </span>
              <Link
                href="/upload"
                aria-label={t("landing.hero.ctaEnter", "Ingresar a Brik Studio")}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-semibold text-[var(--color-on-primary)] transition-colors hover:bg-primary-container"
              >
                <span>{t("landing.brikIA.openChatCta", "Probar en Studio")}</span>
                <Send className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
