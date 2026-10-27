import { DSPContainer } from "./container";

export interface Env {
  DSP: DurableObjectNamespace;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Orchestrator liveness; never reaches the container.
    if (url.pathname === "/__diag") {
      return json({ ok: true, service: "waveai-orchestrator", phase: 1 });
    }

    if (url.pathname === "/") {
      return json({
        service: "waveai-orchestrator",
        phase: 1,
        hint: "/__diag orchestrator healthcare; everything else proxies the DSP container",
      });
    }

    // Phase 1 smoke: proxy everything to the single "dsp-smoke" instance.
    // Phase 3 keys instances per job id once Queues land.
    const id = env.DSP.idFromName("dsp-smoke");
    const stub = env.DSP.get(id);
    return stub.fetch(
      new Request(new URL(url.pathname + url.search, "https://dsp.internal"), request),
    );
  },
} satisfies ExportedHandler<Env>;

export { DSPContainer };
