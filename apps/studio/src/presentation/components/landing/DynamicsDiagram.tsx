import type { CSSProperties } from "react";

interface DynamicsDiagramProps {
  normalLabel: string;
  masteredLabel: string;
  dynamicRangeLabel: string;
  peakControlLabel: string;
  cleanSpaceLabel: string;
  ariaLabel: string;
}

const BAR_COUNT = 40;
const SLOT = 8;
const BAR_W = 5;
const X0 = 8;
const MAX_H = 90;

/*
 * Bar heights are precomputed integers, not calculated at render. Floating
 * point math (Math.sin / Math.pow) can serialize differently on the server and
 * the client, which breaks hydration. Integers keep the markup identical.
 *
 * Normal audio: uneven bars with occasional tall peaks.
 * Mastered audio: heights pinned in a narrow band under the ceiling.
 */
const NORMAL_HEIGHTS: readonly number[] = [14, 90, 15, 39, 25, 30, 47, 16, 22, 38, 90, 73, 16, 90, 72, 29, 90, 29, 49, 22, 64, 39, 51, 28, 16, 22, 34, 14, 16, 28, 90, 59, 20, 28, 17, 41, 90, 89, 32, 65];
const MASTERED_HEIGHTS: readonly number[] = [54, 79, 56, 69, 64, 66, 71, 58, 63, 69, 80, 76, 59, 81, 76, 66, 79, 66, 71, 63, 75, 69, 72, 65, 58, 63, 67, 54, 58, 65, 81, 74, 62, 65, 59, 70, 81, 79, 67, 75];

/** Two-slot gaps split the mastered bars into clean bands (low / mid / high). */
function isGap(i: number): boolean {
  return (i >= 12 && i <= 13) || (i >= 26 && i <= 27);
}

const NORMAL_BASE = 120;
const MASTER_BASE = 270;
const CEILING_Y = MASTER_BASE - 0.92 * MAX_H;

const TEXT_STYLE: CSSProperties = { fill: "var(--text-secondary)" };
const TITLE_STYLE: CSSProperties = { fill: "var(--text-primary)" };
const PRIMARY_STYLE: CSSProperties = { fill: "var(--accent-primary)" };

/**
 * Side-by-side dynamics: a normal waveform against the same material mastered.
 * Arrows and labels call out dynamic range, peak control and clean space.
 */
export default function DynamicsDiagram({
  normalLabel,
  masteredLabel,
  dynamicRangeLabel,
  peakControlLabel,
  cleanSpaceLabel,
  ariaLabel,
}: DynamicsDiagramProps) {
  const normalBars = NORMAL_HEIGHTS.map((h, i) => (
    <rect key={`n-${i}`} x={X0 + i * SLOT} y={NORMAL_BASE - h} width={BAR_W} height={h} rx={1} fill="rgba(134, 147, 145, 0.75)" />
  ));

  const masteredBars = MASTERED_HEIGHTS.map((h, i) => {
    if (isGap(i)) return null;
    return <rect key={`m-${i}`} x={X0 + i * SLOT} y={MASTER_BASE - h} width={BAR_W} height={h} rx={1} fill="#6ee9e0" />;
  });

  const normalTop = NORMAL_BASE - MAX_H;
  const normalMinTop = NORMAL_BASE - 0.16 * MAX_H;
  const gapCenter = X0 + 12.5 * SLOT + BAR_W / 2;

  return (
    <svg
      viewBox="0 0 420 310"
      role="img"
      aria-label={ariaLabel}
      className="h-auto w-full"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <marker id="dyn-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto-start-reverse">
          <path d="M0,0 L8,4 L0,8 z" fill="rgba(134, 147, 145, 0.9)" />
        </marker>
        <marker id="dyn-arrow-primary" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill="#6ee9e0" />
        </marker>
      </defs>

      {/* Normal audio */}
      <text x={0} y={16} fontSize={13} fontWeight={600} style={TITLE_STYLE}>
        {normalLabel}
      </text>
      <line x1={X0 - 2} y1={NORMAL_BASE} x2={X0 + BAR_COUNT * SLOT} y2={NORMAL_BASE} stroke="rgba(134, 147, 145, 0.35)" strokeWidth={1} />
      {normalBars}

      {/* Dynamic range bracket */}
      <line
        x1={346}
        y1={normalTop}
        x2={346}
        y2={normalMinTop}
        stroke="rgba(134, 147, 145, 0.9)"
        strokeWidth={1.5}
        markerStart="url(#dyn-arrow)"
        markerEnd="url(#dyn-arrow)"
      />
      <text x={356} y={(normalTop + normalMinTop) / 2 - 4} fontSize={12} style={TEXT_STYLE}>
        <tspan x={356}>{dynamicRangeLabel.split(" ")[0]}</tspan>
        <tspan x={356} dy={14}>{dynamicRangeLabel.split(" ").slice(1).join(" ")}</tspan>
      </text>

      {/* Mastered audio */}
      <text x={0} y={170} fontSize={13} fontWeight={600} style={TITLE_STYLE}>
        {masteredLabel}
      </text>
      <line x1={0} y1={CEILING_Y} x2={420} y2={CEILING_Y} stroke="#6ee9e0" strokeOpacity={0.55} strokeWidth={1} strokeDasharray="4 4" />
      <line x1={330} y1={CEILING_Y - 14} x2={330} y2={CEILING_Y - 2} stroke="#6ee9e0" strokeWidth={1.5} markerEnd="url(#dyn-arrow-primary)" />
      <text x={420} y={CEILING_Y - 18} fontSize={12} textAnchor="end" style={PRIMARY_STYLE}>
        {peakControlLabel}
      </text>
      <line x1={X0 - 2} y1={MASTER_BASE} x2={X0 + BAR_COUNT * SLOT} y2={MASTER_BASE} stroke="rgba(110, 233, 224, 0.35)" strokeWidth={1} />
      {masteredBars}

      {/* Clean space between bands */}
      <line x1={gapCenter} y1={MASTER_BASE + 26} x2={gapCenter} y2={MASTER_BASE + 6} stroke="#6ee9e0" strokeWidth={1.5} markerEnd="url(#dyn-arrow-primary)" />
      <text x={gapCenter} y={MASTER_BASE + 38} fontSize={12} textAnchor="middle" style={PRIMARY_STYLE}>
        {cleanSpaceLabel}
      </text>
    </svg>
  );
}
