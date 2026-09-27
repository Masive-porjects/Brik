"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import type { MixStatusStage } from "./mixI18n";

interface MixStatusStreamProps {
  /** Etapas de la cadena DSP (ya filtradas: sin "dimension" si está off). */
  stages: MixStatusStage[];
  /** Índice de la última etapa COMPLETADA (ticker monótono de MixPanel). */
  stageIndex: number;
  /** Progreso real: solo con 100 (respuesta del backend) aparece la fila
   *  final de éxito — nunca antes. */
  percent: number;
}

/**
 * Feed secuencial del POST /mix (blocking): una fila por etapa DSP real.
 * Completada → check verde; siguiente → Loader2 girando; resto → pendiente
 * tenue. Cuando el backend responde (``percent === 100``) se agrega la fila
 * final "Mezcla final generada exitosamente". Las filas NUNCA se repiten:
 * el ticker avanza monótono hasta la última etapa. Puro presentacional.
 */
export default function MixStatusStream({
  stages,
  stageIndex,
  percent,
}: MixStatusStreamProps) {
  const allCompleted = percent === 100;

  return (
    <div className="flex min-w-0 flex-col gap-1.5" aria-live="polite">
      {stages.map((stage, i) => {
        const completed = allCompleted || i <= stageIndex;
        const active =
          !allCompleted && i === Math.min(stageIndex + 1, stages.length - 1);
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
            Mezcla final{" "}
            <span className="serif-accent" style={{ color: "#10b981" }}>
              generada exitosamente
            </span>
            .
          </span>
        </div>
      )}
    </div>
  );
}