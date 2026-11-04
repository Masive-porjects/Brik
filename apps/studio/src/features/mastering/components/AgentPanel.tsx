"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Loader2,
  Sparkles,
  XCircle,
  Info,
  Sparkle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getAgentJobStatus,
  getAudioUrl,
  getMixAudioUrl,
  submitAgentJob,
  type AgentAudioAsset,
  type AgentChangeReport,
  type AgentChangeReportBlock,
  type AgentNarrativeItem,
  type AgentRunResult,
  type AgentToolExecution,
  type AudioVerdict,
  type Deficiency,
  type Route,
} from "@/lib/api";
import { genreDisplayLabel } from "@/lib/audioUtils";
import { useTranslation } from "@/i18n";

import MixWaveformAB from "@/presentation/components/MixWaveformAB";

import { narrativeSentence } from "./narrativeText";
import { escalationDecision } from "./escalationJob";
import AgentStemStack from "./AgentStemStack";

/**
 * Módulo Brik — Capa de decisión interactiva (T6-T8).
 *
 * Flujo conversacional:
 *  1. El usuario escribe en el composer → POST /agent/chat
 *  2. El router heurístico decide:
 *     - answer_in_chat: Brik responde, se muestra en la lista
 *     - escalate_to_job: Toast "Proceso lanzado", se dispara job async
 *     - updates_intent: Pill "Intención actualizada — confirmá para aplicar"
 *  3. El transcript se persiste en el backend (FIFO 20 turnos)
 *
 * El panel NO ejecuta DSP ni interpreta la intención: encola jobs, espera y
 * muestra lo que el backend registró. El diagnóstico, la lista de herramientas y
 * las métricas vienen del `tool_log` real del loop, no se deducen de archivos.
 */

const CARD_STYLE: React.CSSProperties = {
  position: "relative",
  background: "var(--bg-glass)",
  backdropFilter: "blur(16px)",
  WebkitBackdropFilter: "blur(16px)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "1rem",
  boxShadow: "var(--shadow-card)",
};

const AGENT_POLL_MS = 2_000;
const AGENT_TIMEOUT_MS = 1_800_000;
const OK_COLOR = "#30d158";

/** Estados internos del flujo de decisión (legacy + chat). */
export type DecisionPhase =
  | "idle"
  | "analyzing"
  | "verdict"
  | "producing"
  | "completed"
  | "error";

interface AgentPanelProps {
  sessionId: string | null;
  disabled?: boolean;
  /**
   * Hides the internal title block and turns the panel into a full-height
   * column: scrollable body + sticky composer. Used when the panel lives
   * inside the Brik rail, which already renders the title in its header.
   */
  compact?: boolean;
  /** Lets the rail paint the engine status badge without owning the flow. */
  onPhaseChange?: (phase: DecisionPhase) => void;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  ts: number;
  escalated?: boolean;
  intentPill?: boolean;
}

export default function AgentPanel({
  sessionId,
  disabled,
  compact = false,
  onPhaseChange,
}: AgentPanelProps) {
  const { t } = useTranslation();

  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [composerInput, setComposerInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [escalateNotice, setEscalateNotice] = useState(false);

  // Legacy flow state (for verdict/producing phases)
  const [phase, setPhase] = useState<DecisionPhase>("idle");
  const [verdict, setVerdict] = useState<AudioVerdict | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [selectedRoute, setSelectedRoute] = useState<"auto" | "mix_then_master" | "master_only">("auto");
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timedOutRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
      abortRef.current?.abort();
      pollAbortRef.current?.abort();
    };
  }, []);

  // El rail pinta el estado del motor sin ser dueño del flujo de decisión.
  useEffect(() => {
    onPhaseChange?.(phase);
  }, [phase, onPhaseChange]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  const sleep = (ms: number, signal: AbortSignal) =>
    new Promise<void>((resolve, reject) => {
      if (signal.aborted) {
        reject(new DOMException("Aborted", "AbortError"));
        return;
      }
      const timer = setTimeout(resolve, ms);
      signal.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });

  /** Dispara un job del Productor y lo sigue hasta el estado terminal.
   *
   *  Un solo camino para las dos entradas: la escalada del chat y el botón
   *  legacy. Antes la escalada era fire-and-forget — el panel decía "proceso
   *  lanzado" y nunca volvía a preguntar, así que un job que moría en el
   *  backend se veía exactamente igual que un job eterno.
   */
  const runAgentJob = useCallback(
    async (
      prompt: string,
      decision: "auto" | "mix_then_master" | "master_only",
    ) => {
      if (!sessionId) return;

      abortRef.current?.abort();
      pollAbortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const pollController = new AbortController();
      pollAbortRef.current = pollController;

      timedOutRef.current = false;
      clearWatchdog();
      watchdogRef.current = setTimeout(() => {
        timedOutRef.current = true;
        controller.abort();
        pollController.abort();
      }, AGENT_TIMEOUT_MS);

      setPhase("producing");
      setError(null);
      setCancelled(false);
      setResult(null);

      try {
        const accepted = await submitAgentJob(
          sessionId,
          prompt,
          decision,
          controller.signal,
        );

        // El loop no expone progreso parcial: se sondea hasta el estado
        // terminal, sin barra de progreso falsa.
        for (;;) {
          await sleep(AGENT_POLL_MS, pollController.signal);
          const state = await getAgentJobStatus(
            accepted.job_id,
            pollController.signal,
          );
          if (state.status === "completed") {
            clearWatchdog();
            if (state.result) setResult(state.result);
            else setError(t("productor.emptyResult"));
            setPhase("completed");
            return;
          }
          if (state.status === "error") {
            clearWatchdog();
            setError(state.error ?? t("productor.interrupted"));
            setPhase("error");
            return;
          }
        }
      } catch (e) {
        const isAbort = (e as { name?: string })?.name === "AbortError";
        if (isAbort && timedOutRef.current) {
          setError(t("productor.timeout"));
        } else if (isAbort) {
          setCancelled(true);
        } else {
          setError(e instanceof Error ? e.message : t("productor.failed"));
        }
        setPhase("error");
      } finally {
        clearWatchdog();
        if (abortRef.current === controller) abortRef.current = null;
        if (pollAbortRef.current === pollController) pollAbortRef.current = null;
      }
    },
    [sessionId, clearWatchdog, t],
  );

  /** Chat flow: send message to /agent/chat and handle response. */
  const handleSendMessage = useCallback(async () => {
    if (!sessionId || !composerInput.trim() || isSending) return;

    const userMessage = composerInput.trim();
    setComposerInput("");
    setIsSending(true);

    // Optimistically add user message
    const userMsg: Message = {
      role: "user",
      content: userMessage,
      ts: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const { chatWithBrik } = await import("@/lib/api");
      const response = await chatWithBrik(sessionId, userMessage, messages);

      // Add assistant response
      const assistantMsg: Message = {
        role: "assistant",
        content: response.reply,
        ts: Date.now(),
        escalated: response.escalation?.action === "escalate_to_job",
        intentPill: response.escalation?.updates_intent === true,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Handle escalation
      if (response.escalation?.action === "escalate_to_job") {
        const { job_kind, job_payload } = response.escalation;
        if (job_kind) {
          setEscalateNotice(true);
          setTimeout(() => setEscalateNotice(false), 4000);

          // El job se sigue hasta el estado terminal: la escalada ya no es
          // fire-and-forget.
          void runAgentJob(
            userMessage,
            escalationDecision(job_kind, job_payload),
          );
        }
      }

      // If intent updates, we already show the pill via the message flag
      // The actual intent merge happens when user confirms via verdict card
    } catch (e) {
      const errorMsg = t("productor.chat.error");
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: errorMsg,
          ts: Date.now(),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }, [sessionId, composerInput, isSending, messages, t, runAgentJob]);

  /** Paso 3 — Lanza el job completo con la decisión elegida (legacy). */
  const handleProduceWithDecision = useCallback(async () => {
    await runAgentJob(composerInput, selectedRoute);
  }, [runAgentJob, composerInput, selectedRoute]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    pollAbortRef.current?.abort();
  }, []);

  const handleBackToVerdict = useCallback(() => {
    setPhase("verdict");
    setSelectedRoute("auto");
  }, []);

  if (!sessionId) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        {t("productor.loadAudioPrompt")}
      </p>
    );
  }

  const isRunning = phase === "analyzing" || phase === "producing";

  // ─── COMPOSER (sticky footer) ───
  const composer = (
    <div
      className={compact ? "shrink-0 border-t px-4 py-3" : "px-4 pt-3"}
      style={compact ? { borderColor: "var(--border-subtle)" } : undefined}
    >
      <div className="flex flex-col gap-2">
        {/* Escalate notice inline */}
        <AnimatePresence>
          {escalateNotice && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="flex items-center gap-2 rounded-xl px-3 py-2 text-xs"
              style={{
                background: "rgba(16, 185, 129, 0.15)",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                color: OK_COLOR,
              }}
            >
              <Sparkles size={13} className="shrink-0" />
              <span className="font-medium">{t("productor.chat.escalateToast")}</span>
              <span style={{ color: "var(--text-muted)" }}>{t("productor.chat.escalateDescription")}</span>
            </motion.div>
          )}
        </AnimatePresence>

        <label htmlFor="agent-prompt" className="sr-only">
          {t("productor.promptLabel")}
        </label>
        <textarea
          id="agent-prompt"
          value={composerInput}
          onChange={(e) => setComposerInput(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSendMessage();
            }
          }}
          disabled={isSending || isRunning || disabled}
          rows={2}
          placeholder={t("productor.chat.placeholder")}
          className="flex-1 resize-none rounded-xl border px-3 py-2 text-sm outline-none
            transition-colors duration-300 focus:border-[var(--accent-primary)]
            disabled:opacity-40"
          style={{
            background: "var(--surface-hover)",
            borderColor: "var(--border-subtle)",
            color: "var(--text-primary)",
          }}
        />
        <button
          type="button"
          onClick={handleSendMessage}
          disabled={isSending || isRunning || disabled || !composerInput.trim()}
          className="shrink-0 flex items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold text-white
            transition-all duration-300 hover:brightness-110
            disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            background: "linear-gradient(135deg, #10b981, #00d4aa)",
            boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)",
          }}
        >
          {isSending ? (
            <>
              <Loader2 size={16} className="animate-spin mr-1.5 animate-pulse" />
              <span className="font-medium text-sm">{t("productor.chat.sending")}</span>
            </>
          ) : (
            <>
              <Sparkle size={16} className="mr-1.5" />
              {t("productor.chat.send")}
            </>
          )}
        </button>
      </div>
    </div>
  );

  return (
    <div
      className={compact ? "flex h-full min-h-0 w-full flex-col" : "w-full max-w-[440px]"}
      style={CARD_STYLE}
    >
      {!compact && (
        <div className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4">
          <div>
            <h2
              className="text-lg font-bold"
              style={{ color: "var(--text-primary)", letterSpacing: "-0.02em" }}
            >
              {t("productor.title")}
            </h2>
            <p className="mt-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
              {t("productor.subtitle")}
            </p>
          </div>
        </div>
      )}

      {!compact && composer}

      <div
        className={
          compact
            ? "min-h-0 flex-1 overflow-y-auto px-4 pt-3"
            : "px-4 pt-3 pb-4"
        }
      >
        {/* ─── MESSAGE LIST ─── */}
        <AnimatePresence mode="popLayout">
          {messages.length > 0 ? (
            <div className="flex-1 min-h-0 flex flex-col overflow-y-auto max-h-[50vh] prose prose-sm break-words" role="log" aria-live="polite">
              {messages.map((msg, idx) => (
                <motion.div
                  key={`${msg.ts}-${idx}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
                  className={`flex gap-2 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
                >
                  <div
                    className={`flex-1 max-w-[85%] ${msg.role === "user" ? "text-right" : ""}`}
                  >
                    <div
                      className={`inline-block rounded-2xl px-3.5 py-2 text-sm leading-relaxed prose break-words ${
                        msg.role === "user"
                          ? "rounded-br-none"
                          : "rounded-bl-none"
                      }`}
                      style={{
                        background:
                          msg.role === "user"
                            ? "var(--accent-primary)"
                            : "var(--surface-hover)",
                        color:
                          msg.role === "user"
                            ? "white"
                            : "var(--text-primary)",
                        border:
                          msg.role === "assistant"
                            ? "1px solid var(--border-subtle)"
                            : "none",
                      }}
                    >
                      {msg.content}
                    </div>

                    {/* Escalation toast indicator */}
                    {msg.escalated && (
                      <motion.div
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="mt-1.5 flex items-center gap-1.5 text-[10px]"
                        style={{ color: "var(--accent-primary)" }}
                      >
                        <Sparkles size={11} />
                        <span>{t("productor.chat.escalateToast")}</span>
                      </motion.div>
                    )}

                    {/* Intent pill */}
                    {msg.intentPill && (
                      <motion.div
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        className="mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em]"
                        style={{
                          background: "rgba(16, 185, 129, 0.15)",
                          color: OK_COLOR,
                          border: "1px solid rgba(16, 185, 129, 0.3)",
                        }}
                      >
                        <Info size={9} />
                        {t("productor.chat.intentPill")}
                      </motion.div>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          ) : (
            <p
              className="text-center text-sm py-8"
              style={{ color: "var(--text-muted)" }}
            >
              {t("productor.chat.noHistory")}
            </p>
          )}
        </AnimatePresence>
        <div ref={messagesEndRef} />

        {/* ─── LEGACY VERDICT / PRODUCING UI ─── */}
        {phase === "verdict" && verdict && (
          <VerdictCard
            verdict={verdict}
            selectedRoute={selectedRoute}
            onRouteChange={setSelectedRoute}
            onConfirm={handleProduceWithDecision}
            onCancel={handleBackToVerdict}
            t={t}
            disabled={disabled}
          />
        )}

        {isRunning && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 flex items-center gap-2"
          >
            <Loader2 size={18} className="animate-spin" style={{ color: "var(--accent-primary)" }} />
            <span className="text-sm" style={{ color: "var(--text-primary)" }}>
              {phase === "analyzing"
                ? t("productor.verdict.analyzing")
                : t("productor.running")}
            </span>
            <button
              type="button"
              onClick={handleCancel}
              className="ml-2 flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold
                transition-colors duration-300 hover:border-[var(--border-hover)]"
              style={{
                background: "var(--surface-hover)",
                borderColor: "var(--border-subtle)",
                color: "var(--text-secondary)",
              }}
            >
              <Ban size={13} />
              {t("productor.cancel")}
            </button>
          </motion.div>
        )}

        {cancelled && (
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 rounded-lg px-3 py-2 text-xs leading-relaxed"
            style={{ background: "var(--surface-hover)", color: "var(--text-secondary)" }}
            role="status"
          >
            {t("productor.cancelled")}
          </motion.p>
        )}

        {(analysisError || error) && (
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 rounded-lg px-3 py-2 text-xs leading-relaxed"
            style={{ background: "var(--surface-hover)", color: "var(--accent-error)" }}
            role="alert"
          >
            {analysisError ?? error}
          </motion.p>
        )}

        {phase === "completed" && result && <AgentResultView result={result} />}
      </div>

      {compact && composer}
    </div>
  );
}

/* ────────────────── Tarjeta de Veredicto (legacy) ────────────────── */

function VerdictCard({
  verdict,
  selectedRoute,
  onRouteChange,
  onConfirm,
  onCancel,
  t,
  disabled,
}: {
  verdict: AudioVerdict;
  selectedRoute: "auto" | "mix_then_master" | "master_only";
  onRouteChange: (r: "auto" | "mix_then_master" | "master_only") => void;
  onConfirm: () => void;
  onCancel: () => void;
  t: (k: string) => string;
  disabled?: boolean;
}) {
  const reasoningLabel = t(`productor.verdict.reasoning.${verdict.reasoning_key}`);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
      className="mt-4 space-y-4"
    >
      {/* Header del veredicto */}
      <div className="rounded-xl p-4" style={{ background: "var(--surface-hover)", border: "1px solid var(--border-subtle)" }}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <h3 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
              {t("productor.verdict.title")}
            </h3>
            <p className="mt-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
              {t("productor.verdict.subtitle")}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            <span
              className="rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em]"
              style={{
                background: verdict.needs_mix ? "rgba(251, 191, 36, 0.15)" : "rgba(48, 209, 88, 0.15)",
                color: verdict.needs_mix ? "#fbbf24" : OK_COLOR,
                border: verdict.needs_mix ? "1px solid rgba(251, 191, 36, 0.3)" : "1px solid rgba(48, 209, 88, 0.3)",
              }}
            >
              {t("productor.verdict.needsMix")}: {verdict.needs_mix ? t("productor.verdict.yes") : t("productor.verdict.no")}
            </span>
            <span
              className="rounded-full px-2.5 py-0.5 text-[10px] font-bold"
              style={{
                background: "var(--accent-primary)",
                color: "white",
                opacity: 0.9,
              }}
            >
              {t("productor.verdict.confidence")}: {Math.round(verdict.confidence * 100)}%
            </span>
          </div>
        </div>

        <div className="mt-3 pt-3 border-t" style={{ borderColor: "var(--border-subtle)" }}>
          <p className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
            {t("productor.verdict.reasoning.raw_mix_detected")}:{" "}
            <span style={{ color: "var(--text-primary)" }}>{reasoningLabel}</span>
          </p>
        </div>
      </div>

      {/* Carencias */}
      {verdict.deficiencies.length > 0 && (
        <section className="space-y-2">
          <h4 className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{ color: "var(--text-secondary)" }}>
            {t("productor.verdict.deficienciesTitle")}
          </h4>
          <div className="flex flex-wrap gap-2">
            {verdict.deficiencies.map((def) => (
              <DeficiencyChip key={`${def.band_hz}-${def.direction}`} def={def} />
            ))}
          </div>
        </section>
      )}

      {verdict.deficiencies.length === 0 && (
        <p className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ background: "var(--surface-hover)", color: "var(--text-muted)" }}>
          {t("productor.verdict.deficienciesNone")}
        </p>
      )}

      {/* Selector de ruta — Radio group estilo tarjetas */}
      <section className="space-y-2">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{ color: "var(--text-secondary)" }}>
          {t("productor.verdict.title")}
        </h4>
        <div className="space-y-2" role="radiogroup" aria-label={t("productor.verdict.title")}>
          {verdict.routes.map((route) => (
            <RouteCard
              key={route.id}
              route={route}
              isSelected={selectedRoute === route.id}
              onSelect={() => onRouteChange(route.id as "auto" | "mix_then_master" | "master_only")}
              t={t}
              disabled={disabled}
            />
          ))}
        </div>
      </section>

      {/* Botones de acción */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold
            transition-colors duration-300 hover:border-[var(--border-hover)]"
          style={{
            background: "var(--surface-hover)",
            borderColor: "var(--border-subtle)",
            color: "var(--text-secondary)",
          }}
          disabled={disabled}
        >
          <XCircle size={13} />
          {t("common.cancel")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="ml-auto flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white
            transition-all duration-300 hover:brightness-110
            disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            background: "linear-gradient(135deg, #10b981, #00d4aa)",
            boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)",
          }}
          disabled={disabled}
        >
          <Sparkles size={16} />
          {t("productor.verdict.confirmButton")}
        </button>
      </div>
    </motion.div>
  );
}

function DeficiencyChip({ def }: { def: Deficiency }) {
  const isLacks = def.direction === "lacks";
  const label = isLacks
    ? `${def.band_hz} Hz: falta ${Math.abs(def.delta_db).toFixed(1)} dB`
    : `${def.band_hz} Hz: exceso ${Math.abs(def.delta_db).toFixed(1)} dB`;

  return (
    <span
      className="rounded-full px-2.5 py-1 text-[11px] font-medium"
      style={{
        background: isLacks ? "rgba(251, 191, 36, 0.12)" : "rgba(244, 63, 94, 0.12)",
        color: isLacks ? "#fbbf24" : "#f43f5e",
        border: isLacks ? "1px solid rgba(251, 191, 36, 0.3)" : "1px solid rgba(244, 63, 94, 0.3)",
      }}
    >
      {label}
    </span>
  );
}

function RouteCard({
  route,
  isSelected,
  onSelect,
  t,
  disabled,
}: {
  route: Route;
  isSelected: boolean;
  onSelect: () => void;
  t: (k: string) => string;
  disabled?: boolean;
}) {

  return (
    <label
      className={`relative flex items-start gap-3 rounded-xl p-3 transition-all duration-300 cursor-pointer ${
        isSelected ? "ring-2" : "hover:border-[var(--border-hover)]"
      }`}
      style={{
        background: "var(--surface-hover)",
        borderColor: isSelected ? "var(--accent-primary)" : "var(--border-subtle)",
        borderWidth: isSelected ? 2 : 1,
        opacity: disabled ? 0.5 : 1,
        pointerEvents: disabled ? "none" : "auto",
      }}
    >
      <input
        type="radio"
        checked={isSelected}
        onChange={onSelect}
        disabled={disabled}
        className="mt-0.5 shrink-0"
        style={{
          accentColor: "var(--accent-primary)",
          width: 18,
          height: 18,
        }}
      />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          {route.id === "mix_then_master" ? t("productor.verdict.routeMixThenMaster") : t("productor.verdict.routeMasterOnly")}
        </p>
        <p className="mt-0.5 text-[11px] leading-snug" style={{ color: "var(--text-secondary)" }}>
          {route.id === "mix_then_master" ? t("productor.verdict.routeMixThenMasterDesc") : t("productor.verdict.routeMasterOnlyDesc")}
        </p>
        {route.recommended && (
          <span className="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em]"
            style={{ background: "rgba(16, 185, 129, 0.15)", color: OK_COLOR, border: "1px solid rgba(16, 185, 129, 0.3)" }}>
            <Info size={10} />
            {t("productor.verdict.routeAutoDesc")}
          </span>
        )}
      </div>
    </label>
  );
}

/* ────────────────── Vista de resultado (legacy) ────────────────── */

function AgentResultView({ result }: { result: AgentRunResult }) {
  const { t } = useTranslation();

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
      className="mt-4 space-y-4"
    >
      {result.diagnosis && (
        <section>
          <SectionTitle>{t("productor.diagnosisTitle")}</SectionTitle>
          <blockquote
            className="rounded-xl px-3.5 py-2.5 text-sm leading-relaxed"
            style={{
              background: "var(--surface-hover)",
              borderLeft: "2px solid var(--accent-primary)",
              color: "var(--text-primary)",
            }}
          >
            {result.diagnosis}
          </blockquote>
        </section>
      )}

      <AgentNarrative items={result.narrative} />

      {/* Las pistas sólo aparecen si la corrida realmente separó audio: la
          narrativa es la prueba de que la herramienta corrió, no la existencia
          de un archivo. Un master directo no tiene nada que mostrar acá. */}
      {result.session_id &&
        result.narrative?.some((item) => item.code === "separated") && (
          <section>
            <SectionTitle>{t("productor.stemsTitle")}</SectionTitle>
            <AgentStemStack sessionId={result.session_id} />
          </section>
        )}

      <section>
        <SectionTitle>{t("productor.toolsTitle")}</SectionTitle>
        {result.tools_executed.length === 0 ? (
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            {t("productor.toolsEmpty")}
          </p>
        ) : (
          <ol className="space-y-1.5">
            {result.tools_executed.map((tool, i) => (
              <ToolRow key={`${i}-${tool.tool}`} index={i + 1} tool={tool} />
            ))}
          </ol>
        )}
      </section>

      <AgentMetrics result={result} />
      <AgentChangeReportView block={result.change_report} />
      <AgentAudio
        audio={result.audio}
        sessionId={result.session_id}
        masterSource={result.master_metrics?.source ?? null}
      />
    </motion.div>
  );
}

/* ────────────────── Narrativa del productor ────────────────── */

/** Severity → the colour of the item's left rule. */
const SEVERITY_COLOR: Record<AgentNarrativeItem["severity"], string> = {
  info: "var(--border-strong)",
  success: OK_COLOR,
  warning: "var(--accent-warning)",
  error: "var(--accent-error)",
};

/** What the agent did to the audio, in order, in the producer's language.
 *
 *  The sentence itself lives in `narrativeText.ts`, where it is pure and can be
 *  pinned by a test without mounting a component. */
function AgentNarrative({ items }: { items?: AgentNarrativeItem[] }) {
  const { t } = useTranslation();

  if (!items || items.length === 0) return null;

  return (
    <section>
      <SectionTitle>{t("productor.narrativeTitle")}</SectionTitle>
      <ol className="space-y-1.5">
        {items.map((item, i) => (
          <li
            key={`${i}-${item.code}`}
            className="py-0.5 pl-2.5 text-xs leading-relaxed"
            style={{
              borderLeft: `2px solid ${SEVERITY_COLOR[item.severity]}`,
              color: "var(--text-primary)",
            }}
          >
            {narrativeSentence(t, item)}
          </li>
        ))}
      </ol>
    </section>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3
      className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em]"
      style={{ color: "var(--text-secondary)" }}
    >
      {children}
    </h3>
  );
}

function ToolRow({
  index,
  tool,
}: {
  index: number;
  tool: AgentToolExecution;
}) {
  const { t } = useTranslation();
  const Icon = tool.ok ? CheckCircle2 : XCircle;

  return (
    <li
      className="flex items-start gap-2 rounded-lg px-2.5 py-1.5"
      style={{ background: "var(--surface-hover)" }}
    >
      <Icon
        size={13}
        className="mt-0.5 shrink-0"
        style={{ color: tool.ok ? OK_COLOR : "var(--accent-error)" }}
      />
      <div className="min-w-0">
        <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
          <span style={{ color: "var(--text-muted)" }}>{index}.</span>{" "}
          {t(`productor.tools.${tool.tool}`, tool.tool)}
        </p>
        {/* The successful `detail` is model-facing text: it carries absolute
            server paths and never the user's language. The narrative above is
            what explains a step; this row is the evidence that it ran. A
            failure still shows its error, because the user has to know what
            broke. */}
        {!tool.ok && (
          <p
            className="text-[11px] leading-snug break-words"
            style={{ color: "var(--text-secondary)" }}
          >
            {tool.error ?? tool.detail}
          </p>
        )}
      </div>
    </li>
  );
}

function AgentMetrics({ result }: { result: AgentRunResult }) {
  const { t } = useTranslation();
  const cells: { label: string; value: string }[] = [];

  const master = result.master_metrics;
  if (master) {
    if (typeof master.integrated_lufs === "number") {
      cells.push({
        label: t("productor.lufs"),
        value: `${master.integrated_lufs.toFixed(1)} LUFS`,
      });
    }
    if (typeof master.true_peak_db === "number") {
      cells.push({
        label: t("productor.truePeak"),
        value: `${master.true_peak_db.toFixed(1)} dBTP`,
      });
    }
    if (typeof master.crest_factor_db === "number") {
      cells.push({
        label: t("productor.crest"),
        value: `${master.crest_factor_db.toFixed(1)} dB`,
      });
    }
    if (typeof master.lra === "number") {
      cells.push({ label: t("productor.lra"), value: `${master.lra.toFixed(1)} LU` });
    }
  }

  const mix = result.mix_metrics;
  if (mix) {
    if (typeof mix.tempo_bpm === "number") {
      cells.push({ label: "BPM", value: String(Math.round(mix.tempo_bpm)) });
    }
    if (mix.genre) {
      cells.push({ label: t("productor.genre"), value: genreDisplayLabel(mix.genre) });
    }
  }

  cells.push({
    label: t("productor.iterations"),
    value: String(result.iterations),
  });

  return (
    <section>
      <SectionTitle>{t("productor.metricsTitle")}</SectionTitle>
      {cells.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("productor.metricsEmpty")}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {cells.map((cell) => (
            <span
              key={cell.label}
              className="rounded-full px-3 py-1 text-xs font-semibold"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
                color: "var(--text-primary)",
              }}
            >
              {cell.value}{" "}
              <span
                className="text-[10px] font-medium normal-case"
                style={{ color: "var(--text-muted)" }}
              >
                {cell.label}
              </span>
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

/** Ancho de barra al 100 %: los deltas reales superan los 30 dB en material
 *  sintético, así que la barra satura y el número es el que manda. */
const BAND_DELTA_FULL_SCALE_DB = 12;

const CHANGE_REPORT_STATUS_KEY: Record<
  Exclude<AgentChangeReport["status"], "ready">,
  string
> = {
  no_before: "productor.changeReport.noBefore",
  no_after: "productor.changeReport.noAfter",
  error: "productor.changeReport.error",
};

/** Centro de banda legible: 60 → "60 Hz", 1000 → "1 kHz". */
function formatBand(hz: number): string {
  return hz >= 1000 ? `${hz / 1000} kHz` : `${hz} Hz`;
}

/** Antes/después de la corrida, con las mismas métricas en los dos lados.
 *
 *  El backend degrada en vez de fallar: un reporte que no se pudo medir llega
 *  con `status !== "ready"` y su motivo. Se muestra el motivo, nunca se
 *  esconde la sección. */
function AgentChangeReportView({
  block,
}: {
  block?: AgentChangeReportBlock | null;
}) {
  const { t } = useTranslation();

  if (!block) return null;
  const report = block.report;

  if (report.status !== "ready") {
    return (
      <section>
        <SectionTitle>{t("productor.changeReportTitle")}</SectionTitle>
        <p
          className="flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-relaxed"
          style={{
            background: "var(--surface-hover)",
            color: "var(--text-secondary)",
          }}
          role="status"
        >
          <Info size={13} className="mt-0.5 shrink-0" />
          <span>{report.message ?? t(CHANGE_REPORT_STATUS_KEY[report.status])}</span>
        </p>
      </section>
    );
  }

  const bands = report.before_bands_hz.map((hz, i) => ({
    hz,
    delta: report.band_deltas_db[i] ?? 0,
  }));

  return (
    <section>
      <SectionTitle>{t("productor.changeReportTitle")}</SectionTitle>

      <div className="flex flex-wrap items-center gap-2">
        <DeltaPill
          label={t("productor.lufs")}
          before={report.before_integrated_lufs}
          after={report.after_integrated_lufs}
          delta={report.lufs_delta_db}
          unit="LUFS"
        />
        <DeltaPill
          label={t("productor.truePeak")}
          before={report.before_true_peak_db}
          after={report.after_true_peak_db}
          delta={report.true_peak_delta_db}
          unit="dBTP"
        />
      </div>

      {bands.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {bands.map(({ hz, delta }) => {
            const width =
              Math.min(Math.abs(delta) / BAND_DELTA_FULL_SCALE_DB, 1) * 50;
            const up = delta >= 0;
            return (
              <li key={hz} className="flex items-center gap-2 text-[10px]">
                <span
                  className="w-12 shrink-0 text-right font-mono"
                  style={{ color: "var(--text-muted)" }}
                >
                  {formatBand(hz)}
                </span>
                <span
                  className="relative h-1.5 flex-1 overflow-hidden rounded-full"
                  style={{ background: "var(--surface-hover)" }}
                >
                  <span
                    className="absolute inset-y-0"
                    style={{
                      left: up ? "50%" : `${50 - width}%`,
                      width: `${width}%`,
                      background: up ? OK_COLOR : "var(--accent-error)",
                    }}
                  />
                  <span
                    className="absolute inset-y-0 left-1/2 w-px"
                    style={{ background: "var(--border-strong)" }}
                  />
                </span>
                <span
                  className="w-16 shrink-0 text-right font-mono"
                  style={{ color: up ? OK_COLOR : "var(--accent-error)" }}
                >
                  {up ? "+" : ""}
                  {delta.toFixed(1)} dB
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--text-muted)" }}>
        {t("productor.changeReportBandsHint", {
          standard: report.loudness_standard,
        })}
      </p>

      {!block.durable && block.note && (
        <p
          className="mt-1.5 text-[10px] leading-snug"
          style={{ color: "var(--text-muted)" }}
        >
          {block.note}
        </p>
      )}
    </section>
  );
}

function DeltaPill({
  label,
  before,
  after,
  delta,
  unit,
}: {
  label: string;
  before: number | null;
  after: number | null;
  delta: number | null;
  unit: string;
}) {
  if (before === null || after === null) return null;
  const up = (delta ?? 0) >= 0;

  return (
    <span
      className="rounded-full px-3 py-1 text-xs font-semibold"
      style={{
        background: "var(--bg-elevated)",
        border: "1px solid var(--border-subtle)",
        color: "var(--text-primary)",
      }}
    >
      <span className="font-mono">
        {before.toFixed(1)} → {after.toFixed(1)}
      </span>{" "}
      <span
        className="text-[10px] font-medium normal-case"
        style={{ color: "var(--text-muted)" }}
      >
        {unit} {label}
      </span>
      {delta !== null && (
        <>
          {" "}
          <span
            className="text-[10px] font-bold"
            style={{ color: up ? OK_COLOR : "var(--accent-error)" }}
          >
            {up ? "+" : ""}
            {delta.toFixed(1)} dB
          </span>
        </>
      )}
    </span>
  );
}

/** Reproducción A/B de la corrida.
 *
 *  Con máster entregado el A/B compara la ENTRADA REAL del motor con su
 *  salida: la mezcla en `mix_then_master`, el original en `master_only`
 *  (`master_metrics.source` lo dice). Sin máster reproducible cae a los
 *  reproductores sueltos de siempre. */
function AgentAudio({
  audio,
  sessionId,
  masterSource,
}: {
  audio: AgentRunResult["audio"];
  sessionId: string;
  masterSource: "mix" | "original" | null;
}) {
  const { t } = useTranslation();

  const masterAsset = audio.master;
  const mixAsset = audio.mix;
  const delivered = masterAsset ?? mixAsset;

  const playable = [
    { kind: "master" as const, asset: masterAsset },
    { kind: "mix" as const, asset: mixAsset },
  ].filter(
    (item): item is { kind: "master" | "mix"; asset: AgentAudioAsset } =>
      Boolean(item.asset?.url),
  );

  // `source` ausente en corridas viejas: el lado A por defecto es la mezcla,
  // que es lo que el motor masterizó en el camino histórico.
  const compareFromMix = masterSource !== "original";
  const beforeUrl = compareFromMix
    ? (mixAsset?.url ?? getMixAudioUrl(sessionId))
    : getAudioUrl(sessionId, "original");

  return (
    <section>
      <SectionTitle>{t("productor.audioTitle")}</SectionTitle>

      {!delivered ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("productor.audioEmpty")}
        </p>
      ) : masterAsset?.url ? (
        <div className="pb-2">
          <MixWaveformAB
            originalUrl={beforeUrl}
            mixedUrl={masterAsset.url}
            originalLabel={
              compareFromMix
                ? t("productor.audioMix")
                : t("productor.audioOriginal")
            }
            mixedLabel={t("productor.audioMaster")}
          />
        </div>
      ) : playable.length === 0 ? (
        <p
          className="flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-relaxed"
          style={{ background: "var(--surface-hover)", color: "var(--accent-warning)" }}
          role="status"
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{delivered.note ?? t("productor.audioEphemeral")}</span>
        </p>
      ) : (
        <div className="space-y-2 pb-2">
          {playable.map(({ kind, asset }) => (
            <div key={kind}>
              <p className="text-[10px] font-semibold" style={{ color: "var(--text-muted)" }}>
                {kind === "master" ? t("productor.audioMaster") : t("productor.audioMix")}
              </p>
              <audio
                controls
                preload="none"
                src={asset.url ?? undefined}
                aria-label={
                  kind === "master" ? t("productor.audioMaster") : t("productor.audioMix")
                }
                className="mt-0.5 w-full"
                style={{ colorScheme: "dark" }}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}