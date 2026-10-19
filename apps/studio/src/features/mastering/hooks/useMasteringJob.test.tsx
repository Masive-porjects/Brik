/**
 * useMasteringJob — el polling tiene que terminar.
 *
 * Regresión: el hook reprogramaba el tick ante un estado desconocido o ante un
 * error de red no-404, sin tope de intentos. Un backend que responde 500 de
 * forma sostenida (o un 200 con un body que no trae `status`) dejaba la UI en
 * "processing" para siempre: el usuario veía un spinner eterno y la app seguía
 * golpeando el servidor cada 10 s.
 *
 * El contrato que fija este test: tras un número acotado de fallos seguidos el
 * hook tiene que declarar el job fallido y dejar de consultar.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  getMasterJobStatus: vi.fn(),
  submitMasterJob: vi.fn(),
  // Referencia estable: si `t` cambia de identidad en cada render, el efecto
  // que arranca el polling se re-ejecuta sin parar y el timer nunca dispara.
  t: (key: string, fallback?: string) => fallback ?? key,
}));

vi.mock("@/lib/api", () => ({
  getMasterJobStatus: mocks.getMasterJobStatus,
  submitMasterJob: mocks.submitMasterJob,
}));

// El hook sólo necesita `t`; sin i18n real devolvemos el fallback.
vi.mock("@/i18n/useTranslation", () => ({
  useTranslation: () => ({ t: mocks.t }),
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ user: null }),
}));

import { useMasteringJob } from "./useMasteringJob";

const PAYLOAD = {} as never;

describe("useMasteringJob — terminación del polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.getMasterJobStatus.mockReset();
    mocks.submitMasterJob.mockReset();
    mocks.submitMasterJob.mockResolvedValue({ job_id: "job-1" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("declara el job fallido cuando el backend devuelve error de forma sostenida", async () => {
    mocks.getMasterJobStatus.mockRejectedValue(
      new Error("500 Internal Server Error"),
    );

    const { result, unmount } = renderHook(() =>
      useMasteringJob({ payload: PAYLOAD }),
    );

    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });

    expect(result.current.state).toBe("error");
    expect(result.current.isTerminal).toBe(true);
    // Tope de intentos: 6 fallos con backoff consumen ~40 s, no 120 s de ticks.
    expect(mocks.getMasterJobStatus.mock.calls.length).toBeLessThan(12);

    unmount();
  });

  it("declara el job fallido cuando el backend responde un estado desconocido", async () => {
    mocks.getMasterJobStatus.mockResolvedValue({
      job_id: "job-1",
      status: undefined,
      progress: 0,
    });

    const { result, unmount } = renderHook(() =>
      useMasteringJob({ payload: PAYLOAD }),
    );

    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });

    expect(result.current.state).toBe("error");
    expect(result.current.isTerminal).toBe(true);
    expect(mocks.getMasterJobStatus.mock.calls.length).toBeLessThan(12);

    unmount();
  });

  it("sigue consultando mientras el job está en processing (sin regresión)", async () => {
    mocks.getMasterJobStatus.mockResolvedValue({
      job_id: "job-1",
      status: "processing",
      progress: 40,
    });

    const { result, unmount } = renderHook(() =>
      useMasteringJob({ payload: PAYLOAD }),
    );

    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(result.current.state).toBe("processing");
    expect(result.current.progress).toBe(40);
    expect(mocks.getMasterJobStatus.mock.calls.length).toBeGreaterThan(1);

    unmount();
  });
});
