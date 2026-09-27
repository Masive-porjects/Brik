/**
 * useLiveEngine — tests de regresión y robustez.
 *
 * 1. Regresión del glitch: el grafo de audio se crea UNA sola vez aunque
 *    params cambie (bug: la dep [params] recreaba el grafo en cada
 *    cambio → el audio se cortaba al girar un knob).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLiveEngine } from '@/adapters/live/useLiveEngine';

// Hoisted mock para poder espiar desde el factory de vi.mock
const { createAudioGraphMock } = vi.hoisted(() => ({
  createAudioGraphMock: vi.fn(),
}));

vi.mock('@/adapters/live/audioGraph', () => ({
  createAudioGraph: (...args: unknown[]) => createAudioGraphMock(...args),
}));

vi.mock('@/adapters/live/recorder', () => ({
  createRecorder: vi.fn(() => ({
    start: vi.fn(),
    stop: vi.fn(),
    download: vi.fn(),
    cleanup: vi.fn(),
  })),
}));

vi.mock('@/adapters/live/fxPresets', () => ({
  applyPreset: (p: unknown) => p,
  FX_PRESETS: {},
}));

// AudioContext no existe en jsdom → stub mínimo
class MockAudioContext {
  state = 'running';
  currentTime = 0;
  destination = {};
  resume = vi.fn();
  close = vi.fn();
}

beforeEach(() => {
  vi.stubGlobal('AudioContext', MockAudioContext);
  createAudioGraphMock.mockReset();
  // El mock devuelve un graph con la API mínima que el hook usa
  createAudioGraphMock.mockReturnValue({
    nodes: { masterGain: { connect: vi.fn() } },
    audioContext: null,
    setParams: vi.fn(),
    setFxPreset: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    disconnect: vi.fn(),
    getAnalyserData: vi.fn(() => ({ frequency: new Uint8Array(0), timeDomain: new Uint8Array(0) })),
    getOutputLevel: vi.fn(() => 0),
    getStereoData: vi.fn(() => ({ l: new Float32Array(2048), r: new Float32Array(2048) })),
  });
});

describe('useLiveEngine — regresión del glitch', () => {
  it('no recrea el grafo al cambiar params (regresión: dep [params] lo recreaba)', () => {
    const buffer = {} as AudioBuffer;

    const { result } = renderHook(() => useLiveEngine({ masterAudioBuffer: buffer }));

    // Grafo creado al llegar el buffer
    expect(createAudioGraphMock).toHaveBeenCalledTimes(1);

    // Simula giros de knob
    act(() => { result.current.setParams({ drive: 0.8 }); });
    act(() => { result.current.setParams({ drive: 0.9 }); });
    act(() => { result.current.setParams({ reverb_mix: 0.3 }); });

    // Con el bug: 4 llamadas (recreación por cada cambio).
    // Con el fix: sigue siendo 1.
    expect(createAudioGraphMock).toHaveBeenCalledTimes(1);
  });
});
