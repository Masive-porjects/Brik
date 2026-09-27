"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { safeCloseAudioContext } from "@/lib/live/audioContextUtils";

/* ── Stereo Field Analysis Hook ─────────────────────────────
   Decodes an audio URL into a stereo buffer, then analyses the
   L/R channel relationship in real time to produce:
     - correlation: -1 (anti-phase) → 0 (uncorrelated) → +1 (mono)
     - width: 0 (mono) → 1 (full stereo) → >1 (extra-wide)
     - lData / rData: raw channel snapshots for goniometer rendering

   The consumer owns the AudioContext lifecycle via start/stop.
   ──────────────────────────────────────────────────────────── */

export interface StereoFieldData {
  /** Whether the analysis pipeline is running. */
  active: boolean;
  /** Whether a file has been decoded and is ready for analysis. */
  ready: boolean;
  /** Error message if decoding/analysis failed. */
  error: string | null;
  /** Average stereo correlation over the analysis window. */
  correlation: number;
  /** Stereo width metric (0 = mono, 1 = normal, >1 = wide). */
  width: number;
  /** RMS level of the left channel (0–1). */
  levelL: number;
  /** RMS level of the right channel (0–1). */
  levelR: number;
  /** Raw L channel time-domain data (updated per animation frame). */
  lData: Float32Array | null;
  /** Raw R channel time-domain data (updated per animation frame). */
  rData: Float32Array | null;
  /** Start analysis. */
  start: () => void;
  /** Stop analysis (releases resources). */
  stop: () => void;
}

export function useStereoField(
  audioUrl: string | null,
): StereoFieldData {
  const [active, setActive] = useState(false);
  const [ready, setReady] = useState(false);
  const [correlation, setCorrelation] = useState(0);
  const [width, setWidth] = useState(0);
  const [levelL, setLevelL] = useState(0);
  const [levelR, setLevelR] = useState(0);
  const [lData, setLData] = useState<Float32Array | null>(null);
  const [rData, setRData] = useState<Float32Array | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ctxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const analyserLRef = useRef<AnalyserNode | null>(null);
  const analyserRRef = useRef<AnalyserNode | null>(null);
  const splitterRef = useRef<ChannelSplitterNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const bufferRef = useRef<AudioBuffer | null>(null);

  /* ── Decode audio URL into a buffer ─────────────────── */
  const decodeAudio = useCallback(async (url: string, ctx?: AudioContext) => {
    try {
      const decodeCtx = ctx ?? ctxRef.current;
      if (!decodeCtx) return;

      // Resume if suspended (autoplay policy)
      if (decodeCtx.state === "suspended") {
        await decodeCtx.resume();
      }

      setError(null);
      const res = await fetch(url);
      if (!res.ok) {
        setError(`Error ${res.status}: no se pudo cargar el audio`);
        return;
      }
      const arrayBuf = await res.arrayBuffer();

      // Timeout-safe decode (10s)
      const decoded = await Promise.race([
        decodeCtx.decodeAudioData(arrayBuf),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("Decode timeout")), 10000),
        ),
      ]);

      bufferRef.current = decoded;
      setReady(decoded.numberOfChannels >= 2);
      setError(decoded.numberOfChannels < 2 ? "Audio mono — se necesita estéreo" : null);
    } catch (e) {
      setReady(false);
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === "Decode timeout") {
        setError("Tiempo de espera agotado — el audio es muy largo o la red es lenta");
      } else {
        setError("No se pudo decodificar el audio. Verificá la conexión.");
      }
    }
  }, []);

  /* ── Pre-decode on mount ──────────────────────────────
     Create a throwaway AudioContext just for decoding so
     `ready` becomes true before the user clicks anything. */
  useEffect(() => {
    if (!audioUrl || bufferRef.current) return;

    let disposed = false;
    const preCtx = new AudioContext();

    decodeAudio(audioUrl, preCtx).then(() => {
      // safeClose es idempotente: si el cleanup ya cerró preCtx (Strict Mode /
      // carrera), esto es no-op en vez de InvalidStateError.
      void safeCloseAudioContext(preCtx);
    });

    return () => {
      disposed = true;
      void safeCloseAudioContext(preCtx);
    };
  }, [audioUrl, decodeAudio]);

  /* ── Analysis loop ────────────────────────────────────
     readFrame como function declaration (hoisted): permite la
     auto-referencia del requestAnimationFrame sin TDZ. */
  function readFrame() {
    const analyserL = analyserLRef.current;
    const analyserR = analyserRRef.current;
    if (!analyserL || !analyserR) return;

    const fftSize = 2048;
    const bufL = new Float32Array(fftSize);
    const bufR = new Float32Array(fftSize);

    analyserL.getFloatTimeDomainData(bufL);
    analyserR.getFloatTimeDomainData(bufR);

    // Snapshot for goniometer (downsample to 512 for performance)
    const snapshotSize = 512;
    const snapL = new Float32Array(snapshotSize);
    const snapR = new Float32Array(snapshotSize);
    const step = Math.floor(fftSize / snapshotSize);
    for (let i = 0; i < snapshotSize; i++) {
      snapL[i] = bufL[i * step];
      snapR[i] = bufR[i * step];
    }
    setLData(snapL);
    setRData(snapR);

    // Compute correlation: E[L×R] / (E[L²] × E[R²])^0.5
    let sumLR = 0;
    let sumL2 = 0;
    let sumR2 = 0;
    for (let i = 0; i < fftSize; i++) {
      sumLR += bufL[i] * bufR[i];
      sumL2 += bufL[i] * bufL[i];
      sumR2 += bufR[i] * bufR[i];
    }
    const denom = Math.sqrt(sumL2 * sumR2);
    const corr = denom > 0.0001 ? sumLR / denom : 0;
    setCorrelation(corr);

    // Width: ratio of difference signal to sum signal
    let sumDiff = 0;
    let sumSum = 0;
    for (let i = 0; i < fftSize; i++) {
      const diff = bufL[i] - bufR[i];
      const sum = bufL[i] + bufR[i];
      sumDiff += diff * diff;
      sumSum += sum * sum;
    }
    const rmsDiff = Math.sqrt(sumDiff / fftSize);
    const rmsSum = Math.sqrt(sumSum / fftSize);
    const w = rmsSum > 0.0001 ? rmsDiff / rmsSum : 0;
    setWidth(w);

    // Channel levels
    let rmsL = 0;
    let rmsR = 0;
    for (let i = 0; i < fftSize; i++) {
      rmsL += bufL[i] * bufL[i];
      rmsR += bufR[i] * bufR[i];
    }
    setLevelL(Math.sqrt(rmsL / fftSize));
    setLevelR(Math.sqrt(rmsR / fftSize));

    rafRef.current = requestAnimationFrame(readFrame);
  }

  // readFrame solo usa refs y setters estables (sin closure stale), y es
  // recreada en cada render — incluirla en deps rompería la estabilidad del useCallback.
  const analyse = useCallback(() => {
    readFrame();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- readFrame: solo refs+setters estables

  /* ── Start / Stop ───────────────────────────────────── */
  const start = useCallback(async () => {
    if (active) return;
    setError(null);

    // Create context for playback + analysis
    const ctx = new AudioContext();
    ctxRef.current = ctx;

    // Resume if suspended (autoplay policy)
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        setError("No se pudo iniciar el audio. Prueba de nuevo.");
        return;
      }
    }

    // Decode only if pre-decode hasn't completed yet
    if (!bufferRef.current && audioUrl) {
      await decodeAudio(audioUrl);
    }

    const buffer = bufferRef.current;
    if (!buffer) {
      // decodeAudio already set the error
      return;
    }
    if (buffer.numberOfChannels < 2) {
      setError("Audio mono — se necesita estéreo para esta visualización");
      return;
    }

    // Build graph: Source → Splitter → AnalyserL + AnalyserR
    const source = ctx.createBufferSource();
    source.buffer = buffer;

    const splitter = ctx.createChannelSplitter(2);
    const analyserL = ctx.createAnalyser();
    analyserL.fftSize = 2048;
    const analyserR = ctx.createAnalyser();
    analyserR.fftSize = 2048;

    source.connect(splitter);
    splitter.connect(analyserL, 0);
    splitter.connect(analyserR, 1);

    sourceRef.current = source;
    splitterRef.current = splitter;
    analyserLRef.current = analyserL;
    analyserRRef.current = analyserR;

    source.start(0);
    setActive(true);

    // Start analysis loop
    rafRef.current = requestAnimationFrame(analyse);
  }, [active, audioUrl, decodeAudio, analyse]);

  const stop = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    try {
      sourceRef.current?.stop();
    } catch {
      // Already stopped
    }
    sourceRef.current?.disconnect();
    splitterRef.current?.disconnect();
    analyserLRef.current?.disconnect();
    analyserRRef.current?.disconnect();

    void safeCloseAudioContext(ctxRef.current);

    ctxRef.current = null;
    sourceRef.current = null;
    splitterRef.current = null;
    analyserLRef.current = null;
    analyserRRef.current = null;

    setActive(false);
    setCorrelation(0);
    setWidth(0);
    setLevelL(0);
    setLevelR(0);
    setLData(null);
    setRData(null);
  }, []);

  /* ── Re-decode when URL changes ───────────────────────
     Reset de estado en fase de render (patrón recomendado por React:
     ajustar estado cuando cambia una prop). El efecto solo hace el
     side-effect (decodificar), sin setState síncrono. */
  const [prevUrl, setPrevUrl] = useState(audioUrl);
  if (prevUrl !== audioUrl) {
    setPrevUrl(audioUrl);
    setReady(false);
  }

  useEffect(() => {
    bufferRef.current = null;
    if (audioUrl && ctxRef.current) {
      decodeAudio(audioUrl);
    }
  }, [audioUrl, decodeAudio]);

  /* ── Cleanup on unmount ─────────────────────────────── */
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      try { sourceRef.current?.stop(); } catch { /* */ }
      void safeCloseAudioContext(ctxRef.current);
    };
  }, []);

  return {
    active,
    ready,
    error,
    correlation,
    width,
    levelL,
    levelR,
    lData,
    rData,
    start,
    stop,
  };
}
