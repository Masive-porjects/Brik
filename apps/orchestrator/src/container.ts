import { Container } from "@cloudflare/containers";

/**
 * AudioMind DSP container: the existing FastAPI image (apps/audiomind/Dockerfile).
 *
 * One keyed instance per job/session keeps the backend's in-memory DSP state
 * coherent (AUDIOMIND_MAX_CONCURRENT_DSP=1). The spike uses the single key
 * "dsp-smoke"; phase 3 will key instances per job id once Queues arrive.
 */
export class DSPContainer extends Container {
  // Must match the Dockerfile: ENV PORT=8000 and the uvicorn CMD default.
  override defaultPort = 8000;

  // Idle lifetime before stop(): the cost lever for standard-4 activity.
  override sleepAfter = "10m";

  override onStart(): void {
    console.log("dsp container started");
  }

  override onStop(): void {
    console.log("dsp container stopped");
  }

  override onError(error: unknown): void {
    console.error("dsp container error:", error);
  }

  // Spike phase: pass every request straight to the FastAPI app.
  override async fetch(request: Request): Promise<Response> {
    return this.containerFetch(request);
  }
}
