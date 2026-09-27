/**
 * Cierre seguro e idempotente de un AudioContext.
 *
 * InvalidStateError("Cannot close a closed AudioContext") aparece cuando dos
 * rutas de cleanup cierran el mismo context (React Strict Mode / Fast Refresh:
 * efectos que se montan/desmontan dos veces, cleanups duplicados, finally).
 * Esta función es no-op si:
 *   - ctx es null/undefined
 *   - ctx ya está en estado "closed"
 * y traga ÚNICAMENTE InvalidStateError (la carrera de cierre: otro cleanup
 * cerró el context entre la comprobación y el close). Cualquier otro
 * error real se re-lanza para no ocultar bugs del engine.
 */
export async function safeCloseAudioContext(
  ctx?: AudioContext | null,
): Promise<void> {
  if (!ctx) return;
  if (ctx.state === 'closed') return;
  try {
    await ctx.close();
  } catch (err) {
    if (err instanceof DOMException && err.name === 'InvalidStateError') {
      // Otro cleanup ya cerró este context entre la comprobación y el close.
      return;
    }
    throw err;
  }
}