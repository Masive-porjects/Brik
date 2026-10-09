import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the shared audio engine before importing AudioEngine
const { mockEnsureStarted, mockGetTransport } = vi.hoisted(() => ({
  mockEnsureStarted: vi.fn().mockResolvedValue(undefined),
  mockGetTransport: vi.fn(() => ({ stop: vi.fn() })),
}));

vi.mock("@/adapters/audio/engine", () => ({
  audioEngine: {
    ensureStarted: mockEnsureStarted,
    getTransport: mockGetTransport,
  },
}));

// Mock Tone.js
const { ToneMock } = vi.hoisted(() => {
  const mock = {
    default: {
      getContext: vi.fn(() => ({ rawContext: {} })),
      start: vi.fn().mockResolvedValue(undefined),
      getTransport: () => ({ stop: vi.fn() }),
    },
  };
  return { ToneMock: mock };
});

vi.mock("tone", () => ToneMock);

import { AudioEngine } from "@/features/projects/audioEngine";

/** Minimal mock shapes for the Web Audio nodes used by AudioEngine. */
type FnMock = ReturnType<typeof vi.fn>;

interface AudioParamMock {
  value: number;
}

interface AudioNodeMock {
  connect: FnMock;
  disconnect: FnMock;
}

interface AudioContextMock {
  state: string;
  currentTime: number;
  createGain: FnMock;
  createDynamicsCompressor: FnMock;
  createStereoPanner: FnMock;
  createBufferSource: FnMock;
  decodeAudioData: FnMock;
  resume: FnMock;
  destination: Record<string, never>;
}

describe("AudioEngine", () => {
  let audioContextMock: AudioContextMock;
  let gainNodeMock: AudioNodeMock & { gain: AudioParamMock };
  let bufferSourceMock: AudioNodeMock & {
    buffer: AudioBuffer | null;
    start: FnMock;
    stop: FnMock;
    onended: (() => void) | null;
  };
  let dynamicsCompressorMock: AudioNodeMock & {
    threshold: AudioParamMock;
    knee: AudioParamMock;
    ratio: AudioParamMock;
    attack: AudioParamMock;
    release: AudioParamMock;
  };
  let stereoPannerMock: AudioNodeMock & { pan: AudioParamMock };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockEnsureStarted.mockResolvedValue(undefined);

    // Mock AudioContext and related nodes
    gainNodeMock = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      gain: { value: 1 },
    };

    dynamicsCompressorMock = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      threshold: { value: 0 },
      knee: { value: 0 },
      ratio: { value: 1 },
      attack: { value: 0 },
      release: { value: 0 },
    };

    stereoPannerMock = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      pan: { value: 0 },
    };

    bufferSourceMock = {
      buffer: null,
      connect: vi.fn(),
      disconnect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
      onended: null,
    };

    audioContextMock = {
      state: "running",
      currentTime: 0,
      createGain: vi.fn(() => gainNodeMock),
      createDynamicsCompressor: vi.fn(() => dynamicsCompressorMock),
      createStereoPanner: vi.fn(() => stereoPannerMock),
      createBufferSource: vi.fn(() => bufferSourceMock),
      decodeAudioData: vi.fn().mockResolvedValue({
        duration: 120,
        length: 44100 * 120,
        sampleRate: 44100,
        numberOfChannels: 2,
      }),
      resume: vi.fn().mockResolvedValue(undefined),
      destination: {},
    };

    // Configure Tone.js mock to return our audioContextMock
    ToneMock.default.getContext.mockReturnValue({ rawContext: audioContextMock });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("initializes AudioContext and master bus", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    expect(audioContextMock.createGain).toHaveBeenCalled();
    expect(audioContextMock.createDynamicsCompressor).toHaveBeenCalled();
    expect(gainNodeMock.connect).toHaveBeenCalledWith(dynamicsCompressorMock);
    expect(dynamicsCompressorMock.connect).toHaveBeenCalledWith(audioContextMock.destination);
  });

  it("loads a stem from URL and creates gain/pan nodes", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    // Mock fetch for stem loading
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await engine.loadStem("drums", "https://example.com/drums.wav");

    expect(result.stem).toBe("drums");
    expect(result.duration).toBe(120);
    expect(audioContextMock.createGain).toHaveBeenCalledTimes(2); // master + stem
    expect(audioContextMock.createStereoPanner).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("https://example.com/drums.wav");
  });

  it("loads all 4 stems in parallel", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    const urls = {
      drums: "https://example.com/drums.wav",
      bass: "https://example.com/bass.wav",
      other: "https://example.com/other.wav",
      vocals: "https://example.com/vocals.wav",
    };

    const results = await engine.loadAllStems(urls);

    expect(Object.keys(results)).toEqual(["drums", "bass", "other", "vocals"]);
    expect(results.drums.stem).toBe("drums");
    expect(results.bass.stem).toBe("bass");
    expect(results.other.stem).toBe("other");
    expect(results.vocals.stem).toBe("vocals");
  });

  it("sets fader level and clamps to [-60, 12] dB", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    engine.setFader("drums", -3);
    expect(gainNodeMock.gain.value).toBeCloseTo(Math.pow(10, -3 / 20), 5);

    engine.setFader("drums", 15); // above max
    expect(gainNodeMock.gain.value).toBeCloseTo(Math.pow(10, 12 / 20), 5);

    engine.setFader("drums", -70); // below min
    expect(gainNodeMock.gain.value).toBeCloseTo(Math.pow(10, -60 / 20), 5);
  });

  it("sets mute state", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    engine.setMute("drums", true);
    expect(gainNodeMock.gain.value).toBe(0);
  });

  it("sets pan position", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    engine.setPan("drums", 0.5);
    expect(stereoPannerMock.pan.value).toBe(0.5);

    engine.setPan("drums", -1);
    expect(stereoPannerMock.pan.value).toBe(-1);
  });

  it("plays, pauses, and stops", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    engine.play();
    expect(bufferSourceMock.start).toHaveBeenCalled();
    expect(engine.isPlayingNow()).toBe(true);

    engine.pause();
    expect(bufferSourceMock.stop).toHaveBeenCalled();
    expect(engine.isPlayingNow()).toBe(false);

    engine.play();
    engine.stop();
    expect(bufferSourceMock.stop).toHaveBeenCalledTimes(2);
    expect(engine.isPlayingNow()).toBe(false);
  });

  it("seeks to specific time", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    engine.play();
    engine.seek(30);
    expect(engine.getCurrentTime()).toBeCloseTo(30, 1);
  });

  it("emits events on play/pause/stop", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    const listener = vi.fn();
    const unsubscribe = engine.on(listener);

    engine.play();
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ type: "play" }));

    engine.pause();
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ type: "pause" }));

    engine.play();
    engine.stop();
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ type: "stop" }));

    // Should have 6 calls (play, pause, play, stop + timeupdate events)
    expect(listener).toHaveBeenCalledTimes(6);

    unsubscribe();
    engine.play();
    // Listener should not be called after unsubscribe
    expect(listener).toHaveBeenCalledTimes(6);
  });
it("gets current time and duration", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");

    expect(engine.getDuration()).toBe(120);
    expect(engine.getCurrentTime()).toBe(0);

    engine.play();
    // Note: getCurrentTime() uses audioContext.currentTime which doesn't advance with fake timers
    // In real usage, time advances with actual audio playback
    expect(engine.getCurrentTime()).toBeGreaterThanOrEqual(0);
  });

  it("disposes all resources", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(100),
    });
    vi.stubGlobal("fetch", fetchMock);

    await engine.loadStem("drums", "https://example.com/drums.wav");
    engine.play();

    engine.dispose();

    expect(gainNodeMock.disconnect).toHaveBeenCalled();
    expect(dynamicsCompressorMock.disconnect).toHaveBeenCalled();
    expect(bufferSourceMock.stop).toHaveBeenCalled();
  });

  it("handles load error gracefully", async () => {
    const engine = new AudioEngine();
    await engine.initialize();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(engine.loadStem("drums", "https://example.com/missing.wav")).rejects.toThrow(
      "Failed to load drums: 404"
    );
  });
});