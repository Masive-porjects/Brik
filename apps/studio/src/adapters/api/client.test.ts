/**
 * client — URL builders de audio/download (demo multi-preset):
 *  - getAudioUrl: mastered + preset => ?preset_id; original nunca lo lleva
 *  - getDownloadUrl: appendea ?preset_id para wav y mp3 cuando hay preset
 *  - processAudio: ?source=original|mix elige qué archivo consume el master
 *    (T2); sin source no manda la query (default smart del backend)
 *  - Sin presetId la URL queda intacta (ruta legacy)
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import {
  getAudioUrl,
  getDownloadUrl,
  getMixAudioUrl,
  mixTracks,
  processAudio,
  submitMixJob,
  getMixJobState,
  submitAgentJob,
  getAgentJobStatus,
  getProjectDocument,
  putProjectDocument,
  getProjectMixState,
  submitProjectMixJob,
  createProject,
  listProjects,
  presignAsset,
  completeAsset,
  listAssets,
  getAssetDownloadUrl,
  DEFAULT_PARAMS,
  type ProjectDocumentV1,
} from '@/adapters/api/client';

// Supabase browser singleton stub: `authHeaders()` reads the session from it.
// `vi.hoisted` lets the module factory below close over the mock.
const { mockGetSession } = vi.hoisted(() => ({ mockGetSession: vi.fn() }));
vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({ auth: { getSession: mockGetSession } }),
}));

// Mismo fallback que config.ts en tests (sin NEXT_PUBLIC_API_URL).
const API = 'http://localhost:8000/api';
const SID = 'session-123';

/** A structurally valid V1 document (mirrors backend ProjectDocument). */
function validDocument(): ProjectDocumentV1 {
  return {
    schema_version: 1,
    structure: {
      stems: {
        drums: { display_name: 'Drums', order: 0, group_id: null, color_token: null, hidden: false },
        bass: { display_name: 'Bass', order: 1, group_id: null, color_token: null, hidden: false },
        other: { display_name: 'Other', order: 2, group_id: null, color_token: null, hidden: false },
        vocals: { display_name: 'Vocals', order: 3, group_id: null, color_token: null, hidden: false },
      },
      groups: [],
    },
    mix_intent: { genre: null, character: null, proposals: [] },
    master_intent: {
      preset_id: null,
      platform_target: null,
      format: 'wav',
      output_bit_depth: 24,
      master_name: null,
      parameters: null,
    },
    updated_by: 'user',
    updated_at: null,
  };
}

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

describe('submitMixJob', () => {
  function okFetch() {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'mix_abc123',
        session_id: SID,
        status: 'processing',
        poll_url: `/api/jobs/mix/mix_abc123`,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('devuelve el job_id sin esperar al DSP', async () => {
    okFetch();
    const accepted = await submitMixJob(SID);
    expect(accepted.job_id).toBe('mix_abc123');
    expect(accepted.status).toBe('processing');
  });

  it('pega al endpoint async, no al blocking /session/{id}/mix', async () => {
    const fetchMock = okFetch();
    await submitMixJob(SID);
    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/jobs/mix/${SID}`);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
  });

  it('manda dimension_enabled y filtra los trims neutros', async () => {
    const fetchMock = okFetch();
    await submitMixJob(SID, {
      dimensionEnabled: false,
      autoBalance: true,
      stemTrims: { drums_db: 0, bass_db: -1.5, vocal_db: 0 },
    });
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      dimension_enabled: false,
      auto_balance: true,
      stem_trims: { bass_db: -1.5 },
    });
  });

  it('omite auto_balance y stem_trims cuando no aplican', async () => {
    const fetchMock = okFetch();
    await submitMixJob(SID);
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      dimension_enabled: true,
    });
  });

  it('propaga el error del backend con su status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'session not found' }),
    }));
    await expect(submitMixJob('nope')).rejects.toThrow('session not found');
  });

  it('rechaza una sesión sin audio en vez de encolar un job muerto', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'La sesión no tiene audio cargado' }),
    }));
    await expect(submitMixJob(SID)).rejects.toThrow(
      'La sesión no tiene audio cargado',
    );
  });
});

describe('getMixJobState', () => {
  it('lee el estado real del job', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'mix_abc123',
        kind: 'mix',
        status: 'processing',
        progress: 0,
        stage: null,
        session_id: SID,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const state = await getMixJobState('mix_abc123');
    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/jobs/mix/mix_abc123`);
    expect(state.status).toBe('processing');
    expect(state.progress).toBe(0);
  });

  it('expone la URL de R2 al completar', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'mix_abc123',
        kind: 'mix',
        status: 'completed',
        progress: 100,
        stage: null,
        session_id: SID,
        result: {
          r2_key: `mixes/${SID}/final.wav`,
          download_url: 'https://r2.example/final.wav?sig=1',
          content_type: 'audio/wav',
        },
      }),
    }));

    const state = await getMixJobState('mix_abc123');
    expect(state.status).toBe('completed');
    expect(state.result?.download_url).toBe('https://r2.example/final.wav?sig=1');
    expect(state.result?.r2_key).toBe(`mixes/${SID}/final.wav`);
  });

  it('codifica el job_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'x', status: 'processing', progress: 0 }),
    });
    vi.stubGlobal('fetch', fetchMock);
    await getMixJobState('mix_weird/id');
    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/jobs/mix/mix_weird%2Fid`);
  });

  it('propaga el error de un job caódo', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Job no encontrado' }),
    }));
    await expect(getMixJobState('mix_abc123')).rejects.toThrow('Job no encontrado');
  });

  it('propaga el AbortError cuando el usuario cancela', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(
      new DOMException('Aborted', 'AbortError'),
    ));
    const controller = new AbortController();
    controller.abort();
    await expect(
      getMixJobState('mix_abc123', controller.signal),
    ).rejects.toThrow(/abort/i);
  });
});

describe('project endpoints — auth header (B1)', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockGetSession.mockResolvedValue({ data: { session: null } });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function okDocumentFetch() {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'p1',
        version: 0,
        document: validDocument(),
        updated_at: null,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('envía Authorization: Bearer cuando hay sesión de Supabase', async () => {
    mockGetSession.mockResolvedValueOnce({
      data: { session: { access_token: 'tok-123' } },
    });
    const fetchMock = okDocumentFetch();

    await getProjectDocument('p1');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe(
      'Bearer tok-123',
    );
  });

  it('omite Authorization cuando no hay sesión (no rompe el modo dev)', async () => {
    mockGetSession.mockResolvedValueOnce({ data: { session: null } });
    const fetchMock = okDocumentFetch();

    await getProjectDocument('p1');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('no rompe la llamada si getSession falla (Supabase sin configurar)', async () => {
    mockGetSession.mockRejectedValueOnce(new Error('no supabase env'));
    const fetchMock = okDocumentFetch();

    await getProjectDocument('p1');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('project endpoints — DTO normalization (B2)', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockGetSession.mockResolvedValue({ data: { session: null } });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('getProjectDocument normaliza project_id/updated_at a camelCase', async () => {
    const doc = validDocument();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'p1',
        version: 7,
        document: doc,
        updated_at: '2026-10-09T00:00:00Z',
      }),
    }));

    const res = await getProjectDocument('p1');

    expect(res.projectId).toBe('p1');
    expect(res.version).toBe(7);
    expect(res.updatedAt).toBe('2026-10-09T00:00:00Z');
    expect(res.document).toEqual(doc);
    expect((res as unknown as { project_id?: unknown }).project_id).toBeUndefined();
  });

  it('putProjectDocument normaliza la respuesta', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'p1',
        version: 1,
        document: validDocument(),
        updated_at: '2026-10-09T00:00:01Z',
      }),
    }));

    const res = await putProjectDocument('p1', {
      document: validDocument(),
      expected_version: 0,
    });

    expect(res.projectId).toBe('p1');
    expect(res.updatedAt).toBe('2026-10-09T00:00:01Z');
  });

  it('getProjectMixState renombra undo_stack → undoStack', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'p1',
        state: { faders: { drums_db: -3 }, toggles: {} },
        undo_stack: [{ faders: {}, toggles: {}, timestamp: 1 }],
        updated_at: '2026-10-09T00:00:00Z',
      }),
    }));

    const res = await getProjectMixState('p1');

    expect(res.projectId).toBe('p1');
    expect(res.undoStack).toHaveLength(1);
    expect(res.updatedAt).toBe('2026-10-09T00:00:00Z');
    expect(
      (res as unknown as { undo_stack?: unknown }).undo_stack,
    ).toBeUndefined();
  });

  it('submitProjectMixJob normaliza job_id/poll_url', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'j1',
        project_id: 'p1',
        asset_id: 'a1',
        status: 'processing',
        poll_url: '/api/jobs/mix/j1',
      }),
    }));

    const res = await submitProjectMixJob('p1');

    expect(res.jobId).toBe('j1');
    expect(res.pollUrl).toBe('/api/jobs/mix/j1');
  });
});

describe('project endpoints — PUT body (B3)', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockGetSession.mockResolvedValue({ data: { session: null } });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('envía expected_version (snake_case) y no expectedVersion', async () => {
    const doc = validDocument();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'p1',
        version: 1,
        document: doc,
        updated_at: null,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await putProjectDocument('p1', { document: doc, expected_version: 3 });

    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.expected_version).toBe(3);
    expect(body.expectedVersion).toBeUndefined();
    expect(body.document).toEqual(doc);
  });
});

describe('project assets — subida directa a R2', () => {
  beforeEach(() => {
    mockGetSession.mockReset();
    mockGetSession.mockResolvedValue({ data: { session: null } });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const p1 = 'p1';
  const a1 = 'a1';

  function stub(payload: unknown, ok = true, status = 200) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok,
      status,
      json: async () => payload,
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('createProject hace POST a /projects y normaliza user_id → userId', async () => {
    const fetchMock = stub({
      id: 'p1',
      user_id: 'u1',
      name: 'Tema',
      bpm: null,
      musical_key: null,
      created_at: null,
      updated_at: null,
    });

    const res = await createProject('Tema');

    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/projects`);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(
      JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string),
    ).toEqual({ name: 'Tema' });
    expect(res.userId).toBe('u1');
    expect(res.musicalKey).toBeNull();
    expect((res as unknown as { user_id?: unknown }).user_id).toBeUndefined();
  });

  it('createProject manda musical_key (snake_case) cuando se pasa', async () => {
    const fetchMock = stub({
      id: 'p1',
      user_id: 'u1',
      name: 'Tema',
      bpm: 120,
      musical_key: 'Am',
      created_at: null,
      updated_at: null,
    });

    await createProject('Tema', { bpm: 120, musicalKey: 'Am' });

    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.musical_key).toBe('Am');
    expect(body.musicalKey).toBeUndefined();
  });

  it('listProjects normaliza cada fila', async () => {
    stub([
      {
        id: 'p1',
        user_id: 'u1',
        name: 'A',
        bpm: null,
        musical_key: null,
        created_at: null,
        updated_at: null,
      },
    ]);

    const res = await listProjects();

    expect(res).toHaveLength(1);
    expect(res[0].userId).toBe('u1');
  });

  it('presignAsset manda kind/original_filename/content_type y normaliza put_url', async () => {
    const fetchMock = stub({
      asset_id: a1,
      project_id: p1,
      r2_key: `projects/${p1}/original/${a1}.wav`,
      put_url: 'https://r2.example/put',
      content_type: 'audio/wav',
      expires_in: 900,
    });

    const res = await presignAsset(p1, {
      kind: 'original',
      originalFilename: 'Toma con espacios & signos.wav',
      contentType: 'audio/wav',
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${API}/projects/${p1}/assets/presign`,
    );
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    // El nombre original viaja tal cual, sin limpiar (S3).
    expect(body.kind).toBe('original');
    expect(body.original_filename).toBe('Toma con espacios & signos.wav');
    expect(body.content_type).toBe('audio/wav');
    expect(body.originalFilename).toBeUndefined();
    expect(res.putUrl).toBe('https://r2.example/put');
    expect(res.r2Key).toBe(`projects/${p1}/original/${a1}.wav`);
  });

  it('presignAsset omite original_filename/content_type cuando no se pasan', async () => {
    const fetchMock = stub({
      asset_id: a1,
      project_id: p1,
      r2_key: 'k',
      put_url: 'u',
      content_type: 'audio/wav',
      expires_in: 900,
    });

    await presignAsset(p1, { kind: 'stem', stemName: 'vocals' });

    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body).toEqual({ kind: 'stem', stem_name: 'vocals' });
  });

  it('completeAsset hace PATCH en snake_case y normaliza la respuesta', async () => {
    const fetchMock = stub({
      id: a1,
      project_id: p1,
      user_id: 'u1',
      kind: 'original',
      stem_name: null,
      r2_key: 'k',
      media_hash: 'h',
      original_filename: 'x.wav',
      duration_seconds: 3,
      sample_rate: 44100,
      channels: 2,
      format: 'wav',
      size_bytes: 10,
      created_at: null,
    });

    const res = await completeAsset(p1, a1, {
      durationSeconds: 3,
      sampleRate: 44100,
      channels: 2,
      format: 'wav',
      sizeBytes: 10,
      mediaHash: 'h',
    });

    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/projects/${p1}/assets/${a1}`);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('PATCH');
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body.duration_seconds).toBe(3);
    expect(body.media_hash).toBe('h');
    expect(body.durationSeconds).toBeUndefined();
    expect(res.originalFilename).toBe('x.wav');
    expect(res.sizeBytes).toBe(10);
  });

  it('listAssets normaliza el array', async () => {
    stub([
      {
        id: a1,
        project_id: p1,
        user_id: 'u1',
        kind: 'original',
        stem_name: null,
        r2_key: 'k',
        media_hash: null,
        original_filename: 'n.wav',
        duration_seconds: null,
        sample_rate: null,
        channels: null,
        format: null,
        size_bytes: null,
        created_at: null,
      },
    ]);

    const res = await listAssets(p1);

    expect(res[0].r2Key).toBe('k');
    expect(res[0].originalFilename).toBe('n.wav');
  });

  it('getAssetDownloadUrl devuelve la URL firmada y el nombre original', async () => {
    const fetchMock = stub({
      project_id: p1,
      asset_id: a1,
      r2_key: 'k',
      original_filename: 'Toma (demo).wav',
      download_url: 'https://r2.example/get',
      expires_in: 3600,
    });

    const res = await getAssetDownloadUrl(p1, a1);

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${API}/projects/${p1}/assets/${a1}/download`,
    );
    expect(res.downloadUrl).toBe('https://r2.example/get');
    expect(res.originalFilename).toBe('Toma (demo).wav');
    expect(res.expiresIn).toBe(3600);
  });

  it('presignAsset rechaza cuando el backend falla', async () => {
    stub({ detail: 'Proyecto no encontrado.' }, false, 404);

    await expect(presignAsset(p1, { kind: 'original' })).rejects.toThrow();
  });
});

describe('submitAgentJob', () => {
  function okFetch() {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'agent_abc123',
        session_id: SID,
        status: 'processing',
        poll_url: '/api/jobs/agent/agent_abc123',
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('devuelve el job_id sin esperar al bucle agéntico', async () => {
    okFetch();
    const accepted = await submitAgentJob(SID);
    expect(accepted.job_id).toBe('agent_abc123');
    expect(accepted.status).toBe('processing');
  });

  it('pega al endpoint async con el session_id en la ruta', async () => {
    const fetchMock = okFetch();
    await submitAgentJob(SID);
    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/jobs/agent/${SID}`);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
  });

  it('manda el prompt del usuario, sin espacios sobrantes', async () => {
    const fetchMock = okFetch();
    await submitAgentJob(SID, '  quiero la voz al frente  ');
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      prompt: 'quiero la voz al frente',
    });
  });

  it('omite prompt cuando viene vacío: el loop usa su directiva por defecto', async () => {
    const fetchMock = okFetch();
    await submitAgentJob(SID, '   ');
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({});
  });

  it('propaga el 503 sin credencial de LLM con el detalle del backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'No hay transporte LLM disponible' }),
    }));
    await expect(submitAgentJob(SID)).rejects.toThrow('No hay transporte LLM disponible');
  });
});

describe('getAgentJobStatus', () => {
  it('lee el resultado completo: diagnóstico, herramientas y audio durable', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'agent_abc123',
        kind: 'agent',
        status: 'completed',
        progress: 100,
        stage: null,
        session_id: SID,
        result: {
          session_id: SID,
          diagnosis: 'La mezcla estaba apretada en graves.',
          iterations: 2,
          intent: { warmth: 0.6, punch: 0.5 },
          analysis: null,
          mix_metrics: { iteration: 2, qc_report: {} },
          master_metrics: { integrated_lufs: -9.4, source: 'mix' },
          tools_executed: [
            { tool: 'trigger_stem_separation', ok: true, detail: '4 stems', payload: {}, error: null },
          ],
          audio: {
            mix: null,
            master: {
              r2_key: 'masters/session-123/master.wav',
              url: 'https://r2.example/master.wav',
              local_path: null,
              durable: true,
              note: null,
            },
          },
        },
        error: null,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const state = await getAgentJobStatus('agent_abc123');

    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/jobs/agent/agent_abc123`);
    expect(state.status).toBe('completed');
    expect(state.result?.diagnosis).toBe('La mezcla estaba apretada en graves.');
    expect(state.result?.tools_executed[0].tool).toBe('trigger_stem_separation');
    expect(state.result?.audio.master?.durable).toBe(true);
  });

  it('reporta el job interrumpido como error, no como processing eterno', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'agent_abc123',
        kind: 'agent',
        status: 'error',
        progress: 0,
        stage: null,
        session_id: SID,
        result: {},
        error: 'The job was interrupted (the worker stopped before it finished)',
      }),
    }));

    const state = await getAgentJobStatus('agent_abc123');

    expect(state.status).toBe('error');
    expect(state.error).toContain('interrupted');
  });

  it('escapa el job_id en la URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'a/b', kind: 'agent', status: 'processing' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await getAgentJobStatus('a/b');

    expect(fetchMock.mock.calls[0][0]).toBe(`${API}/jobs/agent/a%2Fb`);
  });
});
