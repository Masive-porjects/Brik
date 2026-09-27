"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Download,
  Eye,
  EyeOff,
  Info,
  Loader2,
  Music2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import {
  getAudioUrl,
  getMixAudioUrl,
  mixTracks,
  type MixResult,
} from "@/lib/api";
import { genreDisplayLabel } from "@/lib/audioUtils";
import MixWaveformAB from "@/presentation/components/MixWaveformAB";
import MixStatusStream from "@/presentation/components/MixStatusStream";
import { MIX_STATUS_STAGES } from "@/presentation/components/mixI18n";

/* ── Módulo: tokens semánticos de globals.css (dark por defecto,
   light con html[data-theme="light"]). Los acentos de marca (verde
   #00d4aa/#10b981, rojo de error, gradiente del ring) quedan fijos:
   funcionan en ambos temas. ──────────────────────────────── */

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

interface MixPanelProps {
  sessionId: string | null;
  /** ``session.mix_path`` de una sesión recargada con mix ya generado. */
  sessionMixPath?: string | null;
  /** ``session.mix_analysis`` persistido (espejo del header X-Mix-Result). */
  sessionMixAnalysis?: MixResult | null;
  /** Duración del audio original en segundos (``session.analysis``). */
  audioDurationSeconds?: number | null;
  disabled?: boolean;
  /** ``session.analysis.detected_genre`` — alimenta el mini-panel IA. */
  genreHint?: string | null;
  /** ``hasMix`` del backend (``session.mix_status === "completed"``, T2):
   *  hay una mezcla ENTREGADA y masterizable. Etiqueta la tarjeta del
   *  resultado; el master usa el mismo booleano como ``source=mix``. */
  hasMix: boolean;
  /** Notifica que el POST /mix terminó (éxito o fallo) para que el padre
   *  relea la sesión y sincronice ``mix_status``. */
  onMixSettled?: () => void;
  /** Modo global Manual/Asistente IA (switch del navbar). Gobierna el
   *  mini-panel de recomendaciones IA del módulo. */
  mode: "manual" | "ai";
  /** Acción "Masterizar": carga la vista de mastering (tab "modules")
   *  para continuar el proceso. Habilitado solo con mix terminado. */
  onMasterize?: () => void;
}

/**
 * Etapas del progreso mientras corre el POST /mix (blocking).
 * Honestidad: la cadena DSP (``MIX_STATUS_STAGES``) es SIEMPRE cierta
 * (existe en ``mix_engine.build_mix``). El timing de cuándo se completa
 * cada etapa es simulado por el ticker de `stageMsForDuration` (igual que
 * la barra: cap 95 %, 100 % solo con la respuesta real).
 */

/**
 * Tiempo por etapa según la duración del audio. El backend es una sola
 * request blocking (sin progreso real), así que la UI camina por etapas
 * mientras el fetch está en vuelo:
 *   - ~1 min de audio  → ~7 s por etapa (≈42 s de recorrido) — pruebas
 *     locales rápidas.
 *   - ~3 min de audio  → ~15 s por etapa (≈90 s de recorrido) — cuando la
 *     infraestructura lo admita.
 * Interpola linealmente entre 60 s y 180 s y clampa fuera de ese rango.
 * El porcentaje NUNCA llega a 100 hasta que la promesa resuelve.
 */
function stageMsForDuration(audioDurationSeconds?: number | null): number {
  const clamped = Math.min(Math.max(audioDurationSeconds ?? 60, 60), 180);
  const t = (clamped - 60) / 120; // 0 (1 min) → 1 (3 min)
  return Math.round(7000 + t * 8000); // 7 s → 15 s
}

/** Formatea segundos como mm:ss (o segundos con decimal si es corto). */
function formatDuration(seconds: number): string {
  if (seconds >= 60) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  return `${seconds.toFixed(1)} s`;
}

/* ── Grilla de análisis (tokens semánticos) ──────────────
   Renderiza SOLO los campos presentes en el payload — nunca
   inventa datos que el backend no midió. */
function MixAnalysisGrid({ result }: { result: MixResult }) {
  const cells: { label: string; value: string }[] = [];

  if (typeof result.tempo_bpm === "number") {
    cells.push({ label: "BPM", value: String(Math.round(result.tempo_bpm)) });
  }
  if (typeof result.genre === "string" && result.genre && result.genre !== "other") {
    cells.push({ label: "Género", value: genreDisplayLabel(result.genre) });
  }
  if (typeof result.genre_confidence === "number") {
    cells.push({
      label: "Confianza",
      value: `${Math.round(result.genre_confidence * 100)}%`,
    });
  }
  if (typeof result.sample_rate === "number") {
    cells.push({ label: "Sample rate", value: `${result.sample_rate} Hz` });
  }
  if (typeof result.duration_seconds === "number") {
    cells.push({ label: "Duración", value: formatDuration(result.duration_seconds) });
  }

  const qc = result.qc_report as
    | { summary?: { all_ok?: boolean; flagged?: unknown[] } }
    | null
    | undefined;

  // T6 — celdas honestas de balance: SOLO cuando el payload las trae.
  // ``trim_report`` = faders manuales aplicados; ``balance_report`` = lo
  // que el auto-balance midió/corrigió. Nunca se inventan datos.
  const stemLabel: Record<string, string> = {
    drums_db: "Batería",
    bass_db: "Bajo",
    other_db: "Otros",
    vocals_db: "Voz",
  };
  const fmtGains = (gains?: Record<string, number>) =>
    (gains ? Object.entries(gains) : [])
      .filter(([, db]) => db !== 0)
      .map(
        ([key, db]) =>
          `${stemLabel[key] ?? key} ${db > 0 ? "+" : ""}${db.toFixed(1)} dB`,
      )
      .join(" · ");
  const trimReport = result.trim_report as
    | { gains?: Record<string, number> }
    | null
    | undefined;
  const balanceReport = result.balance_report as
    | { gains?: Record<string, number> }
    | null
    | undefined;
  const trimGainsText = fmtGains(trimReport?.gains);
  const balanceGainsText = fmtGains(balanceReport?.gains);
  if (trimGainsText) cells.push({ label: "Balance", value: trimGainsText });
  if (balanceGainsText)
    cells.push({ label: "Auto-balance", value: balanceGainsText });

  if (cells.length === 0 && !qc) return null;

  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--border-subtle)" }}>
      <p
        className="mb-2.5 text-[10px] font-bold uppercase tracking-[0.16em]"
        style={{ color: "var(--text-secondary)" }}
      >
        Análisis de la mezcla
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {cells.map((cell) => (
          <div key={cell.label} className="min-w-0 text-center">
            <p
              className="truncate font-mono text-sm font-semibold"
              style={{ color: "var(--text-primary)" }}
            >
              {cell.value}
            </p>
            <p
              className="mt-0.5 text-[9px] uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              {cell.label}
            </p>
          </div>
        ))}
        {qc && (
          <div
            className="flex min-w-0 items-center justify-center gap-1.5 text-sm font-semibold"
            style={{
              color: qc.summary?.all_ok === false ? "#b45309" : "#10b981",
            }}
            title={
              qc.summary?.all_ok === false &&
              Array.isArray(qc.summary.flagged) &&
              qc.summary.flagged.length > 0
                ? `Checks marcados: ${qc.summary.flagged.join(", ")}`
                : undefined
            }
          >
            <ShieldCheck size={13} />
            QC: {qc.summary?.all_ok === false ? "revisar" : "ok"}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Faders de Balance (T6) ────────────────────────────────
   Contrato del backend (T5): claves ``*_db`` de los 4 stems, rango
   ±6 dB, 0 = neutral (sin ``trim_report``). El valor mostrado se clampa
   a la banda y el estado se commitea AL SOLTAR el fader (el arrastre vive
   solo en el draft local — el mix lee faders commiteados). */
const STEM_FADERS: { key: string; label: string }[] = [
  { key: "drums_db", label: "Batería" },
  { key: "bass_db", label: "Bajo" },
  { key: "other_db", label: "Otros" },
  { key: "vocals_db", label: "Voz" },
];
const FADER_DEFAULTS: Record<string, number> = {
  drums_db: 0,
  bass_db: 0,
  other_db: 0,
  vocals_db: 0,
};
const FADER_BAND = 6.0;

/* ── Watchdog del POST /mix (T6) ────────────────────────────
   El Mix Engine es una request blocking: si el backend se cuelga, sin
   este watchdog la UI queda congelada en 95% para siempre. 600 s a
   propósito, alineado con ``PROCESS_TIMEOUT_MS`` de
   ``useMasteringWorkflow``: la mezcla nunca debe bloquear la UI más
   tiempo que el master. */
const MIX_TIMEOUT_MS = 600_000;

function FaderControl({
  label,
  value,
  disabled,
  onCommit,
}: {
  label: string;
  value: number;
  disabled: boolean;
  onCommit: (db: number) => void;
}) {
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? value;
  const clamp = Math.max(-FADER_BAND, Math.min(FADER_BAND, shown));
  const commit = useCallback(() => {
    if (draft !== null && draft !== value) onCommit(draft);
    setDraft(null);
  }, [draft, value, onCommit]);
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span
          className="truncate text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-secondary)" }}
        >
          {label}
        </span>
        <span
          className="font-mono text-[10px] font-semibold"
          style={{
            color: clamp === 0 ? "var(--text-muted)" : "var(--text-primary)",
          }}
        >
          {clamp === 0 ? "0 dB" : `${clamp > 0 ? "+" : ""}${clamp.toFixed(1)} dB`}
        </span>
      </div>
      <input
        type="range"
        min={-FADER_BAND}
        max={FADER_BAND}
        step={0.5}
        value={shown}
        disabled={disabled}
        aria-label={`${label} (dB)`}
        onChange={(e) => setDraft(Number(e.currentTarget.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className="mt-1 w-full"
      />
      <p className="mt-0.5 text-[9px]" style={{ color: "var(--text-muted)" }}>
        Rango ±6 dB
      </p>
    </div>
  );
}

export default function MixPanel({
  sessionId,
  sessionMixPath,
  sessionMixAnalysis,
  audioDurationSeconds,
  disabled,
  genreHint,
  hasMix,
  onMixSettled,
  mode,
  onMasterize,
}: MixPanelProps) {
  const [mixing, setMixing] = useState(false);
  const [mixUrl, setMixUrl] = useState<string | null>(null);
  const [mixResult, setMixResult] = useState<MixResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [progressStage, setProgressStage] = useState(0);
  const [progressPct, setProgressPct] = useState(0);
  // Sesión restaurada con mix ya hecho → el resultado se muestra al abrir;
  // la pill permite ocultarlo/mostrarlo.
  const [showResult, setShowResult] = useState(() => Boolean(sessionMixPath));
  // Valor previo de sessionMixPath para el ajuste en render (evita
  // setState-in-effect): cuando la sesión llega con mix ya generado DESPUÉS
  // del mount (restauración asíncrona), mostramos el resultado.
  const [prevSessionMixPath, setPrevSessionMixPath] = useState(sessionMixPath);
  // v6 — dimensión espacial (Delay + Reverb): elección POR MEZCLA, no
  // persistida. ON por defecto (comportamiento actual); OFF = routing
  // Paso 03 (el backend omite dimension_report y la etapa "dimension" no
  // aparece). Se deshabilita mientras corre el POST /mix.
  const [dimensionEnabled, setDimensionEnabled] = useState(true);
  // T6 — Balance: auto-balance opcional (default OFF = neutral) + faders
  // manuales por stem (±6 dB, contrato T1/T5). Elección POR MEZCLA, no
  // persistida. Se deshabilitan mientras corre el POST /mix.
  const [autoBalance, setAutoBalance] = useState(false);
  const [faderValues, setFaderValues] =
    useState<Record<string, number>>(FADER_DEFAULTS);

  const objectUrlRef = useRef<string | null>(null);
  const stageRef = useRef(0);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Watchdog del POST /mix: si el backend no responde en MIX_TIMEOUT_MS,
  // aborta el fetch en vuelo. ``timedOutRef`` distingue el timeout del
  // cancel explícito del usuario (ambos llegan como AbortError).
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timedOutRef = useRef(false);
  // Lista dinámica de etapas DSP (filtrada por dimensionEnabled) vista por
  // el ticker; se asigna en cada render para que el intervalo siempre use
  // la longitud actual sin re-crear el timer.
  const stagesRef = useRef<{ id: string; label: string }[]>([]);

  // Revoca el objectURL local al desmontar (el player lo usa hasta ese
  // momento, por eso NO se revoca en el finally de handleMix), limpia el
  // intervalo y el watchdog si se desmonta a mitad del mix y aborta el
  // fetch en vuelo.
  useEffect(() => {
    return () => {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
      abortRef.current?.abort();
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
    };
  }, []);

  // La sesión puede llegar con mix ya generado después del mount
  // (restauración asíncrona): ajuste de estado durante el render cuando
  // cambia sessionMixPath (patrón recomendado: nunca setState-in-effect).
  if (prevSessionMixPath !== sessionMixPath) {
    setPrevSessionMixPath(sessionMixPath);
    if (sessionMixPath) setShowResult(true);
  }

  const clearProgressTimer = useCallback(() => {
    if (progressIntervalRef.current) {
      clearInterval(progressIntervalRef.current);
      progressIntervalRef.current = null;
    }
  }, []);

  const handleMix = useCallback(async () => {
    if (!sessionId || mixing) return;
    // Re-mezcla: aborta un mix previo si quedó en vuelo.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Watchdog: si el backend se cuelga, el fetch se aborta solo en vez de
    // dejar la UI clavada en 95%. Se limpia en el success, en el catch y
    // en el finally para no disparar después de terminar.
    timedOutRef.current = false;
    if (watchdogRef.current) clearTimeout(watchdogRef.current);
    watchdogRef.current = setTimeout(() => {
      timedOutRef.current = true;
      controller.abort();
    }, MIX_TIMEOUT_MS);

    setMixing(true);
    setError(null);
    setCancelled(false);
    // Re-mezcla: ocultar el resultado previo mientras procesa.
    setShowResult(false);
    stageRef.current = 0;
    setProgressStage(0);
    setProgressPct(0);

    // Progreso por etapas simuladas: el POST /mix del backend es una sola
    // request blocking que devuelve el WAV completo; la UI avanza por etapas
    // mientras el fetch está en vuelo (timing según la duración del audio:
    // ~1 min → etapas de 7 s; ~3 min → etapas de 15 s). Las etapas son
    // MONÓTONAS y NO se repiten: cada tick completa una etapa más hasta la
    // última. El 100% solo llega con la respuesta real — nunca se marca
    // done antes.
    const stageMs = stageMsForDuration(audioDurationSeconds);
    progressIntervalRef.current = setInterval(() => {
      const total = stagesRef.current.length || 1;
      stageRef.current = Math.min(stageRef.current + 1, total - 1);
      setProgressStage(stageRef.current);
      // El % es MONÓTONO creciente por etapa completada: avanza una vez por
      // etapa, jamás retrocede y nunca llega a 95/100 sin la respuesta real.
      setProgressPct((prev) =>
        Math.min(
          95,
          Math.max(prev, Math.round(((stageRef.current + 1) / total) * 100)),
        ),
      );
    }, stageMs);

    try {
      const stemTrims = Object.fromEntries(
        Object.entries(faderValues).filter(([, db]) => db !== 0),
      );
      const { audioUrl, result } = await mixTracks(sessionId, {
        signal: controller.signal,
        dimensionEnabled,
        autoBalance,
        stemTrims,
      });
      clearProgressTimer();
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
      objectUrlRef.current = audioUrl;
      setProgressPct(100);
      setMixUrl(audioUrl);
      setMixResult(result);
      setShowResult(true);
      // El POST /mix ya publicó mix_status en el backend (T2): el padre
      // relee la sesión para que `hasMix` (y con él la etiqueta y el
      // source=mix del master) reflejen la entrega.
      onMixSettled?.();
    } catch (e) {
      clearProgressTimer();
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
      // El estado de mezcla cambió igual (failed / processing tras abort):
      // sincronizamos para no arrastrar un `hasMix` viejo.
      onMixSettled?.();
      // Watchdog: el backend no respondió a tiempo. SÍ es un fallo (el
      // usuario no pidió cancelar), así que se muestra como error y no
      // como el aviso informativo de cancelación.
      if ((e as { name?: string })?.name === "AbortError" && timedOutRef.current) {
        setCancelled(false);
        setError("La mezcla tardó demasiado y se detuvo. Vuelve a intentarlo.");
      } else if ((e as { name?: string })?.name === "AbortError") {
        // Cancelación explícita del usuario: estado informativo, NO un fallo.
        // (El backend puede seguir procesando server-side; el cliente deja de
        // esperar y no marca done.)
        setCancelled(true);
      } else {
        setError(e instanceof Error ? e.message : "No se pudo mezclar el audio");
      }
    } finally {
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
      if (abortRef.current === controller) abortRef.current = null;
      setMixing(false);
    }
  }, [sessionId, mixing, audioDurationSeconds, clearProgressTimer, dimensionEnabled, autoBalance, faderValues, onMixSettled]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    // El catch del fetch hace el resto: limpia el timer, marca `cancelled`
    // y baja `mixing`.
  }, []);

  // Sesión recargada con mix ya hecho: el player usa la URL estable del
  // backend (nunca se re-mezcla automáticamente).
  const hasMixed = Boolean(mixUrl || sessionMixPath);
  const audioSrc = sessionId
    ? mixUrl ?? (sessionMixPath ? getMixAudioUrl(sessionId) : null)
    : null;
  const analysis = mixResult ?? sessionMixAnalysis ?? null;

  // Etapas del feed de progreso: la cadena DSP real de ``build_mix``,
  // filtrada por dimensionEnabled (OFF = la etapa "dimension" no se aplica
  // en el backend y no aparece en la UI). El orden es el de la cadena.
  const stages = useMemo(
    () =>
      MIX_STATUS_STAGES.filter(
        (stage) => dimensionEnabled || stage.id !== "dimension",
      ),
    [dimensionEnabled],
  );
  // La ref se sincroniza tras cada render (prohibido escribir refs durante
  // el render) para que el intervalo siempre use la longitud actual sin
  // re-crear el timer.
  useEffect(() => {
    stagesRef.current = stages;
  }, [stages]);

  // Género real del análisis (chip + panel IA). "other" se normaliza a "Otro".
  const rawGenre =
    genreHint && genreHint !== "other"
      ? genreHint
      : analysis?.genre && analysis.genre !== "other"
        ? analysis.genre
        : null;
  const genreLabel = genreDisplayLabel(rawGenre);

  // Recomendaciones del modo IA — SOLO datos reales ya disponibles
  // (análisis de sesión vía genreHint + mixResult/sessionMixAnalysis).
  const qc = analysis?.qc_report as
    | { summary?: { all_ok?: boolean; flagged?: unknown[] } }
    | null
    | undefined;
  const aiCells: { label: string; value: string }[] = [];
  if (rawGenre) aiCells.push({ label: "Género", value: genreLabel });
  if (typeof analysis?.tempo_bpm === "number") {
    aiCells.push({ label: "Tempo", value: `${Math.round(analysis.tempo_bpm)} BPM` });
  }
  if (typeof analysis?.genre_confidence === "number") {
    aiCells.push({
      label: "Confianza",
      value: `${Math.round(analysis.genre_confidence * 100)}%`,
    });
  }
  if (qc) {
    aiCells.push({
      label: "QC",
      value: qc.summary?.all_ok === false ? "Revisar" : "OK",
    });
  }

  return (
    <div style={CARD_STYLE}>
      {/* ── Mini-panel del Asistente IA (datos reales del análisis) ── */}
      {mode === "ai" && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.25 }}
          className="overflow-hidden border-b"
          style={{ borderColor: "var(--border-subtle)", background: "var(--surface-hover)" }}
        >
          <div className="px-4 py-3">
            <p
              className="mb-2 text-[10px] font-bold uppercase tracking-[0.16em]"
              style={{ color: "var(--text-secondary)" }}
            >
              Recomendaciones del análisis
            </p>
            {aiCells.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                {aiCells.map((cell) => (
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
            ) : (
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Los datos del análisis aparecerán cuando generes la mezcla.
              </p>
            )}
          </div>
        </motion.div>
      )}

      {/* ── Título de sección + badges / acción primaria ── */}
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4">
        <div>
          <h2
            className="text-lg font-bold"
            style={{ color: "var(--text-primary)", letterSpacing: "-0.02em" }}
          >
            Mezcla de Audio
          </h2>
          <p className="mt-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
            Separa, ecualiza y mezcla tus stems en un bus unificado
          </p>
        </div>

        <div className="flex items-center gap-2">
          {hasMixed ? (
            <>
              {/* Pill de acción: muestra/oculta el panel de resultado.
                  Ojo = toggle de visibilidad, NO badge de estado. */}
              <button
                onClick={() => setShowResult((v) => !v)}
                disabled={!hasMixed || mixing}
                aria-pressed={hasMixed && showResult}
                title={
                  hasMixed
                    ? "Mostrar u ocultar el resultado de la mezcla"
                    : "Todavía no hay una mezcla"
                }
                className="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-all duration-300 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
                style={{
                  background: "var(--surface-hover)",
                  borderColor: "var(--border-subtle)",
                  color: "var(--text-primary)",
                }}
              >
                {showResult ? <EyeOff size={13} /> : <Eye size={13} />}
                Mostrar / Ocultar Panel
              </button>
              {/* Pill "Volver a Mezclar": re-procesa el mix (mismo click que
                  el botón primario de v1, ahora como pill verde). */}
              <button
                onClick={handleMix}
                disabled={disabled || mixing}
                title="Volver a mezclar"
                className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-all duration-300 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
                style={{
                  background: "rgba(48, 209, 88, 0.12)",
                  border: "1px solid rgba(48, 209, 88, 0.2)",
                  color: "#30d158",
                }}
              >
                {mixing ? (
                  <>
                    <Loader2 size={13} className="animate-spin" />
                    Mezclando...
                  </>
                ) : (
                  <>
                    <RefreshCw size={13} />
                    Volver a Mezclar
                  </>
                )}
              </button>
            </>
          ) : (
            <button
              onClick={handleMix}
              disabled={disabled || mixing || !sessionId}
              className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white transition-all duration-300 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              style={{
                background: "linear-gradient(135deg, #10b981, #00d4aa)",
                boxShadow: "0 4px 12px rgba(16, 185, 129, 0.25)",
              }}
            >
              {mixing ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Mezclando...
                </>
              ) : (
                <>
                  <Music2 size={16} /> Mezclar Audio
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* ── Opciones de la mezcla: dimensión espacial (Delay + Reverb).
          v6 — elección por mezcla (no persistida), default ON; se
          deshabilita mientras corre el POST /mix. OFF = routing Paso 03
          (backend omite dimension_report). */}
      <div className="flex flex-wrap items-center gap-2.5 px-4 pt-3">
        <button
          type="button"
          role="switch"
          aria-checked={dimensionEnabled}
          aria-label="Dimensión espacial (Delay + Reverb)"
          onClick={() => setDimensionEnabled((v) => !v)}
          disabled={mixing}
          className="relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            background: dimensionEnabled
              ? "var(--accent-primary)"
              : "var(--surface-active)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          <span
            className="absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full bg-white shadow transition-transform duration-200"
            style={{
              transform: dimensionEnabled ? "translateX(1rem)" : "translateX(0)",
            }}
          />
        </button>
        <div className="min-w-0">
          <p
            className="text-xs font-medium"
            style={{ color: "var(--text-primary)" }}
          >
            Dimensión espacial (Delay + Reverb)
          </p>
          <p
            className="text-[10px] leading-relaxed"
            style={{ color: "var(--text-muted)" }}
            title="Agrega delay tempo y reverb por stem. Apagada: mezcla seca, routing idéntico al paso de paneo."
          >
            Apagada: mezcla seca, sin delay ni reverb
          </p>
        </div>
      </div>

      {/* ── Balance: auto-balance opcional + faders manuales por stem (T6).
          Elección por mezcla (no persistida); apagado = neutral (payload
          previo exacto). El fader del usuario queda SIEMPRE visible y
          relativo al resultado del motor (spec: el motor propone, el humano
          decide). Se deshabilita mientras corre el POST /mix. */}
      <div
        className="mt-3 border-t px-4 pt-3"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <p
          className="mb-2 text-[10px] font-bold uppercase tracking-[0.16em]"
          style={{ color: "var(--text-secondary)" }}
        >
          Balance
        </p>
        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            role="switch"
            aria-checked={autoBalance}
            aria-label="Auto-balance"
            onClick={() => setAutoBalance((v) => !v)}
            disabled={mixing}
            className="relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              background: autoBalance
                ? "var(--accent-primary)"
                : "var(--surface-active)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <span
              className="absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full bg-white shadow transition-transform duration-200"
              style={{
                transform: autoBalance ? "translateX(1rem)" : "translateX(0)",
              }}
            />
          </button>
          <div className="min-w-0">
            <p
              className="text-xs font-medium"
              style={{ color: "var(--text-primary)" }}
            >
              Auto-balance
            </p>
            <p
              className="text-[10px] leading-relaxed"
              style={{ color: "var(--text-muted)" }}
              title="Corrige la voz hacia el nivel objetivo del género detectado (proceso automático)."
            >
              Ajusta la voz hacia el nivel objetivo del género. Apagado por
              defecto.
            </p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          {STEM_FADERS.map(({ key, label }) => (
            <FaderControl
              key={key}
              label={label}
              value={faderValues[key] ?? 0}
              disabled={mixing}
              onCommit={(db) =>
                setFaderValues((prev) =>
                  prev[key] === db ? prev : { ...prev, [key]: db },
                )
              }
            />
          ))}
        </div>
      </div>

      {/* ── Círculo de carga por etapas — solo mientras corre el /mix ──
          El anillo avanza con `progressPct` (interpolado por etapas; nunca
          llega a 100 hasta la respuesta real del backend). El feed
          secuencial de etapas DSP (MixStatusStream) vive debajo del anillo. */}
      {mixing && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="flex flex-col items-center gap-3 px-4 pt-6"
        >
          <div className="relative flex items-center justify-center">
            {/* Halo suave detrás del anillo */}
            <div
              className="absolute rounded-full"
              style={{
                width: 168,
                height: 168,
                background:
                  "radial-gradient(circle, rgba(0, 212, 170, 0.08) 0%, transparent 70%)",
              }}
              aria-hidden="true"
            />

            {/* Anillo de progreso */}
            <div className="relative">
              <svg width={128} height={128} className="-rotate-90">
                <defs>
                  <linearGradient
                    id="mix-ring-gradient"
                    x1="0%"
                    y1="0%"
                    x2="100%"
                    y2="100%"
                  >
                    <stop offset="0%" stopColor="#00d4aa" />
                    <stop offset="100%" stopColor="#5e5ce6" />
                  </linearGradient>
                </defs>
                {/* Track de fondo */}
                <circle
                  cx={64}
                  cy={64}
                  r={58}
                  fill="none"
                  stroke="var(--border)"
                  strokeWidth={6}
                />
                {/* Arco de progreso (dashoffset según `progressPct` real) */}
                <motion.circle
                  cx={64}
                  cy={64}
                  r={58}
                  fill="none"
                  stroke="url(#mix-ring-gradient)"
                  strokeWidth={6}
                  strokeLinecap="round"
                  strokeDasharray={2 * Math.PI * 58}
                  initial={false}
                  animate={{
                    strokeDashoffset: 2 * Math.PI * 58 * (1 - progressPct / 100),
                  }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                />
              </svg>
            </div>

            {/* % real: nunca 100 hasta la respuesta del backend */}
            <span
              className="absolute font-mono text-lg font-bold"
              style={{ color: "var(--text-primary)" }}
              aria-live="polite"
            >
              {progressPct}%
            </span>
          </div>

          {/* Feed secuencial de etapas DSP (no repetitivo): completadas en
              verde, la siguiente activa con Loader2, el resto pendiente.
              La fila final de éxito aparece SOLO con la respuesta real. */}
          <MixStatusStream
            stages={stages}
            stageIndex={progressStage}
            percent={progressPct}
          />
        </motion.div>
      )}

      {/* ── Error banner ── */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
          className="px-4 pt-4"
        >
          <div
            className="rounded-xl p-3 text-xs font-medium"
            style={{
              background: "rgba(239, 68, 68, 0.06)",
              border: "1px solid rgba(239, 68, 68, 0.2)",
              color: "#dc2626",
            }}
          >
            {error}
          </div>
        </motion.div>
      )}

      {/* ── Cancelación informativa (NO es un fallo) ── */}
      {cancelled && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
          className="px-4 pt-4"
        >
          <div
            className="flex items-center gap-2 rounded-xl p-3 text-xs font-medium"
            style={{
              background: "rgba(245, 158, 11, 0.08)",
              border: "1px solid rgba(245, 158, 11, 0.25)",
              color: "#b45309",
            }}
          >
            <Info size={14} />
            Mezcla cancelada. Puedes volver a intentarlo cuando quieras.
          </div>
        </motion.div>
      )}

      {/* ── Vista A/B dual + análisis ──
          Solo con mix real (nunca mientras procesa) y cuando la pill
          "Mostrar / Ocultar Panel" lo tiene visible. La fila de acciones vive
          aparte, permanente bajo el módulo. */}
      {hasMixed && sessionId && audioSrc && !mixing && showResult && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="px-4 pt-4"
        >
          <MixWaveformAB
            originalUrl={getAudioUrl(sessionId, "original")}
            mixedUrl={audioSrc}
            mixedDuration={analysis?.duration_seconds ?? null}
            /* La insignia "Audio mezclado" se muestra SOLO con una mezcla
               entregada por el backend (mix_status completed), no con un
               WAV local en vuelo o fallido. */
            hasMix={hasMix}
          />

          {analysis && <MixAnalysisGrid result={analysis} />}
        </motion.div>
      )}

      {/* ── Hint inicial ── */}
      {sessionId && !hasMixed && !mixing && !error && !cancelled && (
        <p
          className="px-4 pt-3 text-center text-xs"
          style={{ color: "var(--text-muted)" }}
        >
          La mezcla separa el audio en stems por rol, aplica ecualización
          por banda de frecuencia y los junta en un bus estéreo unificado.
        </p>
      )}
      {!hasMixed && !mixing && !sessionId && (
        <p className="px-4 pt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          Carga un audio para usar la Mezcla de Audio.
        </p>
      )}

      {/* ── Fila de acciones (permanente bajo el módulo) ──
          Masterizar: primaria verde, habilitada solo con mix terminado
          (onMasterize → vista de mastering). Cancelar mezcla: SIEMPRE
          presente; habilitado solo mientras corre el POST /mix (aborta
          el fetch vía AbortController). Descargar WAV: solo con resultado. */}
      <div
        className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t px-4 pt-3"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
          Mezcla generada: escucha el resultado o descarga el WAV
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onMasterize}
            disabled={!hasMixed || mixing}
            title={
              hasMixed
                ? "Continuar con el masterizado del audio"
                : "Genera la mezcla primero"
            }
            className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-bold uppercase tracking-wide text-white transition-all duration-200 hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              background: "linear-gradient(135deg, #10b981, #00d4aa)",
              boxShadow: "0 4px 12px rgba(16, 185, 129, 0.3)",
            }}
          >
            <Sparkles size={13} />
            Masterizar
          </button>
          <button
            onClick={handleCancel}
            disabled={!mixing}
            title={
              mixing
                ? "Cancelar la mezcla en curso"
                : "No hay una mezcla en curso"
            }
            className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-bold uppercase tracking-wide text-white transition-all duration-200 hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              background: "#ef4444",
              boxShadow: "0 4px 12px rgba(239, 68, 68, 0.3)",
            }}
          >
            <X size={13} strokeWidth={2.5} />
            Cancelar mezcla
          </button>
          {hasMixed && audioSrc && sessionId && (
            <a
              href={audioSrc}
              download={`${sessionId}_mix.wav`}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all hover:brightness-105"
              style={{
                background: "var(--surface-hover)",
                borderColor: "var(--border-subtle)",
                color: "var(--text-primary)",
                boxShadow: "0 1px 2px rgba(15,23,42,0.05)",
              }}
            >
              <Download size={13} />
              Descargar WAV
            </a>
          )}
        </div>
      </div>

      {/* Air inferior de la tarjeta */}
      <div className="h-4" />
    </div>
  );
}