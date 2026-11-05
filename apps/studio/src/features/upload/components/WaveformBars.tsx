"use client";

import { useEffect, useRef } from "react";
import { useIsClient } from "@/lib/audioUtils";

interface WaveformBarsProps {
  isPlaying?: boolean;
  bars?: number;
}

const DEFAULT_BARS = 32;
const GAP_RATIO = 0.4; // fracción del slot que es gap (resto es barra)

/**
 * Waveform decorativo renderizado en un único <canvas> en lugar de 32 <div>.
 *
 * Razones:
 * - Un solo nodo del DOM en vez de 32 + su contenedor: mucho menos coste de
 *   estilo y layout por frame.
 * - Las alturas se calculan y dibujan en JS con requestAnimationFrame, sin
 *   lecturas de getBoundingClientRect ni forced reflows.
 * - El contenedor conserva la clase .waveform-container (contain: layout en
 *   globals.css) para que la contención de estilo siga aplicando.
 */
export default function WaveformBars({
  isPlaying = true,
  bars = DEFAULT_BARS,
}: WaveformBarsProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const heightsRef = useRef<number[]>([]);
  const phaseRef = useRef<number[]>([]);
  const colorRef = useRef<{ start: string; end: string } | null>(null);
  const isClient = useIsClient();

  // Colores de gradiente leídos una sola vez (evita getComputedStyle en cada frame).
  useEffect(() => {
    if (!isClient) return;
    const computed = getComputedStyle(document.documentElement);
    colorRef.current = {
      start: computed.getPropertyValue("--accent-secondary").trim() || "#00d4aa",
      end: computed.getPropertyValue("--accent-primary").trim() || "#10b981",
    };
  }, [isClient]);

  // Alturas iniciales y fases por barra.
  useEffect(() => {
    if (!isClient) return;
    for (let i = 0; i < bars; i++) {
      heightsRef.current[i] = Math.max(
        4,
        12 + Math.sin(i * 0.5) * 18 + Math.cos(i * 0.3) * 8,
      );
      phaseRef.current[i] = Math.random() * Math.PI * 2;
    }
  }, [isClient, bars]);

  // Loop de animación: se re-inicia cuando cambian isPlaying o bars, así
  // `frame` siempre captura los valores actuales sin necesidad de refs
  // intermedios ni asignaciones durante el render.
  useEffect(() => {
    if (!isClient || !isPlaying) return;

    function frame(): void {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const width = canvas.width;
      const height = canvas.height;
      const slotWidth = width / bars;
      const barWidth = slotWidth * (1 - GAP_RATIO);
      const now = Date.now() * 0.002;

      ctx.clearRect(0, 0, width, height);

      const colors = colorRef.current;
      const gradient = ctx.createLinearGradient(0, height, 0, 0);
      gradient.addColorStop(0, colors?.start ?? "#00d4aa");
      gradient.addColorStop(1, colors?.end ?? "#10b981");
      ctx.fillStyle = gradient;

      for (let i = 0; i < bars; i++) {
        if (!isPlaying) {
          ctx.fillRect(
            i * slotWidth + (slotWidth - barWidth) / 2,
            height - heightsRef.current[i],
            barWidth,
            heightsRef.current[i],
          );
          continue;
        }

        // Altura objetivo: suave, aleatoria por barra, sin lecturas de layout.
        const phase = phaseRef.current[i] + now + i * 0.7;
        const target =
          Math.max(
            4,
            Math.min(
              height - 4,
              12 + Math.sin(phase) * 18 + Math.cos(phase * 0.7) * 8,
            ),
          );
        // Interpolación hacia el objetivo (suavizado).
        heightsRef.current[i] += (target - heightsRef.current[i]) * 0.18;

        ctx.fillRect(
          i * slotWidth + (slotWidth - barWidth) / 2,
          height - heightsRef.current[i],
          barWidth,
          heightsRef.current[i],
        );
      }

      rafRef.current = requestAnimationFrame(frame);
    }

    frame();
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [isClient, isPlaying, bars]);

  if (!isClient) return <canvas className="waveform-container" />;

  return (
    <canvas
      ref={canvasRef}
      className="waveform-container"
      width={400}
      height={48}
      style={{ width: "100%", height: "48px", display: "block" }}
    />
  );
}
