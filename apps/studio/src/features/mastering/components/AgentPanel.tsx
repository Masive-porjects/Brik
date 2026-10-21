"use client";

import { motion } from "framer-motion";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Loader2,
  Sparkles,
  XCircle,
  Info,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getAgentJobStatus,
  submitAgentAnalyzeJob,
  submitAgentJob,
  type AgentAudioAsset,
  type AgentRunResult,
  type AgentToolExecution,
  type AudioVerdict,
  type Deficiency,
  type Route,
} from "@/lib/api";
import { genreDisplayLabel } from "@/lib/audioUtils";
import { useTranslation } from "@/i18n";

/**
 * Módulo Brik — Capa de decisión interactiva (T6).
 *
 * Flujo de dos fases:
 *  1. Job de ANÁLISIS (POST /jobs/agent/{id}/analyze) — solo fase 1, ~3s.
 *     Devuelve el veredicto de Brik (AudioVerdict) con carencias y rutas.
 *  2. El usuario elige una ruta (Auto / Separar y mezclar / Solo master).
 *  3. Job COMPLETO (POST /jobs/agent/{id}) con `decision` — Demucs + mix + master
 *     si la ruta lo requiere.
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

/** Estados internos del flujo de decisión. */
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

export default function AgentPanel({
  sessionId,
  disabled,
  compact = false,
  onPhaseChange,
}: AgentPanelProps) {
  const { t } = useTranslation();

  const [prompt, setPrompt] = useState("");
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

  /** Paso 1 — Lanza el job de análisis y espera el veredicto. */
  const handleAnalyze = useCallback(async () => {
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

    setPhase("analyzing");
    setAnalysisError(null);
    setVerdict(null);

    try {
      const accepted = await submitAgentAnalyzeJob(sessionId, prompt, controller.signal);

      let terminal = false;
      while (!terminal) {
        await sleep(AGENT_POLL_MS, pollController.signal);
        const state = await getAgentJobStatus(accepted.job_id, pollController.signal);
        if (state.status === "completed") {
          terminal = true;
          clearWatchdog();
          if (state.result?.verdict) {
            setVerdict(state.result.verdict);
            setPhase("verdict");
            // Preseleccionar la ruta recomendada por defecto
            const rec = state.result.verdict.recommended_path;
            setSelectedRoute(rec === "master_only" ? "master_only" : "mix_then_master");
          } else {
            setAnalysisError(t("productor.verdict.analysisFailed"));
            setPhase("error");
          }
        } else if (state.status === "error") {
          terminal = true;
          clearWatchdog();
          setAnalysisError(state.error ?? t("productor.interrupted"));
          setPhase("error");
        }
      }
    } catch (e) {
      const isAbort = (e as { name?: string })?.name === "AbortError";
      if (isAbort && timedOutRef.current) {
        setAnalysisError(t("productor.timeout"));
      } else if (isAbort) {
        setCancelled(true);
      } else {
        setAnalysisError(e instanceof Error ? e.message : t("productor.verdict.analysisFailed"));
      }
      setPhase("error");
    } finally {
      clearWatchdog();
      if (abortRef.current === controller) abortRef.current = null;
      if (pollAbortRef.current === pollController) pollAbortRef.current = null;
    }
  }, [sessionId, prompt, clearWatchdog, t]);

  /** Paso 3 — Lanza el job completo con la decisión elegida. */
  const handleProduceWithDecision = useCallback(async () => {
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
        selectedRoute,
        controller.signal,
      );

      let terminal = false;
      while (!terminal) {
        await sleep(AGENT_POLL_MS, pollController.signal);
        const state = await getAgentJobStatus(accepted.job_id, pollController.signal);
        if (state.status === "completed") {
          terminal = true;
          clearWatchdog();
          if (state.result) setResult(state.result);
          else setError(t("productor.emptyResult"));
          setPhase("completed");
        } else if (state.status === "error") {
          terminal = true;
          clearWatchdog();
          setError(state.error ?? t("productor.interrupted"));
          setPhase("error");
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
  }, [sessionId, prompt, selectedRoute, clearWatchdog, t]);

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

  // Composer = prompt + acción primaria. En el rail queda anclado abajo
  // (footer sticky sobre el cuerpo scrolleable); inline va arriba, como antes.
  const composer = (
    <div
      className={compact ? "shrink-0 border-t px-4 py-3" : "px-4 pt-3"}
      style={compact ? { borderColor: "var(--border-subtle)" } : undefined}
    >
      <label
        htmlFor="agent-prompt"
        className="text-[10px] font-bold uppercase tracking-[0.16em]"
        style={{ color: "var(--text-secondary)" }}
      >
        {t("productor.promptLabel")}
      </label>
      <textarea
        id="agent-prompt"
        value={prompt}
        onChange={(e) => setPrompt(e.currentTarget.value)}
        disabled={isRunning || disabled}
        rows={2}
        placeholder={t("productor.promptPlaceholder")}
        className="mt-1 w-full resize-none rounded-xl border px-3 py-2 text-sm outline-none
          transition-colors duration-300 focus:border-[var(--accent-primary)]
          disabled:opacity-40"
        style={{
          background: "var(--surface-hover)",
          borderColor: "var(--border-subtle)",
          color: "var(--text-primary)",
        }}
      />
      <p className="mt-1 text-[10px]" style={{ color: "var(--text-muted)" }}>
        {t("productor.promptHint")}
      </p>

      <div className="mt-2 flex items-center gap-2">
        {isRunning ? (
          <span
            className="text-xs font-medium"
            style={{ color: "var(--text-secondary)" }}
          >
            {phase === "analyzing"
              ? t("productor.verdict.analyzing")
              : t("productor.runningShort")}
          </span>
        ) : phase === "verdict" ? (
          <p className="text-[10px] leading-snug" style={{ color: "var(--text-muted)" }}>
            {t("productor.composerVerdictHint")}
          </p>
        ) : (
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={disabled}
            className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white
              transition-all duration-300 hover:brightness-110
              disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              background: "linear-gradient(135deg, #10b981, #00d4aa)",
              boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)",
            }}
          >
            <Sparkles size={16} />
            {phase === "completed" ? t("productor.restart") : t("productor.start")}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div
      className={compact ? "flex h-full min-h-0 w-full flex-col" : "w-full"}
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
          <div className="mt-3 flex items-center gap-2">
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
          </div>
        )}

        {cancelled && (
          <p
            className="mt-3 rounded-lg px-3 py-2 text-xs leading-relaxed"
            style={{ background: "var(--surface-hover)", color: "var(--text-secondary)" }}
            role="status"
          >
            {t("productor.cancelled")}
          </p>
        )}

        {(analysisError || error) && (
          <p
            className="mt-3 rounded-lg px-3 py-2 text-xs leading-relaxed"
            style={{ background: "var(--surface-hover)", color: "var(--accent-error)" }}
            role="alert"
          >
            {analysisError ?? error}
          </p>
        )}

        {phase === "completed" && result && <AgentResultView result={result} />}
      </div>

      {compact && composer}
    </div>
  );
}

/* ────────────────── Tarjeta de Veredicto ────────────────── */

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

/* ────────────────── Vista de resultado (sin cambios, solo import) ────────────────── */

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
      <AgentAudio audio={result.audio} />
    </motion.div>
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
        <p
          className="text-[11px] leading-snug break-words"
          style={{ color: "var(--text-secondary)" }}
        >
          {tool.ok ? tool.detail : (tool.error ?? tool.detail)}
        </p>
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

function AgentAudio({ audio }: { audio: AgentRunResult["audio"] }) {
  const { t } = useTranslation();

  const playable = [
    { kind: "master" as const, asset: audio.master },
    { kind: "mix" as const, asset: audio.mix },
  ].filter(
    (item): item is { kind: "master" | "mix"; asset: AgentAudioAsset } =>
      Boolean(item.asset?.url),
  );

  const delivered = audio.master ?? audio.mix;

  return (
    <section>
      <SectionTitle>{t("productor.audioTitle")}</SectionTitle>

      {!delivered ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("productor.audioEmpty")}
        </p>
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