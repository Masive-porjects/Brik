/**
 * MixGateNotice — banner accionable del gate de mezcla → master (T4).
 *
 * Se renderiza junto al botón de masterizar cuando la sesión tiene una mezcla
 * INICIADA pero no entregada (``mix_status`` en `processing` o `failed`, T2).
 * El camino solo-master nunca se bloquea: este aviso solo aparece cuando el
 * usuario empezó a mezclar, así que el mensaje y el CTA dependen del estado
 * (`processing` = terminá la mezcla, `failed` = reintentá la mezcla).
 *
 * Es un banner, NO un modal: el usuario no pierde el contexto de los módulos
 * ni hay que cerrar nada para volver a masterizar. Los textos llegan ya
 * traducidos desde `useMasteringWorkflow` (i18n con `useTranslation`).
 */

"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Loader2, RefreshCw } from "lucide-react";
import type { MixStatus } from "@/lib/api";

/** Estado del gate que consume el banner. Lo arma `useMasteringWorkflow`
 *  (veredicto de `getMixGate`) y lo cablea la página. */
export interface MixGateState {
  /** El master está bloqueado por una mezcla no entregada. */
  blocked: boolean;
  /** Estado de mezcla del backend: distingue el copy de `processing` vs `failed`. */
  status: MixStatus;
  /** El usuario ya intentó masterizar con el gate bloqueado: se destaca el aviso. */
  attempted: boolean;
  /** Mensaje i18n (null = sin bloqueo). */
  message: string | null;
  /** Label i18n del CTA (null = sin bloqueo). */
  ctaLabel: string | null;
  /** Navega al tab de mezcla, donde vive el disparador de mezclar/reintentar. */
  onGoToMix: () => void;
}

interface MixGateNoticeProps {
  gate: MixGateState | null | undefined;
  className?: string;
}

export default function MixGateNotice({ gate, className }: MixGateNoticeProps) {
  const blocked = Boolean(gate?.blocked) && Boolean(gate?.message);
  const isProcessing = gate?.status === "processing";

  return (
    <AnimatePresence initial={false}>
      {blocked && (
        <motion.div
          key="mix-gate-notice"
          role="status"
          aria-live="polite"
          initial={{ opacity: 0, y: -8, height: 0 }}
          animate={{ opacity: 1, y: 0, height: "auto" }}
          exit={{ opacity: 0, y: -8, height: 0 }}
          transition={{ duration: 0.28, ease: "easeOut" }}
          className={`overflow-hidden ${className ?? ""}`}
        >
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-3.5 py-2.5"
            style={{
              background: "var(--bg-elevated)",
              border: `1px solid ${gate?.attempted ? "var(--accent-primary)" : "var(--border-subtle)"}`,
              boxShadow: gate?.attempted ? "0 0 0 1px var(--accent-primary)" : undefined,
              transition: "border-color 200ms ease, box-shadow 200ms ease",
            }}
          >
            <span
              className="flex size-6 shrink-0 items-center justify-center rounded-full"
              style={{
                background: "color-mix(in srgb, var(--accent-primary) 14%, transparent)",
                color: "var(--accent-primary)",
              }}
              aria-hidden="true"
            >
              {isProcessing ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RefreshCw size={13} />
              )}
            </span>

            <p
              className="min-w-0 flex-1 text-xs leading-relaxed"
              style={{ color: "var(--text-secondary)" }}
            >
              {gate?.message}
            </p>

            <button
              type="button"
              onClick={gate?.onGoToMix}
              className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold
                transition-all duration-200 hover:brightness-110 active:scale-[0.98]"
              style={{
                background: "color-mix(in srgb, var(--accent-primary) 16%, transparent)",
                border: "1px solid var(--border-subtle)",
                color: "var(--accent-primary)",
              }}
            >
              {gate?.ctaLabel}
              <ArrowRight size={12} />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
