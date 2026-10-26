/**
 * useProcessingProgress — cierre del overlay ante fallas del backend.
 *
 * Reglas cubiertas:
 *  S1. `status === "error"` cierra el sondeo y reporta el motivo del motor.
 *  S2. Una falla de red/HTTP que no sea 404 no gira para siempre: tras
 *      MAX_CONSECUTIVE_FAILURES intentos se cierra y se reporta.
 *  S3. Una falla aislada NO aborta: el sondeo se recupera en el siguiente tick.
 *  S4. Un 404 reporta sesión perdida.
 *  S5. Al completar, el sondeo se detiene de verdad (no reprograma ticks).
 */
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number;

    constructor(message: string, status: number) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  return { ApiError, getProcessingProgress: vi.fn() };
});

import { ApiError, getProcessingProgress } from "@/lib/api";

import { useProcessingProgress } from "./useProcessingProgress";

const mockProgress = vi.mocked(getProcessingProgress);

/** Corre los timers falsos dejando que las promesas del tick se resuelvan. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function renderPoller(overrides: Partial<Parameters<typeof useProcessingProgress>[0]> = {}) {
  const onComplete = vi.fn();
  const onError = vi.fn();

  const view = renderHook(() =>
    useProcessingProgress({
      enabled: true,
      sessionId: "session-1",
      onComplete,
      onError,
      ...overrides,
    }),
  );

  return { ...view, onComplete, onError };
}

beforeEach(() => {
  vi.useFakeTimers();
  mockProgress.mockReset();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useProcessingProgress — fallas del backend", () => {
  it("S1: status 'error' cierra el overlay y reporta el motivo del motor", async () => {
    mockProgress.mockResolvedValue({
      progress: 0,
      status: "error",
      error: "Analysis failed: audio too short",
    });

    const { onError } = renderPoller();

    await advance(600);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith({
      kind: "processing_failed",
      message: "Analysis failed: audio too short",
    });
  });

  it("S1: después de un 'error' no sigue sondeando", async () => {
    mockProgress.mockResolvedValue({ progress: 0, status: "error", error: null });

    const { onError } = renderPoller();

    await advance(600);
    const callsAfterFailure = mockProgress.mock.calls.length;

    await advance(30000);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(mockProgress.mock.calls.length).toBe(callsAfterFailure);
  });

  it("S2: tres fallas seguidas de red cierran el overlay en vez de girar para siempre", async () => {
    mockProgress.mockRejectedValue(new ApiError("Bad gateway", 502));

    const { onError } = renderPoller();

    // tick 1 @500ms, tick 2 @+750ms, tick 3 @+1125ms
    await advance(2500);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toMatchObject({ kind: "poll_failed" });
  });

  it("S2: después de agotar los reintentos deja de sondear", async () => {
    mockProgress.mockRejectedValue(new ApiError("Bad gateway", 502));

    const { onError } = renderPoller();

    await advance(2500);
    const callsAfterFailure = mockProgress.mock.calls.length;

    await advance(30000);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(mockProgress.mock.calls.length).toBe(callsAfterFailure);
  });

  it("S3: una falla aislada no aborta el sondeo", async () => {
    mockProgress
      .mockRejectedValueOnce(new ApiError("blip", 502))
      .mockResolvedValue({ progress: 0.5, status: "processing", error: null });

    const { onError, result } = renderPoller();

    await advance(600);
    expect(onError).not.toHaveBeenCalled();

    await advance(1000);
    expect(onError).not.toHaveBeenCalled();
    expect(result.current.progress).toBe(50);
  });

  it("S4: un 404 reporta sesión perdida", async () => {
    mockProgress.mockRejectedValue(new ApiError("Session not found", 404));

    const { onError } = renderPoller();

    await advance(600);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith({ kind: "session_lost", message: null });
  });
});

describe("useProcessingProgress — camino feliz (regresión)", () => {
  it("S5: al completar llama onComplete una vez y no reprograma más ticks", async () => {
    mockProgress.mockResolvedValue({ progress: 1, status: "completed", error: null });

    const { onComplete } = renderPoller();

    await advance(600);
    await advance(1500);

    expect(onComplete).toHaveBeenCalledTimes(1);

    const callsAfterComplete = mockProgress.mock.calls.length;
    await advance(30000);

    expect(mockProgress.mock.calls.length).toBe(callsAfterComplete);
  });

  it("S5: progress 100 sin status 'completed' también completa", async () => {
    mockProgress.mockResolvedValue({ progress: 1, status: "processing", error: null });

    const { onComplete } = renderPoller();

    await advance(600);
    await advance(1500);

    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});
