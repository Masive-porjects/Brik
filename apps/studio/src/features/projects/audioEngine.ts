"use client";

import { audioEngine as sharedAudioEngine } from "@/adapters/audio/engine";
import type { StemName } from "@/features/projects/store/mixStateStore";

/** Represents a loaded stem with its audio buffer and gain node. */
export interface LoadedStem {
  name: StemName;
  buffer: AudioBuffer | null;
  source: AudioBufferSourceNode | null;
  gainNode: GainNode | null;
  panNode: StereoPannerNode | null;
  isPlaying: boolean;
  startOffset: number; // for pause/resume
  solo?: boolean;
  mute?: boolean;
}

/** Result of loading a stem from a URL. */
export interface LoadStemResult {
  stem: StemName;
  buffer: AudioBuffer;
  duration: number;
}

/** Engine events for UI synchronization. */
export type AudioEngineEvent =
  | { type: "play" }
  | { type: "pause" }
  | { type: "stop" }
  | { type: "timeupdate"; currentTime: number; duration: number }
  | { type: "ended" }
  | { type: "error"; error: Error }
  | { type: "loaded"; stem: StemName; duration: number };

type EventListener = (event: AudioEngineEvent) => void;

/** Minimal Tone.js surface used to grab the shared AudioContext. */
interface ToneApi {
  getContext: () => { rawContext: AudioContext };
}

/**
 * Multi-stem AudioEngine for synchronized 4-stem playback.
 * 
 * Features:
 * - Loads 4 stems (drums, bass, other, vocals) from signed URLs
 * - Individual fader control per stem (gain in dB)
 * - Mute/Solo per stem
 * - Synchronized playback with single transport
 * - Per-stem panning support
 * - Event-based UI synchronization
 */
export class AudioEngine {
  private audioContext: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private masterLimiter: DynamicsCompressorNode | null = null;
  private stems: Map<StemName, LoadedStem> = new Map();
  private isPlaying = false;
  private startTime = 0;
  private pauseTime = 0;
  private animationFrameId: number | null = null;
  private listeners = new Set<EventListener>();
  private loadingPromises = new Map<StemName, Promise<LoadStemResult>>();

  /** Initializes the AudioContext and master bus (must be called from user gesture). */
  async initialize(): Promise<void> {
    if (this.audioContext) return;

    // Initialize the shared engine from adapters/audio/engine.ts
    await sharedAudioEngine.ensureStarted();

    // Use the shared AudioContext from Tone.js
    const toneModule = (await import("tone")) as unknown as ToneApi & {
      default?: ToneApi;
    };
    const toneApi: ToneApi = toneModule.default ?? toneModule;
    this.audioContext = toneApi.getContext().rawContext;

    // Create master gain and limiter chain
    const ctx = this.audioContext!;
    this.masterGain = ctx.createGain();
    this.masterGain.gain.value = 0.9; // match backend master bus

    this.masterLimiter = ctx.createDynamicsCompressor();
    this.masterLimiter.threshold.value = -1;
    this.masterLimiter.knee.value = 0;
    this.masterLimiter.ratio.value = 20;
    this.masterLimiter.attack.value = 0.001;
    this.masterLimiter.release.value = 0.1;

    this.masterGain.connect(this.masterLimiter);
    this.masterLimiter.connect(ctx.destination);

    // Initialize stem slots
    const stemNames: StemName[] = ["drums", "bass", "other", "vocals"];
    for (const name of stemNames) {
      this.stems.set(name, {
        name,
        buffer: null,
        source: null,
        gainNode: null,
        panNode: null,
        isPlaying: false,
        startOffset: 0,
      });
    }
  }

  /** Loads a stem from a signed URL into an AudioBuffer. */
  async loadStem(stem: StemName, url: string): Promise<LoadStemResult> {
    if (!this.audioContext) await this.initialize();

    // Deduplicate concurrent loads for same stem
    if (this.loadingPromises.has(stem)) {
      return this.loadingPromises.get(stem)!;
    }

    const promise = (async () => {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to load ${stem}: ${response.status}`);
      }
      const arrayBuffer = await response.arrayBuffer();
      const buffer = await this.audioContext!.decodeAudioData(arrayBuffer);

      // Create gain and pan nodes for this stem
      const gainNode = this.audioContext!.createGain();
      const panNode = this.audioContext!.createStereoPanner();

      // Connect: gain -> pan -> masterGain
      gainNode.connect(this.masterGain!);
      panNode.connect(this.masterGain!);

      // Update stem slot
      const stemData = this.stems.get(stem)!;
      stemData.buffer = buffer;
      stemData.gainNode = gainNode;
      stemData.panNode = panNode;
      stemData.isPlaying = false;
      stemData.startOffset = 0;

      this.loadingPromises.delete(stem);
      const result: LoadStemResult = { stem, buffer, duration: buffer.duration };
      this.emit({ type: "loaded", stem, duration: buffer.duration });
      return result;
    })();

    this.loadingPromises.set(stem, promise);
    return promise;
  }

  /** Loads all 4 stems in parallel. */
  async loadAllStems(
    urls: Record<StemName, string>
  ): Promise<Record<StemName, LoadStemResult>> {
    const results = await Promise.all(
      (["drums", "bass", "other", "vocals"] as StemName[]).map((stem) =>
        this.loadStem(stem, urls[stem])
      )
    );
    return Object.fromEntries(
      results.map((r) => [r.stem, r])
    ) as Record<StemName, LoadStemResult>;
  }

  /** Sets fader level for a stem (in dB, -60 to +12). */
  setFader(stem: StemName, levelDb: number): void {
    const stemData = this.stems.get(stem);
    if (!stemData || !stemData.gainNode) return;

    // Clamp and convert dB to linear gain
    const clamped = Math.max(-60, Math.min(12, levelDb));
    const linearGain = Math.pow(10, clamped / 20);
    stemData.gainNode.gain.value = linearGain;
  }

  /** Sets mute state for a stem. */
  setMute(stem: StemName, muted: boolean): void {
    const stemData = this.stems.get(stem);
    if (!stemData || !stemData.gainNode) return;
    stemData.gainNode.gain.value = muted ? 0 : stemData.gainNode.gain.value;
  }

  /** Sets solo state (mutes all other stems). */
  setSolo(stem: StemName, solo: boolean): void {
    // Solo logic: when any stem is soloed, mute all others
    for (const [name, data] of this.stems) {
      if (name === stem) {
        data.solo = solo;
      } else if (solo && data.gainNode) {
        data.gainNode.gain.value = 0;
      }
    }
  }

  /** Sets panning for a stem (-1 to 1). */
  setPan(stem: StemName, pan: number): void {
    const stemData = this.stems.get(stem);
    if (!stemData || !stemData.panNode) return;
    stemData.panNode.pan.value = Math.max(-1, Math.min(1, pan));
  }

  /** Starts playback from current position (or beginning). */
  play(): void {
    if (!this.audioContext || this.isPlaying) return;
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }

    const now = this.audioContext.currentTime;
    const offset = this.pauseTime > 0 ? this.pauseTime : 0;

    for (const [, data] of this.stems) {
      if (!data.buffer) continue;

      const source = this.audioContext.createBufferSource();
      source.buffer = data.buffer;
      source.connect(data.gainNode!);
      data.panNode?.connect(this.masterGain!);

      source.start(now, offset);
      data.source = source;
      data.isPlaying = true;
      data.startOffset = offset;
    }

    this.isPlaying = true;
    this.startTime = now - offset;
    this.pauseTime = 0;
    this.startTimeUpdateLoop();
    this.emit({ type: "play" });
  }

  /** Pauses playback at current position. */
  pause(): void {
    if (!this.isPlaying) return;

    for (const [, data] of this.stems) {
      if (data.source) {
        data.source.stop();
        data.source.disconnect();
        data.source = null;
      }
      data.isPlaying = false;
    }

    this.pauseTime = this.audioContext!.currentTime - this.startTime;
    this.isPlaying = false;
    this.stopTimeUpdateLoop();
    this.emit({ type: "pause" });
  }

  /** Stops playback and resets to beginning. */
  stop(): void {
    for (const [, data] of this.stems) {
      if (data.source) {
        data.source.stop();
        data.source.disconnect();
        data.source = null;
      }
      data.isPlaying = false;
      data.startOffset = 0;
    }

    this.isPlaying = false;
    this.pauseTime = 0;
    this.startTime = 0;
    this.stopTimeUpdateLoop();
    this.emit({ type: "stop" });
  }

  /** Seeks to a specific time (in seconds). */
  seek(time: number): void {
    const wasPlaying = this.isPlaying;
    if (wasPlaying) this.pause();

    this.pauseTime = time;
    if (wasPlaying) this.play();
  }

  /** Gets current playback time in seconds. */
  getCurrentTime(): number {
    if (!this.audioContext) return 0;
    if (this.isPlaying) {
      return this.audioContext.currentTime - this.startTime;
    }
    return this.pauseTime;
  }

  /** Gets duration of the longest stem. */
  getDuration(): number {
    let max = 0;
    for (const [, data] of this.stems) {
      if (data.buffer && data.buffer.duration > max) {
        max = data.buffer.duration;
      }
    }
    return max;
  }

  /** Checks if currently playing. */
  isPlayingNow(): boolean {
    return this.isPlaying;
  }

  /** Subscribes to engine events. */
  on(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Emits an event to all listeners. */
  private emit(event: AudioEngineEvent): void {
    this.listeners.forEach((l) => l(event));
  }

  /** Starts the requestAnimationFrame loop for time updates. */
  private startTimeUpdateLoop(): void {
    const tick = () => {
      if (!this.isPlaying) return;
      const duration = this.getDuration();
      const currentTime = this.getCurrentTime();

      this.emit({ type: "timeupdate", currentTime, duration });

      if (currentTime >= duration - 0.1) {
        this.stop();
        this.emit({ type: "ended" });
        return;
      }

      this.animationFrameId = requestAnimationFrame(tick);
    };
    tick();
  }

  /** Stops the time update loop. */
  private stopTimeUpdateLoop(): void {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
  }

  /** Disposes all resources. */
  dispose(): void {
    this.stop();
    for (const [, data] of this.stems) {
      data.gainNode?.disconnect();
      data.panNode?.disconnect();
      data.source?.disconnect();
      data.buffer = null;
    }
    this.masterGain?.disconnect();
    this.masterLimiter?.disconnect();
    this.masterGain = null;
    this.masterLimiter = null;
    this.audioContext = null;
    this.listeners.clear();
  }
}

/** Singleton instance for app-wide use. */
export const audioEngine = new AudioEngine();

/** React hook for using the AudioEngine. */
export function useAudioEngine() {
  return audioEngine;
}