/**
 * meterMath — helpers de matemática pura para el Live Meter Deck.
 *
 * Funciones sin estado, sin DOM, sin React: la única fuente de verdad para
 * rms / peak / correlation / width / LUFS aprox. El bus (liveMeterBus.ts) y
 * el engine (useLiveEngine.ts) las usan para escribir readings por frame.
 */

/** Clamp clásico. */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** RMS (0..1) de una ventana de samples en punto flotante. */
export function rms(samples: Float32Array | ArrayLike<number>): number {
  const n = samples.length;
  if (n === 0) return 0;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const s = samples[i];
    sum += s * s;
  }
  return Math.sqrt(sum / n);
}

/**
 * Valor lineal → dB FS.
 * Piso a -96 para silencio: la UI nunca muestra -Infinity.
 */
export function rmsToDb(linear: number): number {
  if (linear <= 0) return -96;
  return 20 * Math.log10(linear);
}

/** Pico real en dB FS de una ventana floats (0 dBFS = clip). Piso -96. */
export function peakDb(samples: Float32Array | ArrayLike<number>): number {
  let peak = 0;
  const n = samples.length;
  for (let i = 0; i < n; i++) {
    const abs = Math.abs(samples[i]);
    if (abs > peak) peak = abs;
  }
  return rmsToDb(peak);
}

/**
 * Correlación estéreo: E[L·R] / sqrt(E[L²]·E[R²]).
 * -1 = antifase · 0 = descorrelacionado · +1 = mono.
 */
export function correlation(
  l: Float32Array | ArrayLike<number>,
  r: Float32Array | ArrayLike<number>,
): number {
  const n = Math.min(l.length, r.length);
  if (n === 0) return 0;
  let sumLR = 0;
  let sumL2 = 0;
  let sumR2 = 0;
  for (let i = 0; i < n; i++) {
    sumLR += l[i] * r[i];
    sumL2 += l[i] * l[i];
    sumR2 += r[i] * r[i];
  }
  const denom = Math.sqrt(sumL2 * sumR2);
  return denom > 1e-8 ? sumLR / denom : 0;
}

/**
 * Ancho estéreo: RMS(L−R) / RMS(L+R).
 * 0 = mono · ~1 = full stereo · >1 = extra-wide.
 */
export function stereoWidth(
  l: Float32Array | ArrayLike<number>,
  r: Float32Array | ArrayLike<number>,
): number {
  const n = Math.min(l.length, r.length);
  if (n === 0) return 0;
  let sumDiff = 0;
  let sumSum = 0;
  for (let i = 0; i < n; i++) {
    const diff = l[i] - r[i];
    const sum = l[i] + r[i];
    sumDiff += diff * diff;
    sumSum += sum * sum;
  }
  const rmsDiff = Math.sqrt(sumDiff / n);
  const rmsSum = Math.sqrt(sumSum / n);
  return rmsSum > 1e-8 ? rmsDiff / rmsSum : 0;
}

/**
 * Estimación de loudness LUFS desde un nivel RMS lineal.
 *
 * HONESTIDAD > PRECISIÓN: esto NO es ITU-R BS.1770. El estándar requiere
 * K-weighting (filtros IIR de shelving + high-pass), gating absoluto/relativo
 * y ventanas de integración reales. El browser no expone esos filtros sin
 * implementarlos a mano; para un vistazo de 1 segundo, RMS en dB sobre
 * ventanas de ~400 ms / ~3 s es una aproximación aceptable y documentada.
 */
export function lufsFromRms(rmsLinear: number): number {
  return rmsToDb(rmsLinear);
}

/** Estado de color de la correlación, unificado por rango. */
export type CorrState = 'safe' | 'warn' | 'clip';

/**
 * Mapea correlación a estado de color.
 * >= 0.6 → 'safe' · >= 0.3 → 'warn' · < 0.3 → 'clip'.
 */
export function corrState(corr: number): CorrState {
  if (corr >= 0.6) return 'safe';
  if (corr >= 0.3) return 'warn';
  return 'clip';
}

/** Rastreador de loudness de ventana deslizante (ring buffer O(1) por push). */
export interface LoudnessTracker {
  /** Cantidad de frames de la ventana. */
  frames: number;
  /** Push del RMS lineal del frame → LUFS aprox de la ventana actual. */
  push(rmsLinear: number): number;
  /** Último valor computado (sin push). -96 si la ventana está vacía. */
  current(): number;
  /** Vacía la ventana. */
  reset(): void;
}

/**
 * Crea un tracker de loudness de ventana deslizante REAL.
 *
 * Mantiene la suma de cuadrados de los últimos `frames` samples en O(1) por
 * frame (resta el más viejo del ring buffer, suma el nuevo). La ventana es en
 * FRAMES de rAF: a 60 fps, 24 frames ≈ 400 ms y 180 frames ≈ 3 s. Si el
 * monitor corre a otra tasa, la ventana temporal se corre proporcionalmente
 * (aproximación documentada — sigue sin ser BS.1770).
 */
export function createLoudnessTracker(frames: number): LoudnessTracker {
  const ring = new Float64Array(frames);
  let head = 0;
  let filled = 0;
  let sumSq = 0;
  let last = -96;

  return {
    frames,

    push(rmsLinear: number): number {
      const sample = rmsLinear > 0 ? rmsLinear : 0;
      const sq = sample * sample;

      // Ring buffer: sacar el más viejo antes de meter el nuevo.
      if (filled === frames) {
        sumSq -= ring[head];
      } else {
        filled++;
      }
      ring[head] = sq;
      sumSq += sq;
      head = (head + 1) % frames;

      // 10*log10(E[x²]) de la ventana = dBFS del RMS promedio.
      last = rmsToDb(Math.sqrt(sumSq / filled));
      return last;
    },

    current(): number {
      return last;
    },

    reset(): void {
      ring.fill(0);
      head = 0;
      filled = 0;
      sumSq = 0;
      last = -96;
    },
  };
}

/** Tracker de loudness momentánea: ~400 ms (24 frames a 60 fps). */
export function momentaryLoudnessDb(): LoudnessTracker {
  return createLoudnessTracker(24);
}

/** Tracker de loudness de corto término: ~3 s (180 frames a 60 fps). */
export function shortTermLoudnessDb(): LoudnessTracker {
  return createLoudnessTracker(180);
}