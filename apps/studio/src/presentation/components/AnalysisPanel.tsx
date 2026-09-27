"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import type { AnalysisResult, MasterResultMetrics, ValidationReport } from "@/lib/api";
import { DEFAULT_PRESET_COLOR, PRESET_INFO, type PresetInfo } from "@/core/presets";
import { useTranslation } from "@/i18n";

interface AnalysisPanelProps {
  analysis: AnalysisResult | null;
  presetId?: string;
  /** Measured metrics of the final master (from POST /process). */
  masterResult?: MasterResultMetrics | null;
  /** Layer 2 post-master validation verdict. */
  validation?: ValidationReport | null;
}

/* ── Animated count-up value ────────────────────────────
   Counts from 0 to the target every time the value changes
   (e.g. when the backend returns a fresh analysis after
   mastering). Writes textContent directly via GSAP onUpdate
   so no React state is touched (react-hooks/set-state-in-effect).
   Falls back to the plain value under prefers-reduced-motion. */

function CountUp({
  value,
  decimals = 1,
  suffix = "",
  className,
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      const fmt = (v: number) => `${v.toFixed(decimals)}${suffix}`;
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        el.textContent = fmt(value);
        return;
      }
      const state = { v: 0 };
      const tween = gsap.to(state, {
        v: value,
        duration: 1.1,
        ease: "power2.out",
        onUpdate: () => {
          el.textContent = fmt(state.v);
        },
      });
      return () => {
        tween.kill();
      };
    },
    { dependencies: [value, decimals, suffix] },
  );

  return (
    <span ref={ref} className={className}>
      {`${value.toFixed(decimals)}${suffix}`}
    </span>
  );
}

/* ── LED VU Meter ────────────────────────────────────── */

function VUMeter({
  label,
  value,
  unit,
  min,
  max,
  target,
  lowOk = true,
}: {
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  target?: number;
  lowOk?: boolean; // true = lower is better (LUFS), false = higher is better
}) {
  const pct = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
  const isWarn = target !== undefined
    ? lowOk ? value > target && value < target + 6 : value < target && value > target - 6
    : false;
  const isClip = target !== undefined
    ? lowOk ? value >= target + 6 : value <= target - 6
    : false;

  const barColor = isClip
    ? "var(--accent-primary)"
    : isWarn
      ? "var(--accent-warning)"
      : "var(--accent-success)";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[var(--text-muted)] font-medium uppercase tracking-wider">
          {label}
        </span>
        <span className="text-xs font-mono text-[var(--text-secondary)] tabular-nums">
          <CountUp value={value} decimals={1} />
          <span className="text-[var(--text-muted)] ml-0.5">{unit}</span>
        </span>
      </div>
      <div className="relative h-2 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${isClip ? 'var(--accent-primary)' : 'var(--accent-success)'}, ${barColor})`,
            boxShadow: isClip
              ? "0 0 8px var(--accent-primary)"
              : isWarn
                ? "0 0 8px var(--accent-warning)"
                : "0 0 4px rgba(52,199,89,0.3)",
          }}
        />
        {/* LED tick marks */}
        <div className="absolute inset-0 flex items-center px-0.5 pointer-events-none">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="flex-1 h-full border-r border-[var(--border-subtle)] last:border-r-0" />
          ))}
        </div>
      </div>
      {target !== undefined && (
        <div className="flex justify-between text-[9px] text-[var(--text-muted)]">
          <span>{min}{unit}</span>
          <span className="text-[var(--text-muted)]">target {target}{unit}</span>
          <span>{max}{unit}</span>
        </div>
      )}
    </div>
  );
}

/* ── Metric row ──────────────────────────────────────── */

function MetricRow({
  label,
  value,
  accent,
  animate,
  animateDecimals = 0,
  animateSuffix = "",
}: {
  label: string;
  value: string;
  accent?: string;
  /** When set, count up from 0 to this number instead of showing `value` */
  animate?: number;
  animateDecimals?: number;
  animateSuffix?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
      <span
        className="text-xs font-mono tabular-nums"
        style={{ color: accent ?? "var(--text-primary)" }}
      >
        {animate !== undefined ? (
          <CountUp
            value={animate}
            decimals={animateDecimals}
            suffix={animateSuffix}
          />
        ) : (
          value
        )}
      </span>
    </div>
  );
}

/* ── Master result card ────────────────────────────────
    Compares the MEASURED master (from the process response)
    against the preset targets. Renders only when measured
    LUFS exists — otherwise the targets-only view stays. */

const DELTA_OK = "#34c759";
const DELTA_WARN = "#ff9f0a";

function formatDelta(delta: number): string {
  return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`;
}

interface ComparisonRow {
  label: string;
  achieved: number;
  target: number;
  delta: number;
  ok: boolean;
}

function MasterResultCard({
  masterResult,
  presetInfo,
}: {
  masterResult?: MasterResultMetrics | null;
  presetInfo?: PresetInfo;
}) {
  const { t } = useTranslation();
  const lufs = masterResult?.integrated_lufs;
  if (lufs === null || lufs === undefined) return null;

  const color = presetInfo?.color ?? DEFAULT_PRESET_COLOR.wave;
  const targetLufs = presetInfo?.targetLufs ?? -14;
  const targetPeak = presetInfo?.ceiling ?? -1;

  const rows: ComparisonRow[] = [
    {
      label: "LUFS",
      achieved: lufs,
      target: targetLufs,
      delta: lufs - targetLufs,
      ok: Math.abs(lufs - targetLufs) <= 0.8,
    },
  ];
  const peak = masterResult?.true_peak_db;
  if (peak !== null && peak !== undefined) {
    rows.push({
      label: "True Peak",
      achieved: peak,
      target: targetPeak,
      delta: peak - targetPeak,
      ok: peak - targetPeak <= 0.1,
    });
  }
  const crest = masterResult?.crest_factor_db;
  if (crest !== null && crest !== undefined) {
    // Crest: informational — any value is acceptable, always green
    rows.push({ label: "Crest", achieved: crest, target: 12, delta: crest - 12, ok: true });
  }

  return (
    <div
      className="p-3 rounded-lg text-xs"
      style={{
        background: `color-mix(in srgb, ${color} 10%, transparent)`,
        border: `1px solid ${color}`,
      }}
    >
      <div className="flex items-center gap-2 mb-2">
        <span
          className="w-2 h-2 rounded-full shadow"
          style={{ background: color, boxShadow: `0 0 5px ${color}` }}
        />
        <span className="font-medium text-[var(--text-primary)]">
          {t("analysis.masterResultTitle", "Resultado del Master")}
        </span>
      </div>
      {presetInfo && (
        <p className="text-[var(--text-secondary)] text-[11px] mb-2">
          {t("analysis.measuredVsTarget", "Medido vs objetivo de")} {presetInfo.title}
        </p>
      )}
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between py-0.5">
            <span className="text-[11px] text-[var(--text-muted)]">{row.label}</span>
            <span className="flex items-center gap-1.5">
              <span className="text-xs font-mono tabular-nums text-[var(--text-primary)]">
                {row.achieved.toFixed(1)}
                <span className="text-[var(--text-muted)]"> / {row.target.toFixed(1)} dB</span>
              </span>
              <span
                className="px-1.5 py-0.5 rounded-full text-[9px] font-mono tabular-nums"
                style={{
                  color: row.ok ? DELTA_OK : DELTA_WARN,
                  background: row.ok ? "rgba(52,199,89,0.12)" : "rgba(255,159,10,0.12)",
                }}
              >
                {formatDelta(row.delta)}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Validation banner (Layer 2 gate) ──────────────────
   Compact verdict above the master result card: slim green
   line when in tolerance, amber card listing issues when not. */

function ValidationBanner({
  validation,
}: {
  validation?: ValidationReport | null;
}) {
  const { t } = useTranslation();
  if (!validation) return null;

  const retrySuffix = t("analysis.retrySuffix", " (reintentado automáticamente con menor intensidad)");

  if (validation.status === "ok") {
    return (
      <div
        className="px-2.5 py-1.5 rounded-lg text-[11px] flex items-center gap-1.5"
        style={{
          background: "rgba(52, 199, 89, 0.08)",
          border: "1px solid rgba(52, 199, 89, 0.2)",
          color: "var(--accent-success)",
        }}
      >
        <span>✓</span>
        <span>
          {t("analysis.masterValidated", "Master validado — dentro de tolerancia")}
          {validation.retry_applied ? retrySuffix : ""}
        </span>
      </div>
    );
  }

  const messages = validation.issues.map((issue) => issue.message_es);
  return (
    <div
      className="p-2.5 rounded-lg text-xs"
      style={{
        background: "rgba(255, 159, 10, 0.08)",
        border: "1px solid rgba(255, 159, 10, 0.3)",
      }}
    >
      <div className="flex items-start gap-1.5">
        <span
          className="mt-1 w-1.5 h-1.5 rounded-full shrink-0"
          style={{ background: DELTA_WARN, boxShadow: `0 0 5px ${DELTA_WARN}` }}
        />
        <p className="text-[var(--text-secondary)] leading-relaxed">
          {messages.join(" · ")}
          {validation.retry_applied ? retrySuffix : ""}
        </p>
      </div>
      {validation.suggested_preset_id === "universal" && (
        <p className="text-[11px] mt-1.5" style={{ color: DELTA_WARN }}>
          {t("analysis.suggestPulido", "Sugerencia: prueba Pulido")}
        </p>
      )}
    </div>
  );
}

/* ── Main panel ──────────────────────────────────────── */

export default function AnalysisPanel({
  analysis,
  presetId,
  masterResult,
  validation,
}: AnalysisPanelProps) {
  const { t } = useTranslation();

  if (!analysis) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <div className="w-10 h-10 rounded-full bg-[var(--surface-hover)] flex items-center justify-center mb-3">
          <svg className="w-5 h-5 text-[var(--text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5m.75-9l3-3 2.148 2.148A12.061 12.061 0 0116.5 7.605" />
          </svg>
        </div>
        <p className="text-xs text-[var(--text-muted)]">{t("analysis.noAudio", "Carga un audio para ver el análisis")}</p>
      </div>
    );
  }

  const formatDb = (db: number) => db.toFixed(1);

  // Preset-aware targets (fall back to streaming-standard values)
  const presetInfo = presetId ? PRESET_INFO[presetId] : undefined;
  const lufsTarget = presetInfo?.targetLufs ?? -14;
  const peakTarget = presetInfo?.ceiling ?? -1;

  // Hide weak-evidence genre guesses instead of showing a misleading label.
  const genreIdentified =
    analysis.detected_genre !== "other" &&
    (analysis.genre_confidence ?? 0) >= 0.5;

  return (
    <div className="space-y-4">
        {/* Already-mastered warning banner */}
      {analysis.is_already_mastered && (
        <div className="p-3 rounded-lg text-xs" style={{
          background: "rgba(255, 159, 10, 0.08)",
          border: "1px solid rgba(255, 159, 10, 0.25)",
          color: "#fbbf24",
        }}>
          <div className="flex items-center gap-1.5 mb-1.5">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <span className="font-semibold">{t("analysis.alreadyMasteredTitle", "Audio ya masterizado")}</span>
          </div>
          <p className="text-[10px] opacity-80 leading-relaxed">
            {analysis.mastering_confidence !== undefined
              ? `${t("analysis.confidence", "Confianza")}: ${Math.round(analysis.mastering_confidence * 100)}%. `
              : ""}
            {t("analysis.alreadyMasteredDesc", "Procesarlo de nuevo puede causar sobremasterización. Se aplicará una cadena reducida al 80% para preservar la calidad.")}
          </p>
        </div>
      )}

      {/* Preset objetivo — only when a preset is selected */}
      {presetId && PRESET_INFO[presetId] && (() => {
        const info = PRESET_INFO[presetId]!;
        return (
          <div
            className="p-3 rounded-lg text-xs"
            style={{
              background: `color-mix(in srgb, ${info.color} 10%, transparent)`,
              border: `1px solid ${info.color}`,
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className="w-2 h-2 rounded-full shadow"
                style={{ background: info.color, boxShadow: `0 0 5px ${info.color}` }}
              />
              <span className="font-medium text-[var(--text-primary)]">
                {t("analysis.targetPreset", "Preset Objetivo")}
              </span>
            </div>
            <p className="text-[var(--text-secondary)] text-[11px] mb-2">
              {info.title} — {info.genre}
            </p>
            <div className="grid grid-cols-3 gap-2">
              <MetricRow
                label={t("analysis.targetLufs", "Target LUFS")}
                value={`${info.targetLufs} dB`}
                accent={info.color}
              />
              <MetricRow
                label={t("analysis.ceiling", "Ceiling")}
                value={`${info.ceiling.toFixed(1)} dB`}
                accent={info.color}
              />
              <MetricRow
                label={t("analysis.ratio", "Ratio")}
                value={`${info.ratio.toFixed(1)}:1`}
                accent={info.color}
              />
            </div>
          </div>
        );
      })()}

      {/* Validation verdict (Layer 2) — above the measured result */}
      <ValidationBanner validation={validation} />

      {/* Master result — measured vs target, only after processing */}
      <MasterResultCard masterResult={masterResult} presetInfo={presetInfo} />

      {/* LED BAR METERS */}
      <VUMeter
        label="LUFS"
        value={analysis.integrated_lufs}
        unit="dB"
        min={-40}
        max={0}
        target={lufsTarget}
        lowOk
      />

      <VUMeter
        label={t("analysis.truePeak", "True Peak")}
        value={analysis.true_peak_db}
        unit="dB"
        min={-12}
        max={3}
        target={peakTarget}
        lowOk
      />

      {/* Crest factor */}
      {analysis.crest_factor_db !== undefined && (
        <VUMeter
          label={t("report.crestFactor", "Crest Factor")}
          value={analysis.crest_factor_db}
          unit="dB"
          min={0}
          max={24}
          target={12}
          lowOk={false}
        />
      )}

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-x-4 border-t border-[var(--border-subtle)] pt-3">
        <MetricRow
          label={t("analysis.dynamicRangeShort", "Rango Din.")}
          value={`${formatDb(analysis.dynamic_range_db)} dB`}
        />
        <MetricRow
          label={t("analysis.tempo", "Tempo")}
          value={`${Math.round(analysis.tempo_bpm)} BPM`}
          animate={analysis.tempo_bpm}
          animateSuffix=" BPM"
        />
        <MetricRow
          label={t("analysis.genre", "Género")}
          value={
            genreIdentified
              ? analysis.detected_genre.replace("_", " ")
              : t("common.notIdentified", "No identificado")
          }
          accent={genreIdentified ? "var(--accent-primary)" : undefined}
        />
        <MetricRow
          label={t("common.duration", "Duración")}
          value={formatDuration(analysis.duration_seconds)}
        />
        <MetricRow
          label={t("report.sampleRate", "Sample Rate")}
          value={`${(analysis.sample_rate / 1000).toFixed(1)} kHz`}
        />
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const min = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  return `${min}:${sec.toString().padStart(2, "0")}`;
}
