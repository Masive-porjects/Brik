/**
 * liveMeterBus — store externo (external store) de readings de meters.
 *
 * ANTI-PATRÓN QUE ELIMINA:
 *   Escribir React state por frame (rAF → setState) para meters/analyser.
 *   Ese patrón re-renderiza componentes a 60fps y encadena reconciliation
 *   innecesaria en cada frame de audio.
 *
 * REEMPLAZO:
 *   El engine (useLiveEngine.ts) computa un `LiveMeterReading` por frame y lo
 *   publica acá con `publish()`. Cualquier componente se suscribe con
 *   `subscribe()` (imperativo, sin re-render) o con `useLiveMeterReading()`
 *   (useSyncExternalStore, re-render solo cuando cambia la referencia del
 *   snapshot). El Deck de meters usa la variante imperativa: dibuja en canvas
 *   directo desde el snapshot, cero renders de React por frame.
 */

import { useSyncExternalStore } from 'react';

/** Lectura completa de meters por frame (SSOT del bus). */
export interface LiveMeterReading {
  /** Espectro (0..255 por bin) y forma de onda del master downmix. */
  frequency: Uint8Array;
  timeDomain: Uint8Array;
  /** RMS 0..1 del master (downmix mono). */
  outputLevel: number;
  /** RMS 0..1 por canal. */
  levelL: number;
  levelR: number;
  /** Picos reales en dB FS por canal. */
  peakL: number;
  peakR: number;
  /** Correlación estéreo: -1 (antifase) .. 0 (descorrelacionado) .. +1 (mono). */
  correlation: number;
  /** Ancho estéreo: 0 = mono, ~1 = full stereo, >1 = extra-wide. */
  width: number;
  /** Loudness momentánea aprox (~400 ms, ventana real — meterMath, NO BS.1770). */
  momentaryLufs: number;
  /** Loudness de corto término aprox (~3 s, ventana real — meterMath, NO BS.1770). */
  shortTermLufs: number;
  /** Marca de tiempo del frame (ms). */
  ts: number;
}

/** Reading inicial: silencio, arrays vacíos. Referencia estable entre publishes. */
export const EMPTY_READING: LiveMeterReading = {
  frequency: new Uint8Array(0),
  timeDomain: new Uint8Array(0),
  outputLevel: 0,
  levelL: 0,
  levelR: 0,
  peakL: -96,
  peakR: -96,
  correlation: 0,
  width: 0,
  momentaryLufs: -96,
  shortTermLufs: -96,
  ts: 0,
};

let current: LiveMeterReading = EMPTY_READING;
const listeners = new Set<() => void>();

/** Suscribirse a publicaciones. Devuelve unsubscribe. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Snapshot actual. Referencia estable si no hubo publish (requisito useSyncExternalStore). */
export function getSnapshot(): LiveMeterReading {
  return current;
}

/**
 * Publicar un nuevo reading. Si es la misma referencia que el anterior,
 * no notifica (evita re-renders espurios en uso con useSyncExternalStore).
 */
export function publish(reading: LiveMeterReading): void {
  if (reading === current) return;
  current = reading;
  listeners.forEach((listener) => listener());
}

/**
 * Resetear el bus a silencio (pausa/stop/teardown de grafo).
 * Publica la constante EMPTY_READING: múltiples resets seguidos no notifican.
 */
export function reset(): void {
  publish(EMPTY_READING);
}

/**
 * Hook React: re-render solo cuando el engine publica un reading nuevo.
 * Para los meters en vivo preferí subscribe() + canvas imperativo; este hook
 * sirve para readouts accesorios de estado lento (chip de status del
 * PresetHeader) sin piggybacking del reconciler en el hot path.
 */
export function useLiveMeterReading(): LiveMeterReading {
  return useSyncExternalStore(subscribe, getSnapshot);
}