"use client";

import { motion } from "framer-motion";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Loader2,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  getAgentJobStatus,
  submitAgentJob,
  type AgentAudioAsset,
  type AgentRunResult,
  type AgentToolExecution,
} from "@/lib/api";
import { genreDisplayLabel } from "@/lib/audioUtils";
import { useTranslation } from "@/i18n";

/**
 * Módulo Productor IA.
 *
 * Es la cara del bucle agéntico del backend (``agentic_loop.run``): el usuario
 * escribe qué quiere, el agente separa stems, mezcla, mide el bus y masteriza
 * por su cuenta. El panel NO ejecuta DSP ni interpreta la intención: encola el
 * job, espera y muestra lo que el backend registró.
 *
 * Esa separación es deliberada. El diagnóstico, la lista de herramientas y las
 * métricas vienen del ``tool_log`` real del loop, no se deducen de un archivo
 * que exista en disco: "se separaron los stems" es cierto porque la herramienta
 * corrió, no porque haya un stem.
 */

/* ── Módulo: tokens semánticos de globals.css (dark por defecto,
   light con html[data-theme="light"]). ─────────────────────── */

const CARD_STYLE: React.CSSProperties = {
  // position: relative ancla overlays internos del módulo.
  position: "relative",
  // Vidrio flotante: el módulo flota sobre el canvas, no es una tarjeta.
  background: "var(--bg-glass)",
  backdropFilter: "blur(16px)",
  WebkitBackdropFilter: "blur(16px)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "1rem",
  boxShadow: "var(--shadow-card)",
};

/** Intervalo de polling. El backend reporta el estado real del job, así que
 *  cada tick es un dato verdadero y no una interpolación. */
const AGENT_POLL_MS = 2_000;

/** Deja de preguntar después de esto. El trabajo SIGUE corriendo del lado del
 *  servidor, así que el mensaje lo dice en vez de fingir un fallo. Un run es
 *  Demucs + la cadena de mezcla + N turnos del modelo: 30 min es holgado. */
const AGENT_TIMEOUT_MS = 1_800_000;

/** Verde de acción del repo (mismo que la pill de MixPanel). */
const OK_COLOR = "#30d158";

interface AgentPanelProps {
  sessionId: string | null;
  disabled?: boolean;
}

/**
 * Panel del Productor IA: prompt, espera y resultado.
 *
 * Renderiza SOLO lo que el backend midió. Una métrica ausente no se dibuja:
 * nunca se rellena con un cero que el agente no midió.
 */
export default function AgentPanel({ sessionId, disabled }: AgentPanelProps) {
  const { t } = useTranslation();

  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AgentRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  // Controller del polling, aparte del submit: cancelar tiene que abortar las
  // DOS requests, no solo la que ya terminó.
  const pollAbortRef = useRef<AbortController | null>(null);
  // Watchdog del submit + polling. ``timedOutRef`` distingue el timeout del
  // cancel explícito del usuario (ambos llegan como AbortError).
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timedOutRef = useRef(false);

  // Limpia al desmontar: sin esto, un run en vuelo seguiría golpeando el
  // backend y haría setState sobre un componente desmontado.
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

  const handleProduce = useCallback(async () => {
    if (!sessionId || running) return;
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

    setRunning(true);
    setError(null);
    setCancelled(false);
    // Run nuevo: el resultado anterior ya no describe lo que está corriendo.
    setResult(null);

    try {
      // Paso 1 — submit: 202 + job_id en milisegundos. El run tarda minutos,
      // así que la conexión no lo espera (eso es lo que el edge corta con
      // 502/504). Un 503 acá significa que falta la credencial del modelo.
      const accepted = await submitAgentJob(sessionId, prompt, controller.signal);

      // Paso 2 — polling. ``progress`` queda en 0 hasta el final: el loop no
      // expone fase, así que mostramos un estado indeterminado en vez de una
      // barra que mienta.
      let terminal = false;
      while (!terminal) {
        await sleep(AGENT_POLL_MS, pollController.signal);
        const state = await getAgentJobStatus(
          accepted.job_id,
          pollController.signal,
        );
        if (state.status === "completed") {
          terminal = true;
          clearWatchdog();
          if (state.result) setResult(state.result);
          else setError(t("productor.emptyResult"));
        } else if (state.status === "error") {
          terminal = true;
          clearWatchdog();
          setError(state.error ?? t("productor.interrupted"));
        }
      }
    } catch (e) {
      const isAbort = (e as { name?: string })?.name === "AbortError";
      if (isAbort && timedOutRef.current) {
        setError(t("productor.timeout"));
      } else if (isAbort) {
        // Cancelación explícita: estado informativo, NO un fallo. El backend
        // puede seguir procesando; solo dejamos de esperar.
        setCancelled(true);
      } else {
        setError(e instanceof Error ? e.message : t("productor.failed"));
      }
    } finally {
      clearWatchdog();
      if (abortRef.current === controller) abortRef.current = null;
      if (pollAbortRef.current === pollController) pollAbortRef.current = null;
      setRunning(false);
    }
  }, [sessionId, running, prompt, clearWatchdog, t]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    pollAbortRef.current?.abort();
  }, []);

  if (!sessionId) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        {t("productor.loadAudioPrompt")}
      </p>
    );
  }

  return (
    <div className="w-full" style={CARD_STYLE}>
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

      <div className="px-4 pt-3 pb-4">
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
          disabled={running || disabled}
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

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleProduce}
            disabled={disabled || running}
            className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white
              transition-all duration-300 hover:brightness-110
              disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              background: "linear-gradient(135deg, #10b981, #00d4aa)",
              boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)",
            }}
          >
            {running ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                {t("productor.runningShort")}
              </>
            ) : (
              <>
                <Sparkles size={16} />
                {t("productor.start")}
              </>
            )}
          </button>

          {running && (
            <button
              type="button"
              onClick={handleCancel}
              className="flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold
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
          )}
        </div>

        {running && (
          <p
            className="mt-3 flex items-start gap-2 text-xs leading-relaxed"
            style={{ color: "var(--text-secondary)" }}
            role="status"
            aria-live="polite"
          >
            <Loader2 size={13} className="mt-0.5 shrink-0 animate-spin" />
            <span>{t("productor.running")}</span>
          </p>
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

        {error && (
          <p
            className="mt-3 rounded-lg px-3 py-2 text-xs leading-relaxed"
            style={{ background: "var(--surface-hover)", color: "var(--accent-error)" }}
            role="alert"
          >
            {error}
          </p>
        )}

        {result && <AgentResultView result={result} />}
      </div>
    </div>
  );
}

/* ── Resultado ───────────────────────────────────────────── */

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

/** Una herramienta ejecutada, en el orden real del run.
 *
 *  El nombre técnico (``trigger_stem_separation``) se traduce para la UI y
 *  cae al nombre crudo cuando es una herramienta que el frontend no conoce:
 *  mejor un identificador feo que una etiqueta inventada. */
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

/** Métricas del run, en celdas.
 *
 *  Igual que ``MixAnalysisGrid``: solo se dibuja un campo cuando el backend lo
 *  midió. ``master_metrics`` viene del payload de ``send_to_master`` y
 *  ``mix_metrics`` de ``bus_metrics`` — ninguna celda se rellena a mano. */
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

/** Audio entregado por el agente.
 *
 *  La URL la re-firma el backend en cada lectura del job, así que acá solo se
 *  reproduce la que vino en el payload. Sin R2 configurado el asset degrada a
 *  ``local_path`` (efímero): en ese caso se avisa en vez de mostrar un player
 *  que va a dar 404 después de un redeploy. */
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
        <div className="space-y-2">
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
