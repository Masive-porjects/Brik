/**
 * useLiveEngine — React hook orchestrating the standalone Live Engine.
 * Manages: AudioContext, AudioGraph, Recorder, and UI state.
 * No WebSocket: params come exclusively from the knob UI (mouse/keyboard).
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import type { LiveParams } from '@/lib/live/liveParams.gen';
import { createAudioGraph, AudioGraph } from './audioGraph';
import { createRecorder, RecorderState } from './recorder';
import { applyPreset, FX_PRESETS, FxPresetName } from './fxPresets';
import { LIVE_PARAM_DEFAULTS } from '@/lib/live/liveDefaults';
import { publish, reset } from '@/lib/live/liveMeterBus';
import { safeCloseAudioContext } from '@/lib/live/audioContextUtils';
import { rms, peakDb, correlation, stereoWidth, momentaryLoudnessDb, shortTermLoudnessDb } from '@/lib/live/meterMath';

export interface UseLiveEngineOptions {
  /** Master audio buffer (from WaveAI mastering) */
  masterAudioBuffer: AudioBuffer | null;
  /** AudioContext (shared or created internally) */
  audioContext?: AudioContext;
  /** Initial LiveParams */
  initialParams?: Partial<LiveParams>;
  /** Callbacks */
  onParamsChange?: (params: LiveParams) => void;
  onError?: (error: Error) => void;
}

export interface UseLiveEngineReturn {
  // State
  params: LiveParams;
  recorderState: RecorderState;
  isPlaying: boolean;

  // Actions
  setParams: (params: Partial<LiveParams>) => void;
  setFxPreset: (preset: FxPresetName) => void;
  play: () => void;
  pause: () => void;
  stop: () => void;
  startRecording: () => void;
  stopRecording: () => void;
  downloadRecording: (filename?: string) => void;

  // Cleanup
  destroy: () => void;
}

/**
 * Main hook for the standalone Live Engine (knob-controlled).
 * Pipeline: Knobs → LiveParams → AudioGraph → Recorder.
 */
export function useLiveEngine(options: UseLiveEngineOptions): UseLiveEngineReturn {
  const {
    masterAudioBuffer,
    audioContext: providedContext,
    initialParams = {},
    onParamsChange,
    onError,
  } = options;

  // ── Refs for persistent objects ──────────────────────────────────
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioGraphRef = useRef<AudioGraph | null>(null);
  const recorderRef = useRef<ReturnType<typeof createRecorder> | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  /** Guard de dispose idempotente: destroy() no debe cerrar el ctx dos veces. */
  const disposedRef = useRef(false);

  // ── React State ──────────────────────────────────────────────────
  const [params, setParamsState] = useState<LiveParams>(() => ({
    ...LIVE_PARAM_DEFAULTS,
    ts: Date.now(),
    ...initialParams,
  }));
  const [recorderState, setRecorderState] = useState<RecorderState>({
    recording: false,
    paused: false,
    duration: 0,
    blob: null,
    url: null,
    mimeType: null,
    extension: null,
  });
  const [isPlaying, setIsPlaying] = useState(false);

  // Latest-value ref: lets the audio graph effect read current params
  // WITHOUT re-running (and recreating the graph) on every param change.
  // Synced via effect (React 19 forbids writing refs during render).
  const paramsRef = useRef(params);
  useEffect(() => {
    paramsRef.current = params;
  }, [params]);

  // ── Initialize AudioContext ──────────────────────────────────────
  // StrictMode / Fast Refresh pueden haber cerrado el ctx vía destroy() en un
  // ciclo anterior: si quedó "closed", descartarlo y crear uno fresco. Nunca
  // se reusa un contexto cerrado (crear nodos sobre él también lanza
  // InvalidStateError).
  useEffect(() => {
    if (audioContextRef.current?.state === 'closed') {
      audioContextRef.current = null;
    }
    if (!audioContextRef.current) {
      disposedRef.current = false; // nuevo dueño de contexto → destroy revive
      const ctx = providedContext || new AudioContext({ latencyHint: 'interactive' });
      audioContextRef.current = ctx;
    }
  }, [providedContext]);

  // ── Initialize AudioGraph when buffer is ready ───────────────────
  useEffect(() => {
    const ctx = audioContextRef.current;
    if (!ctx || !masterAudioBuffer || audioGraphRef.current) return;

    // Resume context if suspended (browser autoplay policy)
    if (ctx.state === 'suspended') {
      ctx.resume();
    }

    const graph = createAudioGraph(ctx, masterAudioBuffer, paramsRef.current);
    audioGraphRef.current = graph;

    // Connect recorder to master output
    const recorder = createRecorder(ctx, {
      onStop: (blob, url) => {
        setRecorderState(prev => ({ ...prev, recording: false, blob, url }));
      },
      onError: (err) => onError?.(err),
    });
    recorderRef.current = recorder;
    if (recorder.mediaStreamDestination) {
      graph.nodes.masterGain.connect(recorder.mediaStreamDestination);
    }

    return () => {
      graph.disconnect();
      audioGraphRef.current = null;
      if (recorderRef.current) {
        recorderRef.current.cleanup();
        recorderRef.current = null;
      }
    };
  }, [masterAudioBuffer]);

  // ── Meter Loop → Bus (sin React state por frame) ────────────────
  // ANTI-PATRÓN eliminado: antes este loop escribía state por frame (re-render
  // React a 60fps). Ahora computa un LiveMeterReading y lo publica en
  // liveMeterBus; los meters se suscriben y dibujan en canvas sin involucrar
  // al reconciler. Deps [masterAudioBuffer]: si el buffer llega
  // DESPUÉS del mount (caso real: master async), el loop arranca recién ahí
  // (bug latente: con deps [] el loop moría temprano con graph null).
  useEffect(() => {
    if (!masterAudioBuffer) return;

    // Ventanas deslizantes por instancia de grafo: MOM ~400ms (24 frames),
    // ST ~3s (180 frames) — aproximación documentada, NO BS.1770.
    const momentary = momentaryLoudnessDb();
    const shortTerm = shortTermLoudnessDb();

    const tick = () => {
      const graph = audioGraphRef.current;
      if (!graph) {
        // Sin grafo: silencio inmediato en el bus (no congelar el último frame).
        reset();
        animationFrameRef.current = requestAnimationFrame(tick);
        return;
      }

      const { frequency, timeDomain } = graph.getAnalyserData();
      const { l, r } = graph.getStereoData();
      const level = graph.getOutputLevel();
      const levelL = rms(l);
      const levelR = rms(r);

      publish({
        frequency,
        timeDomain,
        outputLevel: level,
        levelL,
        levelR,
        peakL: peakDb(l),
        peakR: peakDb(r),
        correlation: correlation(l, r),
        width: stereoWidth(l, r),
        momentaryLufs: momentary.push(level),
        shortTermLufs: shortTerm.push(level),
        ts: Date.now(),
      });

      animationFrameRef.current = requestAnimationFrame(tick);
    };
    animationFrameRef.current = requestAnimationFrame(tick);

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      reset();
    };
  }, [masterAudioBuffer]);

  // ── Parameter Setters ────────────────────────────────────────────
  const setParams = useCallback((newParams: Partial<LiveParams>) => {
    setParamsState(prev => {
      const merged = { ...prev, ...newParams, ts: Date.now() };
      audioGraphRef.current?.setParams(newParams);
      onParamsChange?.(merged);
      return merged;
    });
  }, [onParamsChange]);

  const setFxPreset = useCallback((preset: FxPresetName) => {
    setParamsState(prev => {
      const next = applyPreset(prev, preset);
      audioGraphRef.current?.setFxPreset(preset);
      onParamsChange?.(next);
      return next;
    });
  }, [onParamsChange]);

  // ── Transport Controls ───────────────────────────────────────────
  const play = useCallback(() => {
    // Limpiar el frame viejo en el bus antes de arrancar: los meters
    // muestran silencio hasta que el primer frame real de audio llega.
    reset();
    audioGraphRef.current?.start(true);
    setIsPlaying(true);
  }, []);

  const pause = useCallback(() => {
    audioGraphRef.current?.stop();
    setIsPlaying(false);
    reset();
  }, []);

  const stop = useCallback(() => {
    audioGraphRef.current?.stop();
    setIsPlaying(false);
    reset();
  }, []);

  // ── Recorder Controls ────────────────────────────────────────────
  const startRecording = useCallback(() => {
    recorderRef.current?.start();
    setRecorderState(prev => ({ ...prev, recording: true, paused: false, duration: 0 }));
  }, []);

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    // State updated via onStop callback
  }, []);

  const downloadRecording = useCallback((filename?: string) => {
    recorderRef.current?.download(filename);
  }, []);

  // ── Cleanup ──────────────────────────────────────────────────────
  // Idempotente: StrictMode/Fast Refresh montan y desmontan efectos varias
  // veces; el primer destroy cierra el ctx, los siguientes no-op. El ref se
  // nulifica ANTES del close para que un init posterior cree uno fresco.
  const destroy = useCallback(() => {
    if (disposedRef.current) return;
    disposedRef.current = true;

    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    audioGraphRef.current?.disconnect();
    audioGraphRef.current = null;
    recorderRef.current?.cleanup();
    recorderRef.current = null;

    // Owner del AudioContext interno: cerrar UNA vez. Un contexto provisto
    // por el caller (providedContext) lo cierra el caller, no nosotros.
    const ctx = audioContextRef.current;
    audioContextRef.current = null;
    if (ctx && !providedContext) {
      void safeCloseAudioContext(ctx);
    }
  }, [providedContext]);

  useEffect(() => {
    return () => destroy();
  }, [destroy]);

  return {
    // State
    params,
    recorderState,
    isPlaying,
    // Actions
    setParams,
    setFxPreset,
    play,
    pause,
    stop,
    startRecording,
    stopRecording,
    downloadRecording,
    destroy,
  };
}
