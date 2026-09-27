"use client";

import { motion } from "framer-motion";
import { Activity } from "lucide-react";
import type { MasteringParameters } from "@/lib/api";
import { useSignalChain } from "@/application/hooks/useSignalChain";
import { useTranslation } from "@/i18n";

/* ── Signal Chain Visualizer ───────────────────────────────
   Renders the 4 processing blocks as a horizontal chain.
   Each block shows: label, parameter summary, and a mini SVG
   curve representing the processing characteristic.

   Props:
     params — the active MasteringParameters from the session
     compact — optional: shrink for mobile sidebar placement
   ────────────────────────────────────────────────────────── */

interface SignalChainProps {
  params: MasteringParameters;
  compact?: boolean;
}

/* ── Single chain block ────────────────────────────────── */

function ChainBlockView({
  block,
  compact,
  index,
}: {
  block: ReturnType<typeof useSignalChain>[number];
  compact?: boolean;
  index: number;
}) {
  const { t } = useTranslation();
  const localizedLabel = t(`signalChain.blocks.${block.id}`, block.label);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.08 }}
      className={`relative flex flex-col ${compact ? "gap-1.5" : "gap-2"}`}
    >
      {/* Block container */}
      <div
        className={`relative rounded-xl overflow-hidden transition-all duration-300 ${
          block.active ? "" : "opacity-40"
        }`}
        style={{
          background: block.active
            ? `linear-gradient(135deg, ${block.color}08, ${block.color}03)`
            : "var(--surface-hover)",
          borderColor: block.active ? `${block.color}20` : "transparent",
          boxShadow: block.active ? `inset 0 0 0 1px ${block.color}30` : "none",
          padding: compact ? "8px" : "12px",
        }}
      >
        {/* Label row */}
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-1.5">
            {/* Status dot */}
            <div
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{
                background: block.active ? block.color : "var(--text-muted)",
                boxShadow: block.active
                  ? `0 0 6px ${block.color}60`
                  : "none",
              }}
            />
            <span
              className={`font-semibold ${compact ? "text-[10px]" : "text-xs"}`}
              style={{ color: block.active ? block.color : "var(--text-muted)" }}
            >
              {localizedLabel}
            </span>
          </div>
          {!compact && (
            <span className="text-[9px] text-[var(--text-muted)] font-mono">
              {block.active ? t("signalChain.on", "ON") : t("signalChain.bypass", "BYPASS")}
            </span>
          )}
        </div>

        {/* SVG Curve */}
        <div
          className="relative"
          style={{
            height: compact ? 32 : 44,
          }}
        >
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="w-full h-full"
            aria-hidden="true"
          >
            {/* Grid lines */}
            <line
              x1="0" y1="50" x2="100" y2="50"
              stroke="var(--border-subtle)"
              strokeWidth="0.3"
              strokeDasharray="2 2"
            />
            <line
              x1="50" y1="0" x2="50" y2="100"
              stroke="var(--border-subtle)"
              strokeWidth="0.3"
              strokeDasharray="2 2"
            />

            {/* Main curve */}
            <motion.path
              d={block.curvePath}
              fill="none"
              stroke={block.color}
              strokeWidth={block.active ? 2 : 1}
              strokeLinecap="round"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{
                pathLength: 1,
                opacity: block.active ? 1 : 0.3,
              }}
              transition={{ duration: 0.8, delay: index * 0.1 }}
            />

            {/* Overlay curve (gain reduction for compressor) */}
            {block.overlayPath && block.active && (
              <motion.path
                d={block.overlayPath}
                fill="none"
                stroke={block.color}
                strokeWidth="1"
                strokeLinecap="round"
                strokeDasharray="3 2"
                opacity={0.4}
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 1, delay: index * 0.1 + 0.3 }}
              />
            )}

            {/* Active glow */}
            {block.active && (
              <motion.path
                d={block.curvePath}
                fill="none"
                stroke={block.color}
                strokeWidth="4"
                strokeLinecap="round"
                opacity={0.15}
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 1.2, delay: index * 0.1 }}
              />
            )}
          </svg>

          {/* Intensity bar (bottom) */}
          <div
            className="absolute bottom-0 left-0 right-0 h-[2px] rounded-full overflow-hidden"
            style={{ background: "var(--border-subtle)" }}
          >
            <motion.div
              className="h-full rounded-full"
              style={{ background: block.color }}
              initial={{ width: "0%" }}
              animate={{ width: `${block.intensity * 100}%` }}
              transition={{ duration: 0.6, delay: index * 0.1 }}
            />
          </div>
        </div>

        {/* Subtitle */}
        <p
          className={`font-mono leading-tight mt-1 ${compact ? "text-[8px]" : "text-[9px]"}`}
          style={{ color: "var(--text-muted)" }}
        >
          {block.subtitle}
        </p>
      </div>

      {/* Connector arrow (between blocks, not after last) */}
      {index < 3 && (
        <div
          className={`absolute -right-2 top-1/2 -translate-y-1/2 z-10 ${
            compact ? "hidden" : ""
          }`}
          style={{ color: "var(--text-muted)", opacity: 0.3 }}
        >
          <svg width="8" height="10" viewBox="0 0 8 10" fill="none">
            <path
              d="M1 1L6 5L1 9"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      )}
    </motion.div>
  );
}

/* ── Main component ─────────────────────────────────────── */

export default function SignalChain({ params, compact }: SignalChainProps) {
  const { t } = useTranslation();
  const blocks = useSignalChain(params);

  return (
    <div
      className={`w-full ${compact ? "" : "py-3"}`}
    >
      {/* Header */}
      {!compact && (
        <div className="flex items-center gap-2 mb-3 px-1">
          <Activity size={13} className="text-[var(--text-muted)]" />
          <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
            {t("signalChain.title", "Cadena de Señal")}
          </span>
        </div>
      )}

      {/* Chain blocks */}
      <div
        className={`grid gap-2 ${
          compact
            ? "grid-cols-2 gap-1.5"
            : "grid-cols-4 gap-2"
        }`}
      >
        {blocks.map((block, i) => (
          <ChainBlockView
            key={block.id}
            block={block}
            compact={compact}
            index={i}
          />
        ))}
      </div>

      {/* Flow indicator (desktop only) */}
      {!compact && (
        <div className="flex items-center justify-center gap-1.5 mt-3 opacity-30">
          <div className="h-px flex-1 bg-gradient-to-r from-transparent to-[var(--border-subtle)]" />
          <span className="text-[8px] text-[var(--text-muted)] uppercase tracking-widest shrink-0">
            {t("signalChain.flow", "Input → Procesamiento → Output")}
          </span>
          <div className="h-px flex-1 bg-gradient-to-l from-transparent to-[var(--border-subtle)]" />
        </div>
      )}
    </div>
  );
}
