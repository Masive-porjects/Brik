import { ApiError } from "./client";

/**
 * Transient failures worth retrying for READ requests: gateway errors
 * (502/503/504) and network-level failures. A browser reports a CORS-blocked
 * or unreachable response as a `TypeError` from `fetch`, so that is treated as
 * transient too. Other statuses (400, 401, 404...) are real answers and are
 * never retried.
 *
 * Never use this for POST submissions: a retried POST can create a duplicate job.
 */
export function isTransientGatewayError(err: unknown): boolean {
  if (err instanceof ApiError) {
    return err.status === 502 || err.status === 503 || err.status === 504;
  }
  return err instanceof TypeError;
}

export interface BackoffOptions {
  /** Total attempts, including the first one. */
  attempts?: number;
  /** Delay before the first retry. */
  baseMs?: number;
  /** Upper bound for a single delay. */
  maxMs?: number;
  signal?: AbortSignal;
  /** Called before each wait, so the UI can say it is retrying. */
  onRetry?: (attempt: number, delayMs: number) => void;
}

function abortError(): DOMException {
  return new DOMException("Aborted", "AbortError");
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(abortError());
      },
      { once: true },
    );
  });
}

/**
 * Runs `task` and retries transient failures with exponential backoff
 * (1s, 2s, 4s... capped at `maxMs`) plus jitter. Aborts are never retried.
 */
export async function withBackoff<T>(
  task: () => Promise<T>,
  options: BackoffOptions = {},
): Promise<T> {
  const { attempts = 4, baseMs = 1_000, maxMs = 8_000, signal, onRetry } = options;

  for (let attempt = 1; ; attempt++) {
    try {
      return await task();
    } catch (err) {
      if (signal?.aborted) throw abortError();
      if (
        (err as { name?: string })?.name === "AbortError" ||
        attempt >= attempts ||
        !isTransientGatewayError(err)
      ) {
        throw err;
      }
      const base = Math.min(maxMs, baseMs * 2 ** (attempt - 1));
      const delay = Math.round(base * (0.8 + Math.random() * 0.4));
      onRetry?.(attempt, delay);
      await sleep(delay, signal);
    }
  }
}
