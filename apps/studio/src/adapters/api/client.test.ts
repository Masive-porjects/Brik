/**
 * client — URL builders de audio/download (demo multi-preset):
 *  - getAudioUrl: mastered + preset => ?preset_id; original nunca lo lleva
 *  - getDownloadUrl: appendea ?preset_id para wav y mp3 cuando hay preset
 *  - processAudio: ?source=original|mix elige qué archivo consume el master
 *    (T2); sin source no manda la query (default smart del backend)
 *  - Sin presetId la URL queda intacta (ruta legacy)
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  getAudioUrl,
  getDownloadUrl,
  getMixAudioUrl,
  mixTracks,
  processAudio,
  DEFAULT_PARAMS,
} from '@/adapters/api/client';

// Mismo fallback que config.ts en tests (sin NEXT_PUBLIC_API_URL).
const API = 'http://localhost:8000/api';
const SID = 'session-123';

describe('getAudioUrl', () => {
  it('mastered con preset appendea ?preset_id', () => {
    expect(getAudioUrl(SID, 'mastered', 'urban')).toBe(
      `${API}/session/${SID}/audio/mastered?preset_id=urban`,
    );
  });

  it('mastered sin preset NO appendea la query', () => {
    expect(getAudioUrl(SID, 'mastered')).toBe(
      `${API}/session/${SID}/audio/mastered`,
    );
  });

  it('original nunca appendea preset_id', () => {
    expect(getAudioUrl(SID, 'original', 'urban')).toBe(
      `${API}/session/${SID}/audio/original`,
    );
  });

  it('codifica el preset_id', () => {
    expect(getAudioUrl(SID, 'mastered', 'rock & roll')).toBe(
      `${API}/session/${SID}/audio/mastered?preset_id=rock%20%26%20roll`,
    );
  });
});

describe('getDownloadUrl', () => {
  it('wav con preset appendea la query', () => {
    expect(getDownloadUrl(SID, 'wav', 'urban')).toBe(
      `${API}/session/${SID}/download/wav?preset_id=urban`,
    );
  });

  it('mp3 con preset appendea la query', () => {
    expect(getDownloadUrl(SID, 'mp3', 'urban')).toBe(
      `${API}/session/${SID}/download/mp3?preset_id=urban`,
    );
  });

  it('sin presetId deja la URL intacta', () => {
    expect(getDownloadUrl(SID, 'wav')).toBe(`${API}/session/${SID}/download/wav`);
    expect(getDownloadUrl(SID, 'mp3')).toBe(`${API}/session/${SID}/download/mp3`);
  });
});

describe('getMixAudioUrl', () => {
  it('apunta al WAV mezclado persistido de la sesión', () => {
    expect(getMixAudioUrl(SID)).toBe(`${API}/session/${SID}/audio/mix`);
  });
});

describe('processAudio — ?source (T2)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function okFetch() {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: SID, mix_status: 'completed' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('envía source=mix cuando el master parte de la mezcla entregada', async () => {
    const fetchMock = okFetch();

    await processAudio(SID, DEFAULT_PARAMS, undefined, undefined, 'mix');

    expect(fetchMock.mock.calls[0][0].toString()).toBe(
      `${API}/session/${SID}/process?source=mix`,
    );
  });

  it('envía source=original cuando no hay mezcla entregada', async () => {
    const fetchMock = okFetch();

    await processAudio(SID, DEFAULT_PARAMS, undefined, undefined, 'original');

    expect(fetchMock.mock.calls[0][0].toString()).toBe(
      `${API}/session/${SID}/process?source=original`,
    );
  });

  it('omite la query cuando no se pasa source (default smart del backend)', async () => {
    const fetchMock = okFetch();

    await processAudio(SID, DEFAULT_PARAMS);

    expect(fetchMock.mock.calls[0][0].toString()).toBe(
      `${API}/session/${SID}/process`,
    );
  });

  it('combina source con preset_id', async () => {
    const fetchMock = okFetch();

    await processAudio(SID, DEFAULT_PARAMS, undefined, 'urbano', 'mix');

    const url = new URL(fetchMock.mock.calls[0][0].toString());
    expect(url.searchParams.get('source')).toBe('mix');
    expect(url.searchParams.get('preset_id')).toBe('urbano');
  });
});

describe('mixTracks', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  /** Stub de jsdom: URL.createObjectURL no está implementado. */
  function stubObjectUrl() {
    URL.createObjectURL = vi.fn(() => 'blob:mock-mix') as unknown as typeof URL.createObjectURL;
  }

  it('POSTea /mix y parsea el header X-Mix-Result', async () => {
    const payload = {
      tempo_bpm: 128,
      genre: 'urban',
      genre_confidence: 0.87,
      sample_rate: 48000,
      duration_seconds: 96.5,
      stem_presence: { drums: true, bass: true, other: false, vocals: true },
      qc_report: { summary: { all_ok: true, flagged: [] } },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['RIFF...'], { type: 'audio/wav' }),
      headers: { get: (name: string) => (name === 'X-Mix-Result' ? JSON.stringify(payload) : null) },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    const { audioUrl, result } = await mixTracks(SID);

    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/session/${SID}/mix`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ dimension_enabled: true }),
      }),
    );
    expect(audioUrl).toBe('blob:mock-mix');
    expect(result?.tempo_bpm).toBe(128);
    expect(result?.genre).toBe('urban');
    expect(result?.stem_presence).toEqual({
      drums: true,
      bass: true,
      other: false,
      vocals: true,
    });
    expect(result?.qc_report).toEqual(payload.qc_report);
  });

  it('devuelve result null cuando el header no parsea como JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x']),
      headers: { get: () => 'not-json{' },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    const { result } = await mixTracks(SID);
    expect(result).toBeNull();
  });

  it('lanza error con el detail del backend cuando !res.ok', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: 'Mix failed: boom' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(mixTracks(SID)).rejects.toThrow('Mix failed: boom');
  });

  it('propaga un AbortSignal opcional al fetch de /mix', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    const { audioUrl } = await mixTracks(SID, { signal: controller.signal });

    expect(audioUrl).toBe('blob:mock-mix');
    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/session/${SID}/mix`,
      expect.objectContaining({
        method: 'POST',
        signal: controller.signal,
      }),
    );
  });

  it('envía dimension_enabled: false cuando dimensionEnabled es false', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    await mixTracks(SID, { dimensionEnabled: false });

    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/session/${SID}/mix`,
      expect.objectContaining({
        body: JSON.stringify({ dimension_enabled: false }),
      }),
    );
  });

  it('envía auto_balance: true solo cuando autoBalance es true', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    await mixTracks(SID, { autoBalance: true });

    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/session/${SID}/mix`,
      expect.objectContaining({
        body: JSON.stringify({ dimension_enabled: true, auto_balance: true }),
      }),
    );
  });

  it('envía stem_trims con los faders ≠ 0 y omite los ceros', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    await mixTracks(SID, { stemTrims: { drums_db: 2, bass_db: 0, vocals_db: 0 } });

    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/session/${SID}/mix`,
      expect.objectContaining({
        body: JSON.stringify({ dimension_enabled: true, stem_trims: { drums_db: 2 } }),
      }),
    );
  });

  it('omite stem_trims cuando todos valen 0 (body previo exacto)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['x']),
      headers: { get: () => null },
    });
    vi.stubGlobal('fetch', fetchMock);
    stubObjectUrl();

    await mixTracks(SID, { stemTrims: { drums_db: 0, bass_db: 0 } });

    expect(fetchMock).toHaveBeenCalledWith(
      `${API}/session/${SID}/mix`,
      expect.objectContaining({
        body: JSON.stringify({ dimension_enabled: true }),
      }),
    );
  });
});
