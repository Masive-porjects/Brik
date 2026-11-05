"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import type { MixStatusStage } from "./mixI18n";

interface MixStatusStreamProps {
  /** Etapas de la cadena DSP (ya filtradas: sin "dimension" si está off). */
  stages: MixStatusStage[];
  /** Índice de la etapa que el backend reporta como ACTUAL. Las anteriores
   *  se marcan completadas y esta gira. ``-1`` = todavía no sabemos en cuál
   *  va (ninguna fila se marca activa). */
  activeIndex: number;
  /** Progreso real reportado por el backend (0..100). Solo 100 marca éxito. */
  percent: number;
  /** Copy de la fila final de éxito (lo inyecta el container con i18n). */
  doneLabel?: string;
}

/**
 * Feed secuencial del Mix Engine: una fila por etapa DSP real.
 *
 * Completada → check verde; actual → Loader2 girando; resto → pendiente
 * tenue. Cuando el backend reporta ``percent === 100`` se agrega la fila
 * final de éxito. Las filas NUNCA se repiten. Puro presentacional: no
 * conoce fetch, timers ni i18n.
 */
export default function MixStatusStream({
  stages,
  activeIndex,
  percent,
  doneLabel = "Mezcla final generada exitosamente",
}: MixStatusStreamProps) {
  const allCompleted = percent === 100;

  return (
    <div className="flex min-w-0 flex-col gap-1.5" aria-live="polite">
      {stages.map((stage, i) => {
        const completed =
          allCompleted || (activeIndex >= 0 && i < activeIndex);
        const active = !allCompleted && i === activeIndex;
        return (
          <div key={stage.id} className="flex items-center gap-2">
            {completed ? (
              <CheckCircle2
                size={14}
                className="shrink-0"
                style={{ color: "#10b981" }}
                aria-hidden="true"
              />
            ) : active ? (
              <Loader2
                size={14}
                className="shrink-0 animate-spin"
                style={{ color: "#10b981" }}
                aria-hidden="true"
              />
            ) : (
              <span
                className="h-3.5 w-3.5 shrink-0 rounded-full border"
                style={{ borderColor: "var(--border-subtle)" }}
                aria-hidden="true"
              />
            )}
            <span
              className="text-xs leading-snug"
              style={{
                color:
                  completed || active ? "var(--text-primary)" : "var(--text-muted)",
              }}
            >
              {stage.label}
            </span>
          </div>
        );
      })}

      {allCompleted && (
        <div className="flex items-center gap-2 pt-0.5">
          <CheckCircle2
            size={14}
            className="shrink-0"
            style={{ color: "#10b981" }}
            aria-hidden="true"
          />
          <span className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>
            {doneLabel}
          </span>
        </div>
      )}
    </div>
  );
}
