/**
 * Decisión que el chat manda al job cuando Brik escala a ejecución.
 *
 * El backend nombra dos tipos de escalada:
 *
 * - `agent` — el loop de sesión (`POST /jobs/agent/{session_id}`), que lee el
 *   audio que el usuario acaba de subir.
 * - `master` — "sáltate la mezcla, masteriza el original". Es exactamente la
 *   ruta que el mismo loop expone como `decision: "master_only"`.
 *
 * La escalada `master` NO puede ir a `POST /jobs/master`: ese endpoint
 * stateless resuelve su entrada desde `public.tracks.storage_path` (o una URL
 * explícita), y el chat solo conoce el id de la sesión de subida. Mandar ese
 * id como `track_id` no encontraba ninguna fila y respondía 500 en cada
 * escalada.
 */

export type AgentDecision = "auto" | "mix_then_master" | "master_only";

/** Payload que el backend adjunta a la escalada. */
export interface EscalationJobPayload {
  /** Decisión elegida para una escalada `agent`. */
  decision?: unknown;
  [key: string]: unknown;
}

/**
 * Resuelve la decisión del job de sesión para una escalada.
 *
 * `master` siempre es `master_only`; `agent` reenvía la decisión que eligió
 * Brik y cae en `auto` cuando falta o no es una ruta conocida.
 */
export function escalationDecision(
  jobKind: "agent" | "master",
  jobPayload?: EscalationJobPayload | null,
): AgentDecision {
  if (jobKind === "master") return "master_only";

  const requested = jobPayload?.decision;
  return requested === "mix_then_master" || requested === "master_only"
    ? requested
    : "auto";
}
