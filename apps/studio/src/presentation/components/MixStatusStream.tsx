"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import type { MixStatusStage } from "./mixI18n";

interface MixStatusStreamProps {
  /** Etapas de la cadena DSP (ya filtradas: sin "dimension" si está off). */
  stages: MixStatusStage[];
  /** Índice de la última etapa COMPLETADA. Con el job async el backend no
   *  reporta etapa por etapa, así que se pasa -1 y se activa `indeterminate`. */
  stageIndex: number;
  /** Progreso real reportado por el backend (0..100). Solo 100 marca éxito. */
  percent: number;
  /** El backend no expone qué etapa del Mix Engine está corriendo: ninguna
   *  fila se marca "activa" porque no lo sabemos. Sin esto la UI estaría
   *  afirmando un dato que nadie midió. */
  indeterminate?: boolean;
  /** Copy de la fila final de éxito (lo inyecta el container con i18n). */
  doneLabel?: string;
}

/**
 * Feed secuencial del Mix Engine: una fila por etapa DSP real.
 *
 * Completada → check verde; siguiente → Loader2 girando; resto → pendiente
 * tenue. Cuando el backend reporta ``percent === 100`` se agrega la fila
 * final de éxito. Las filas NUNCA se repiten. Puro presentacional: no
 * conoce fetch, timers ni i18n.
 */
export default function MixStatusStream({
  stages,
  stageIndex,
  percent,
  indeterminate = false,
  doneLabel = "Mezcla final generada exitosamente",
}: MixStatusStreamProps) {
  const allCompleted = percent === 100;

  return (
    <div className="flex min-w-0 flex-col gap-1.5" aria-live="polite">
      {stages.map((stage, i) => {
        // En modo indeterminado NINGUNA etapa se marca completada ni activa:
        // el job es una sola unidad de trabajo y aún no sabemos en cuál va.
        const completed = allCompleted || (!indeterminate && i <= stageIndex);
        const active =
          !allCompleted &&
          !indeterminate &&
          i === Math.min(stageIndex + 1, stages.length - 1);
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
