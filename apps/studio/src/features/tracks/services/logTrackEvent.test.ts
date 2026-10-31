/**
 * logTrackEvent — auditoría best-effort del ciclo de vida del track.
 *
 * El punto delicado: supabase-js NO lanza cuando PostgREST rechaza un insert,
 * resuelve con `{ error }`. Si nadie lee ese campo, un 409 (violación de FK o
 * de unique) desaparece sin dejar rastro y la auditoría se pierde en silencio.
 * Estos tests fijan que el error se reporte y que el éxito no haga ruido.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mockInsert } = vi.hoisted(() => ({ mockInsert: vi.fn() }));

vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    from: () => ({ insert: mockInsert }),
  }),
}));

import { logTrackEvent } from '@/features/tracks/services/trackStorageService';

const USER_ID = '3f6f36c8-a6bc-4ef6-8eec-240c267d37a4';
const TRACK_ID = 'cc98f927-1344-4f63-a59e-def5e0d0ab5a';

describe('logTrackEvent', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    mockInsert.mockReset();
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it('reporta el código y el mensaje de PostgREST cuando el insert es rechazado', async () => {
    mockInsert.mockResolvedValue({
      error: {
        code: '23503',
        message: 'insert or update on table "track_events" violates foreign key constraint',
      },
    });

    await logTrackEvent(USER_ID, TRACK_ID, 'analyzed', { detected_genre: 'pop' });

    expect(warnSpy).toHaveBeenCalledTimes(1);
    const report = warnSpy.mock.calls[0].map(String).join(' ');
    expect(report).toContain('23503');
    expect(report).toContain('foreign key constraint');
    expect(report).toContain(TRACK_ID);
  });

  it('no reporta nada cuando el insert se guarda', async () => {
    mockInsert.mockResolvedValue({ error: null });

    await logTrackEvent(USER_ID, TRACK_ID, 'analyzed', {});

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('sigue sin lanzar si el cliente revienta antes de responder', async () => {
    mockInsert.mockRejectedValue(new Error('network down'));

    await expect(logTrackEvent(USER_ID, TRACK_ID, 'analyzed', {})).resolves.toBeUndefined();

    expect(warnSpy).toHaveBeenCalledTimes(1);
    const report = warnSpy.mock.calls[0].map(String).join(' ');
    expect(report).toContain('network down');
  });
});
