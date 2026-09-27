import { describe, it, expect } from 'vitest';
import { safeCloseAudioContext } from './audioContextUtils';

/** Mock mínimo: solo `state` y `close` — suficiente para el contrato. */
function fakeCtx(state: string, closeImpl?: () => void) {
  return {
    state,
    close: closeImpl ?? (() => undefined),
  } as unknown as AudioContext;
}

describe('safeCloseAudioContext', () => {
  it('es no-op con null/undefined', async () => {
    await expect(safeCloseAudioContext(null)).resolves.toBeUndefined();
    await expect(safeCloseAudioContext(undefined)).resolves.toBeUndefined();
  });

  it('no llama close si ya está closed', async () => {
    let closed = false;
    await safeCloseAudioContext(fakeCtx('closed', () => { closed = true; }));
    expect(closed).toBe(false);
  });

  it('cierra un context abierto', async () => {
    let closed = false;
    await safeCloseAudioContext(fakeCtx('running', () => { closed = true; }));
    expect(closed).toBe(true);
  });

  it('traga InvalidStateError (doble close en carrera)', async () => {
    const err = new DOMException('Cannot close a closed AudioContext', 'InvalidStateError');
    await expect(
      safeCloseAudioContext(fakeCtx('running', () => { throw err; })),
    ).resolves.toBeUndefined();
  });

  it('re-lanza errores reales (no los oculta)', async () => {
    await expect(
      safeCloseAudioContext(fakeCtx('running', () => { throw new Error('boom'); })),
    ).rejects.toThrow('boom');
  });
});