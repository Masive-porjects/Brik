/**
 * Live Audio Graph — Web Audio API signal chain for real-time FX.
 * Chain: Source → Filter → Drive → Delay+Feedback → Reverb (Convolver) → Master → Analyser → Destination
 */

import type { LiveParams } from '@/lib/live/liveParams.gen';
import { generateImpulseResponse, IR_PRESETS } from './impulseResponse';

export interface AudioGraphNodes {
  source: AudioBufferSourceNode | MediaElementAudioSourceNode | MediaStreamAudioSourceNode;
  filter: BiquadFilterNode;
  drive: WaveShaperNode;
  delay: DelayNode;
  delayFeedback: GainNode;
  dryGain: GainNode;
  wetGain: GainNode;
  convolver: ConvolverNode;
  masterGain: GainNode;
  analyser: AnalyserNode;
  analyserL: AnalyserNode;
  analyserR: AnalyserNode;
  splitter: ChannelSplitterNode;
  destination: AudioDestinationNode;
}

/** Datos estéreo en tiempo real (canales separados, buffers reutilizados). */
export interface StereoData {
  l: Float32Array;
  r: Float32Array;
}

export interface AudioGraph {
  nodes: AudioGraphNodes;
  audioContext: AudioContext;
  setParams: (params: Partial<LiveParams>) => void;
  setFxPreset: (preset: string) => void;
  start: (loop?: boolean) => void;
  stop: () => void;
  disconnect: () => void;
  getAnalyserData: () => { frequency: Uint8Array; timeDomain: Uint8Array };
  getOutputLevel: () => number; // RMS 0-1
  getStereoData: () => StereoData;
}

/**
 * Create the live audio processing graph.
 * All parameter changes use setTargetAtTime for smooth, click-free transitions.
 */
export function createAudioGraph(
  audioContext: AudioContext,
  audioBuffer: AudioBuffer,
  initialParams: LiveParams = {
    ts: Date.now(),
    filter_cutoff: 12000,
    filter_res: 0.7,
    drive: 0,
    delay_time: 250,
    echo_feedback: 0,
    reverb_mix: 0,
    output_level: 0.9,
    fx_preset: null,
  }
): AudioGraph {
  // ── Create Nodes ─────────────────────────────────────────────────
  const source = audioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.loop = true;

  // Filter: Lowpass with smooth frequency/Q changes
  const filter = audioContext.createBiquadFilter();
  filter.type = 'lowpass';

  // Drive: WaveShaper with tanh curve
  const drive = audioContext.createWaveShaper();
  drive.curve = makeTanhCurve(1); // Initial drive = 0
  drive.oversample = '4x';

  // Delay + Feedback loop
  const delay = audioContext.createDelay(2.0); // Max 2s delay
  const delayFeedback = audioContext.createGain();

  // Dry/Wet for reverb
  const dryGain = audioContext.createGain();
  const wetGain = audioContext.createGain();

  // Convolver for reverb
  const convolver = audioContext.createConvolver();

  // Master gain
  const masterGain = audioContext.createGain();

  // Analyser for visualisation (downmix mono → spectrum + forma de onda)
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 2048;
  analyser.smoothingTimeConstant = 0.3;

  // Analysers estéreo por canal (correlación / width / levels L/R)
  // Tap: splitter 2 canales después de masterGain; NO va al destination.
  const analyserL = audioContext.createAnalyser();
  const analyserR = audioContext.createAnalyser();
  analyserL.fftSize = 2048;
  analyserR.fftSize = 2048;
  analyserL.smoothingTimeConstant = 0.3;
  analyserR.smoothingTimeConstant = 0.3;
  const splitter = audioContext.createChannelSplitter(2);

  // Buffers reutilizados para getStereoData (sin alloc por frame).
  const stereoL = new Float32Array(analyserL.fftSize);
  const stereoR = new Float32Array(analyserR.fftSize);

  // ── Connect Graph ────────────────────────────────────────────────
  // Source → Filter → Drive → [Delay Loop] → Dry/Wet Split → Convolver → Master → [Analyser → Destination] + [Splitter → AnalyserL/R]
  
  source.connect(filter);
  filter.connect(drive);

  // Drive → Delay Input
  drive.connect(delay);
  // Delay → Feedback → Delay (loop)
  delay.connect(delayFeedback);
  delayFeedback.connect(delay);

  // Drive also goes to dry path (bypass delay for dry signal)
  drive.connect(dryGain);

  // Delay output goes to wet path
  delay.connect(wetGain);

  // Dry + Wet → Convolver (reverb)
  dryGain.connect(convolver);
  wetGain.connect(convolver);

  // Convolver → Master → Analyser → Destination
  convolver.connect(masterGain);
  masterGain.connect(analyser);
  analyser.connect(audioContext.destination);

  // Tap estéreo: Master → Splitter → AnalyserL (canal 0) / AnalyserR (canal 1)
  masterGain.connect(splitter);
  splitter.connect(analyserL, 0);
  splitter.connect(analyserR, 1);

  // ── Initial Parameter Values ─────────────────────────────────────
  const now = audioContext.currentTime;
  const SMOOTH_TIME = 0.02; // 20ms ramp for click-free changes

  function setFilter(cutoff: number, Q: number) {
    filter.frequency.setTargetAtTime(cutoff, now, SMOOTH_TIME);
    filter.Q.setTargetAtTime(Q, now, SMOOTH_TIME);
  }

  function setDrive(amount: number) {
    // amount: 0-1, remap to curve index
    const curveIndex = Math.min(9, Math.floor(amount * 10));
    drive.curve = makeTanhCurve(curveIndex);
  }

  function setDelay(timeMs: number, feedback: number) {
    delay.delayTime.setTargetAtTime(timeMs / 1000, now, SMOOTH_TIME);
    delayFeedback.gain.setTargetAtTime(feedback, now, SMOOTH_TIME);
  }

  function setReverbMix(mix: number) {
    // mix: 0-1, dry/wet crossfade
    dryGain.gain.setTargetAtTime(1 - mix, now, SMOOTH_TIME);
    wetGain.gain.setTargetAtTime(mix, now, SMOOTH_TIME);
  }

  function setMasterLevel(level: number) {
    masterGain.gain.setTargetAtTime(level, now, SMOOTH_TIME);
  }

  function loadIR(type: 'plate' | 'hall' | 'room' | 'chamber' | 'spring') {
    const ir = generateImpulseResponse(audioContext, type);
    convolver.buffer = ir;
  }

  // Apply initial params (with defaults for optional params)
  setFilter(initialParams.filter_cutoff ?? 12000, initialParams.filter_res ?? 0.7);
  setDrive(initialParams.drive ?? 0);
  setDelay(initialParams.delay_time ?? 250, initialParams.echo_feedback ?? 0);
  setReverbMix(initialParams.reverb_mix ?? 0);
  setMasterLevel(initialParams.output_level ?? 0.9);
  if (initialParams.fx_preset && IR_PRESETS[initialParams.fx_preset]) {
    loadIR(IR_PRESETS[initialParams.fx_preset]);
  } else {
    loadIR('hall'); // Default
  }

  // ── Public API ───────────────────────────────────────────────────
  return {
    nodes: {
      source,
      filter,
      drive,
      delay,
      delayFeedback,
      dryGain,
      wetGain,
      convolver,
      masterGain,
      analyser,
      analyserL,
      analyserR,
      splitter,
      destination: audioContext.destination,
    },
    audioContext,

    setParams(params: Partial<LiveParams>) {
      const t = audioContext.currentTime;
      if (params.filter_cutoff !== undefined || params.filter_res !== undefined) {
        setFilter(params.filter_cutoff ?? initialParams.filter_cutoff ?? 12000, params.filter_res ?? initialParams.filter_res ?? 0.7);
      }
      if (params.drive !== undefined) {
        setDrive(params.drive);
      }
      if (params.delay_time !== undefined || params.echo_feedback !== undefined) {
        setDelay(params.delay_time ?? initialParams.delay_time ?? 250, params.echo_feedback ?? initialParams.echo_feedback ?? 0);
      }
      if (params.reverb_mix !== undefined) {
        setReverbMix(params.reverb_mix);
      }
      if (params.output_level !== undefined) {
        setMasterLevel(params.output_level);
      }
      if (params.fx_preset !== undefined && params.fx_preset && IR_PRESETS[params.fx_preset]) {
        loadIR(IR_PRESETS[params.fx_preset]);
      }
      // Update initialParams for subsequent calls
      Object.assign(initialParams, params);
    },

    setFxPreset(preset: string) {
      const validPresets = ['clean', 'dub', 'big_room', 'radio'] as const;
      type ValidPreset = typeof validPresets[number];
      if (validPresets.includes(preset as ValidPreset)) {
        loadIR(IR_PRESETS[preset as ValidPreset]);
        initialParams.fx_preset = preset as ValidPreset;
      }
    },

    start(loop = true) {
      source.loop = loop;
      source.start(0);
    },

    stop() {
      source.stop(0);
    },

    disconnect() {
      source.disconnect();
      filter.disconnect();
      drive.disconnect();
      delay.disconnect();
      delayFeedback.disconnect();
      dryGain.disconnect();
      wetGain.disconnect();
      convolver.disconnect();
      masterGain.disconnect();
      analyser.disconnect();
      analyserL.disconnect();
      analyserR.disconnect();
      splitter.disconnect();
    },

    getAnalyserData() {
      const freqData = new Uint8Array(analyser.frequencyBinCount);
      const timeData = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(freqData);
      analyser.getByteTimeDomainData(timeData);
      return { frequency: freqData, timeDomain: timeData };
    },

    getOutputLevel(): number {
      const timeData = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteTimeDomainData(timeData);
      // RMS from time domain
      let sum = 0;
      for (let i = 0; i < timeData.length; i++) {
        const sample = (timeData[i] - 128) / 128; // -1 to 1
        sum += sample * sample;
      }
      return Math.sqrt(sum / timeData.length);
    },

    getStereoData(): StereoData {
      // Buffers reutilizados: cero allocations en el hot path (60 fps).
      analyserL.getFloatTimeDomainData(stereoL);
      analyserR.getFloatTimeDomainData(stereoR);
      return { l: stereoL, r: stereoR };
    },
  };
}

/**
 * Generate tanh distortion curves for WaveShaper.
 * Index 0 = clean, 9 = heavy distortion.
 */
function makeTanhCurve(index: number): Float32Array<ArrayBuffer> {
  const samples = 4096;
  const curve = new Float32Array(new ArrayBuffer(samples * 4));
  const drive = index / 9; // 0 to 1
  const maxDrive = 20; // Max gain before tanh

  for (let i = 0; i < samples; i++) {
    const x = (i / (samples - 1)) * 2 - 1; // -1 to 1
    const driven = x * (1 + drive * maxDrive);
    curve[i] = Math.tanh(driven);
  }
  return curve;
}

/**
 * Factory to create graph from a mastered audio buffer URL.
 * Handles loading and decoding.
 */
export async function createAudioGraphFromUrl(
  audioContext: AudioContext,
  url: string,
  initialParams?: Partial<LiveParams>
): Promise<AudioGraph> {
  const response = await fetch(url);
  const arrayBuffer = await response.arrayBuffer();
  const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
  
  const params: LiveParams = {
    ts: Date.now(),
    filter_cutoff: 12000,
    filter_res: 0.7,
    drive: 0,
    delay_time: 250,
    echo_feedback: 0,
    reverb_mix: 0,
    output_level: 0.9,
    fx_preset: null,
    ...initialParams,
  };

  return createAudioGraph(audioContext, audioBuffer, params);
}