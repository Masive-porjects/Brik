import { describe, expect, it, vi, afterEach } from "vitest";
import { ApiError } from "./client";
import { isTransientGatewayError, withBackoff } from "./retry";

afterEach(() => {
  vi.useRealTimers();
});

describe("isTransientGatewayError", () => {
  it("treats 502/503/504 as transient", () => {
    expect(isTransientGatewayError(new ApiError("bad gateway", 502))).toBe(true);
    expect(isTransientGatewayError(new ApiError("unavailable", 503))).toBe(true);
    expect(isTransientGatewayError(new ApiError("timeout", 504))).toBe(true);
  });

  it("treats network/CORS TypeErrors as transient", () => {
    expect(isTransientGatewayError(new TypeError("Failed to fetch"))).toBe(true);
  });

  it("never retries real client answers", () => {
    expect(isTransientGatewayError(new ApiError("not found", 404))).toBe(false);
    expect(isTransientGatewayError(new ApiError("unauthorized", 401))).toBe(false);
    expect(isTransientGatewayError(new Error("boom"))).toBe(false);
  });
});

describe("withBackoff", () => {
  it("returns the value without retrying when the first call succeeds", async () => {
    const task = vi.fn().mockResolvedValue("ok");
    await expect(withBackoff(task)).resolves.toBe("ok");
    expect(task).toHaveBeenCalledTimes(1);
  });

  it("retries transient failures until the task succeeds", async () => {
    vi.useFakeTimers();
    const task = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new ApiError("bad gateway", 502))
      .mockResolvedValue("recovered");
    const onRetry = vi.fn();

    const pending = withBackoff(task, { baseMs: 100, onRetry });
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toBe("recovered");
    expect(task).toHaveBeenCalledTimes(3);
    expect(onRetry).toHaveBeenCalledTimes(2);
  });

  it("gives up after the configured attempts and rethrows the last error", async () => {
    vi.useFakeTimers();
    const task = vi.fn().mockRejectedValue(new ApiError("bad gateway", 502));

    const pending = withBackoff(task, { attempts: 3, baseMs: 10 });
    const assertion = expect(pending).rejects.toBeInstanceOf(ApiError);
    await vi.runAllTimersAsync();

    await assertion;
    expect(task).toHaveBeenCalledTimes(3);
  });

  it("does not retry non-transient errors", async () => {
    const task = vi.fn().mockRejectedValue(new ApiError("not found", 404));
    await expect(withBackoff(task)).rejects.toBeInstanceOf(ApiError);
    expect(task).toHaveBeenCalledTimes(1);
  });

  it("stops immediately when aborted", async () => {
    const controller = new AbortController();
    const task = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const pending = withBackoff(task, { signal: controller.signal, baseMs: 10_000 });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(task).toHaveBeenCalledTimes(1);
  });
});
