/**
 * trackStorageService — guardado del original directo a R2.
 *
 * Dos propiedades importan acá:
 *  1. El flujo es presign → PUT → PATCH, y el PUT manda EXACTAMENTE el mismo
 *     Content-Type con el que se firmó (si difiere, R2 rechaza la firma).
 *  2. La clave de R2 es determinista, así que el nombre original viaja tal cual
 *     en `original_filename` y `tracks.storage_path` guarda `r2:<r2_key>`.
 *
 * Las rutas legacy (sin prefijo `r2:`) siguen resolviéndose por Supabase
 * Storage para no romper la librería ya existente.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mockCreateProject, mockPresignAsset, mockCompleteAsset, mockGetAssetDownloadUrl } =
  vi.hoisted(() => ({
    mockCreateProject: vi.fn(),
    mockPresignAsset: vi.fn(),
    mockCompleteAsset: vi.fn(),
    mockGetAssetDownloadUrl: vi.fn(),
  }));

vi.mock('@/adapters/api/client', () => ({
  createProject: mockCreateProject,
  presignAsset: mockPresignAsset,
  completeAsset: mockCompleteAsset,
  getAssetDownloadUrl: mockGetAssetDownloadUrl,
}));

const { mockCreateSignedUrl } = vi.hoisted(() => ({
  mockCreateSignedUrl: vi.fn(),
}));

vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    storage: { from: () => ({ createSignedUrl: mockCreateSignedUrl }) },
  }),
}));

import {
  uploadOriginalToR2,
  getOriginalSignedUrl,
  parseR2Key,
  toR2StoragePath,
} from '@/features/tracks/services/trackStorageService';

const PROJECT_ID = '11111111-1111-1111-1111-111111111111';
const ASSET_ID = '22222222-2222-2222-2222-222222222222';
const R2_KEY = `projects/${PROJECT_ID}/original/${ASSET_ID}.wav`;
const FILENAME = 'Toma con espacios & signos.wav';

function makeFile(name = FILENAME, type = 'audio/wav'): File {
  const bytes = new Uint8Array([1, 2, 3, 4]);
  const file = new File([bytes], name, { type });
  // jsdom no implementa Blob.arrayBuffer() (los navegadores sí). Se completa
  // solo para el test, sin tocar el código de producción.
  if (typeof file.arrayBuffer !== 'function') {
    Object.defineProperty(file, 'arrayBuffer', {
      value: async () => bytes.buffer.slice(0),
    });
  }
  return file;
}

beforeEach(() => {
  mockCreateProject.mockReset();
  mockPresignAsset.mockReset();
  mockCompleteAsset.mockReset();
  mockGetAssetDownloadUrl.mockReset();
  mockCreateSignedUrl.mockReset();

  mockCreateProject.mockResolvedValue({
    id: PROJECT_ID,
    userId: 'u1',
    name: 'Toma con espacios & signos',
    bpm: null,
    musicalKey: null,
    createdAt: null,
    updatedAt: null,
  });
  mockPresignAsset.mockResolvedValue({
    assetId: ASSET_ID,
    projectId: PROJECT_ID,
    r2Key: R2_KEY,
    putUrl: 'https://r2.example/put',
    contentType: 'audio/wav',
    expiresIn: 900,
  });
  mockCompleteAsset.mockResolvedValue({ id: ASSET_ID });

  // jsdom no expone WebCrypto: se stubea el digest con un valor conocido para
  // que la aserción de `media_hash` sea determinista y no dependa del entorno.
  vi.stubGlobal('crypto', {
    subtle: {
      digest: vi
        .fn()
        .mockResolvedValue(new Uint8Array([0xab, 0xcd, 0x01]).buffer),
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('uploadOriginalToR2', () => {
  it('sube con presign → PUT → PATCH y devuelve el storage_path r2:', async () => {
    const putMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', putMock);

    const res = await uploadOriginalToR2(makeFile(), {
      duration: 12.5,
      sampleRate: 44100,
      channels: 2,
      format: 'wav',
      fileSizeBytes: 4,
    });

    // 1. El proyecto toma el nombre del archivo sin extensión.
    expect(mockCreateProject).toHaveBeenCalledWith('Toma con espacios & signos');

    // 2. El presign manda el nombre ORIGINAL sin limpiar y el content-type.
    expect(mockPresignAsset).toHaveBeenCalledWith(PROJECT_ID, {
      kind: 'original',
      originalFilename: FILENAME,
      contentType: 'audio/wav',
    });

    // 3. PUT directo a R2 con el MISMO content-type que se firmó.
    expect(putMock).toHaveBeenCalledTimes(1);
    const [url, init] = putMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://r2.example/put');
    expect(init.method).toBe('PUT');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe(
      'audio/wav',
    );
    expect(init.body).toBeInstanceOf(File);

    // 4. PATCH con los metadatos y el hash del archivo.
    expect(mockCompleteAsset).toHaveBeenCalledWith(PROJECT_ID, ASSET_ID, {
      durationSeconds: 12.5,
      sampleRate: 44100,
      channels: 2,
      format: 'wav',
      sizeBytes: 4,
      mediaHash: 'abcd01',
    });

    // 5. storage_path listo para `public.tracks`.
    expect(res.storagePath).toBe(`r2:${R2_KEY}`);
    expect(res.projectId).toBe(PROJECT_ID);
    expect(res.assetId).toBe(ASSET_ID);
    expect(res.originalFilename).toBe(FILENAME);
  });

  it('usa audio/wav cuando el File no trae type', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));

    await uploadOriginalToR2(makeFile('sin-tipo', ''));

    expect(mockPresignAsset).toHaveBeenCalledWith(
      PROJECT_ID,
      expect.objectContaining({ contentType: 'audio/wav' }),
    );
  });

  it('si el PUT a R2 falla, no registra metadatos y propaga el error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 403 }),
    );

    await expect(uploadOriginalToR2(makeFile())).rejects.toThrow(/403/);
    expect(mockCompleteAsset).not.toHaveBeenCalled();
  });
});

describe('getOriginalSignedUrl', () => {
  it('resuelve un storage_path r2: por el endpoint de descarga', async () => {
    mockGetAssetDownloadUrl.mockResolvedValue({
      projectId: PROJECT_ID,
      assetId: ASSET_ID,
      r2Key: R2_KEY,
      originalFilename: FILENAME,
      downloadUrl: 'https://r2.example/get',
      expiresIn: 3600,
    });

    const url = await getOriginalSignedUrl(`r2:${R2_KEY}`);

    expect(url).toBe('https://r2.example/get');
    expect(mockGetAssetDownloadUrl).toHaveBeenCalledWith(PROJECT_ID, ASSET_ID);
    expect(mockCreateSignedUrl).not.toHaveBeenCalled();
  });

  it('mantiene Supabase Storage para las rutas legacy', async () => {
    mockCreateSignedUrl.mockResolvedValue({
      data: { signedUrl: 'https://supa.example/s' },
      error: null,
    });

    const url = await getOriginalSignedUrl('u1/track-1.wav');

    expect(url).toBe('https://supa.example/s');
    expect(mockCreateSignedUrl).toHaveBeenCalledWith('u1/track-1.wav', 3600);
    expect(mockGetAssetDownloadUrl).not.toHaveBeenCalled();
  });

  it('falla claro si el storage_path r2: está malformado', async () => {
    await expect(getOriginalSignedUrl('r2:basura')).rejects.toThrow();
    expect(mockGetAssetDownloadUrl).not.toHaveBeenCalled();
  });
});

describe('claves de R2', () => {
  it('toR2StoragePath prefija con r2:', () => {
    expect(toR2StoragePath(R2_KEY)).toBe(`r2:${R2_KEY}`);
  });

  it('parseR2Key extrae proyecto y asset del key determinista', () => {
    expect(parseR2Key(R2_KEY)).toEqual({
      projectId: PROJECT_ID,
      assetId: ASSET_ID,
    });
  });

  it('parseR2Key devuelve null si el key no tiene el formato esperado', () => {
    expect(parseR2Key('basura')).toBeNull();
    expect(parseR2Key('projects/only-two')).toBeNull();
    expect(parseR2Key('mixes/p/original/a.wav')).toBeNull();
  });
});
