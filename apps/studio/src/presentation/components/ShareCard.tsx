"use client";

import type { AnalysisResult, MasterResultMetrics } from "@/lib/api";
import { DEFAULT_PRESET_COLOR, PRESET_INFO } from "@/core/presets";

/* ── Share card ────────────────────────────────────────
   Renders a 1200×630 promo card of the finished master on an
   offscreen <canvas> and shares it via the Web Share API
   (level 2, with file), falling back to a PNG download. */

const CARD_W = 1200;
const CARD_H = 630;
const PAD = 64;

const BG_DARK = "#0a0a0c";
const TEXT_PRIMARY = "#e8e8e8";
const TEXT_SECONDARY = "#8a8f93";
const TEXT_MUTED = "#555555";

interface ShareCardProps {
  sessionId: string;
  originalPath: string | null;
  presetId?: string | null;
  analysis: AnalysisResult | null;
  masterResult?: MasterResultMetrics | null;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load ${src}`));
    img.src = src;
  });
}

function truncateToWidth(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let out = text;
  while (out.length > 1 && ctx.measureText(`${out}…`).width > maxWidth) {
    out = out.slice(0, -1);
  }
  return `${out}…`;
}

function roundedRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function formatDb(v: number | null | undefined): string | null {
  return v === null || v === undefined ? null : `${v.toFixed(1)} dB`;
}

async function renderCard(opts: {
  trackName: string;
  accent: string;
  presetTitle: string | null;
  stats: { label: string; value: string }[];
}): Promise<HTMLCanvasElement> {
  const canvas = document.createElement("canvas");
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");

  // Background — app dark theme
  ctx.fillStyle = BG_DARK;
  ctx.fillRect(0, 0, CARD_W, CARD_H);

  // Accent glow (top-right) + gradient bar (top edge)
  const glow = ctx.createRadialGradient(
    CARD_W - 120,
    -80,
    40,
    CARD_W - 120,
    -80,
    560,
  );
  glow.addColorStop(0, `${opts.accent}33`);
  glow.addColorStop(1, "#00000000");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, CARD_W, CARD_H);

  const bar = ctx.createLinearGradient(0, 0, CARD_W, 0);
  bar.addColorStop(0, opts.accent);
  bar.addColorStop(1, "#00000000");
  ctx.fillStyle = bar;
  ctx.fillRect(0, 0, CARD_W, 6);

  // Ghost watermark — low opacity, right side (best-effort)
  try {
    const ghost = await loadImage("/brand/WaveAI.png");
    const h = CARD_H * 0.92;
    const w = (ghost.width / ghost.height) * h;
    ctx.save();
    ctx.globalAlpha = 0.08;
    ctx.drawImage(ghost, CARD_W - w - 24, (CARD_H - h) / 2, w, h);
    ctx.restore();
  } catch {
    // Watermark is decorative — ignore load failures
  }

  // Logo top-left (SVG; styled-text fallback)
  try {
    const logo = await loadImage("/brand/WaveAI.svg");
    const h = 84;
    const w = (logo.width / logo.height) * h;
    ctx.drawImage(logo, PAD, PAD - 10, w, h);
  } catch {
    ctx.fillStyle = opts.accent;
    ctx.font = '800 34px system-ui, sans-serif';
    ctx.textBaseline = "alphabetic";
    ctx.fillText("WaveIA", PAD, PAD + 24);
  }

  // Track name
  const textMaxW = CARD_W - PAD * 2 - 260;
  ctx.textBaseline = "alphabetic";
  ctx.font = '700 68px system-ui, sans-serif';
  ctx.fillStyle = TEXT_PRIMARY;
  ctx.fillText(truncateToWidth(ctx, opts.trackName, textMaxW), PAD, 292);

  // Preset badge
  let cursorY = 292;
  if (opts.presetTitle) {
    const label = opts.presetTitle.toUpperCase();
    ctx.font = '700 22px system-ui, sans-serif';
    const tw = ctx.measureText(label).width;
    const bw = tw + 32;
    const bh = 42;
    const by = 316;
    roundedRectPath(ctx, PAD, by, bw, bh, bh / 2);
    ctx.fillStyle = `${opts.accent}1f`;
    ctx.fill();
    ctx.strokeStyle = `${opts.accent}99`;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = opts.accent;
    ctx.fillText(label, PAD + 16, by + 28);
    cursorY = by + bh;
  }

  // Stats row
  let sx = PAD;
  const sy = Math.max(cursorY + 56, 452);
  for (const stat of opts.stats) {
    ctx.font = '500 18px system-ui, sans-serif';
    ctx.fillStyle = TEXT_SECONDARY;
    ctx.fillText(stat.label.toUpperCase(), sx, sy);
    ctx.font = '700 30px ui-monospace, monospace';
    ctx.fillStyle = TEXT_PRIMARY;
    ctx.fillText(stat.value, sx, sy + 38);
    const labelW = ctx.measureText(stat.label).width;
    sx += Math.max(labelW, 120) + 48;
    if (sx > CARD_W - PAD * 2) break;
  }

  // Footer
  ctx.font = '500 20px system-ui, sans-serif';
  ctx.fillStyle = TEXT_MUTED;
  ctx.fillText("masterizado con WaveIA", PAD, CARD_H - 36);

  return canvas;
}

export default function ShareCard({
  sessionId,
  originalPath,
  presetId,
  analysis,
  masterResult,
}: ShareCardProps) {
  const handleShare = async () => {
    const name = originalPath?.split(/[\\/]/).pop() ?? "";
    const trackName = name.replace(/\.[^.]+$/, "") || "Track sin nombre";

    const presetInfo = presetId ? PRESET_INFO[presetId] : undefined;
    const accent = presetInfo?.color ?? DEFAULT_PRESET_COLOR.wave;

    // Master metrics first, original-analysis values as fallback
    const stats: { label: string; value: string }[] = [];
    const lufs = formatDb(masterResult?.integrated_lufs ?? analysis?.integrated_lufs);
    if (lufs) stats.push({ label: "LUFS integrado", value: lufs });
    const peak = formatDb(masterResult?.true_peak_db ?? analysis?.true_peak_db);
    if (peak) stats.push({ label: "True Peak", value: peak });
    const bpm = analysis?.tempo_bpm;
    if (bpm !== null && bpm !== undefined) {
      stats.push({ label: "BPM", value: String(Math.round(bpm)) });
    }
    const genre = analysis?.detected_genre;
    if (genre) stats.push({ label: "Género", value: genre.replace("_", " ") });

    let blob: Blob | null = null;
    try {
      const canvas = await renderCard({
        trackName,
        accent,
        presetTitle: presetInfo?.title ?? null,
        stats,
      });
      blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/png"),
      );
    } catch {
      return; // canvas unavailable — nothing sensible to share
    }
    if (!blob) return;

    const fileName = `waveai_${sessionId}_card.png`;
    const file = new File([blob], fileName, { type: "image/png" });

    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({
          files: [file],
          title: "WaveIA",
          text: `${trackName} — masterizado con WaveIA`,
        });
        return;
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        // Real share failure → fall through to download
      }
    }

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <button
      onClick={handleShare}
      aria-label="Compartir tarjeta del master"
      className="flex-1 py-2.5 rounded-lg text-xs font-medium text-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--surface-hover)] hover:bg-[var(--surface-active)] transition-all border border-[var(--border-subtle)]"
    >
      Compartir
    </button>
  );
}
