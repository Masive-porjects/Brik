/**
 * meterMath — tests de matemática pura del Live Meter Deck.
 */
import { describe, it, expect } from 'vitest';
import {
  clamp,
  rms,
  rmsToDb,
  peakDb,
  correlation,
  stereoWidth,
  lufsFromRms,
  corrState,
  createLoudnessTracker,
  momentaryLoudnessDb,
  shortTermLoudnessDb,
} from './meterMath';

/** Seno de N muestras: RMS teórico = 1/√2 ≈ 0.7071. */
function sine(n: number, amplitude = 1): Float32Array {
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    out[i] = amplitude * Math.sin((2 * Math.PI * i) / n);
  }
  return out;
}

describe('clamp', () => {
  it('acota dentro del rango', () => {
    expect(clamp(5, 0, 1)).toBe(1);
    expect(clamp(-5, 0, 1)).toBe(0);
    expect(clamp(0.5, 0, 1)).toBe(0.5);
  });
});

describe('rms', () => {
  it('un seno completo tiene RMS 1/√2', () => {
    expect(rms(sine(1024))).toBeCloseTo(1 / Math.SQRT2, 4);
  });

  it('silencio → 0', () => {
    expect(rms(new Float32Array(64))).toBe(0);
  });

  it('ventana vacía → 0 (sin NaN)', () => {
    expect(rms(new Float32Array(0))).toBe(0);
  });
});

describe('rmsToDb', () => {
  it('1 → 0 dBFS y 0.5 → ~-6.02 dBFS', () => {
    expect(rmsToDb(1)).toBeCloseTo(0, 6);
    expect(rmsToDb(0.5)).toBeCloseTo(-6.0206, 3);
  });

  it('silencio → piso de -96 (nunca -Infinity)', () => {
    expect(rmsToDb(0)).toBe(-96);
    expect(rmsToDb(-1)).toBe(-96);
  });
});

describe('peakDb', () => {
  it('detecta el pico de una ventana', () => {
    const win = new Float32Array(128);
    win[64] = 0.9;
    expect(peakDb(win)).toBeCloseTo(20 * Math.log10(0.9), 4);
  });

  it('silencio → -96', () => {
    expect(peakDb(new Float32Array(32))).toBe(-96);
  });
});

describe('correlation', () => {
  it('canales idénticos → +1 (mono)', () => {
    const l = sine(512);
    expect(correlation(l, l)).toBeCloseTo(1, 6);
  });

  it('canales invertidos → -1 (antifase)', () => {
    const l = sine(512);
    const r = sine(512, -1);
    expect(correlation(l, r)).toBeCloseTo(-1, 6);
  });

  it('ortogonales → ~0 (descorrelacionado)', () => {
    const l = new Float32Array([1, -1, 1, -1]);
    const r = new Float32Array([1, 1, -1, -1]);
    expect(correlation(l, r)).toBeCloseTo(0, 6);
  });

  it('silencio → 0 (sin NaN)', () => {
    expect(correlation(new Float32Array(64), new Float32Array(64))).toBe(0);
  });
});

describe('stereoWidth', () => {
  it('mono (L==R) → 0', () => {
    const l = sine(512);
    expect(stereoWidth(l, l)).toBeCloseTo(0, 6);
  });

  it('L solo (R en silencio) → 1', () => {
    const l = sine(512);
    expect(stereoWidth(l, new Float32Array(512))).toBeCloseTo(1, 4);
  });

  it('silencio → 0 (sin NaN)', () => {
    expect(stereoWidth(new Float32Array(64), new Float32Array(64))).toBe(0);
  });
});

describe('lufsFromRms', () => {
  it('es la misma escala dBFS del RMS (aproximación documentada, NO BS.1770)', () => {
    expect(lufsFromRms(1)).toBeCloseTo(0, 6);
    expect(lufsFromRms(0.5)).toBeCloseTo(-6.0206, 3);
  });
});

describe('corrState', () => {
  it('>= 0.6 → safe', () => {
    expect(corrState(1)).toBe('safe');
    expect(corrState(0.6)).toBe('safe');
    expect(corrState(0.61)).toBe('safe');
  });

  it('[0.3, 0.6) → warn', () => {
    expect(corrState(0.59)).toBe('warn');
    expect(corrState(0.3)).toBe('warn');
    expect(corrState(0.45)).toBe('warn');
  });

  it('< 0.3 → clip', () => {
    expect(corrState(0.29)).toBe('clip');
    expect(corrState(0)).toBe('clip');
    expect(corrState(-1)).toBe('clip');
  });
});

describe('createLoudnessTracker — ventana deslizante REAL', () => {
  it('señal constante → valor estable = dBFS del RMS', () => {
    const t1 = createLoudnessTracker(24);
    for (let i = 0; i < 100; i++) t1.push(1); // 0 dBFS
    expect(t1.current()).toBeCloseTo(0, 4);

    const t2 = createLoudnessTracker(24);
    for (let i = 0; i < 100; i++) t2.push(0.5); // -6.02 dBFS
    expect(t2.current()).toBeCloseTo(-6.0206, 3);
  });

  it('la ventana es real: al cortar la señal, cae al piso tras `frames` pushes', () => {
    const t = createLoudnessTracker(4);
    for (let i = 0; i < 4; i++) t.push(1);
    expect(t.current()).toBeCloseTo(0, 4);
    for (let i = 0; i < 4; i++) t.push(0);
    expect(t.current()).toBe(-96);
  });

  it('transición: una ventana parcial mezcla los frames', () => {
    const t = createLoudnessTracker(2);
    t.push(1);
    t.push(1); // [1,1] → 0 dB
    t.push(0); // [1,0] → RMS=√0.5 → -3.01 dB
    expect(t.current()).toBeCloseTo(-3.0103, 3);
  });

  it('vacío → -96 (sin NaN) y reset limpia la ventana', () => {
    const t = createLoudnessTracker(8);
    expect(t.current()).toBe(-96);
    t.push(1);
    t.reset();
    expect(t.current()).toBe(-96);
    expect(t.frames).toBe(8);
  });

  it('momentánea = 24 frames (~400ms a 60fps) y corto término = 180 frames (~3s)', () => {
    expect(momentaryLoudnessDb().frames).toBe(24);
    expect(shortTermLoudnessDb().frames).toBe(180);
  });
});