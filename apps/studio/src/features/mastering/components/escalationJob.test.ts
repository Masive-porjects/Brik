import { describe, expect, it } from "vitest";

import { escalationDecision } from "./escalationJob";

/**
 * `escalationDecision` — qué job lanza el chat cuando Brik escala.
 *
 * El bug que este test fija: la escalada `master` llamaba al endpoint
 * stateless `POST /jobs/master` mandando el id de la *sesión de subida* como
 * `track_id`. Ese endpoint resuelve el audio desde `public.tracks.storage_path`,
 * así que no encontraba la fila y respondía 500 en cada escalada. La ruta
 * correcta es el job de sesión, con la decisión `master_only`.
 */
describe("escalationDecision", () => {
  it("manda la escalada master al job de sesión como master_only", () => {
    // El backend manda `{ source: "original" }`: no es un track_id ni una URL.
    expect(escalationDecision("master", { source: "original" })).toBe(
      "master_only",
    );
  });

  it("respeta la decisión que Brik eligió para una escalada agent", () => {
    expect(escalationDecision("agent", { decision: "mix_then_master" })).toBe(
      "mix_then_master",
    );
    expect(escalationDecision("agent", { decision: "master_only" })).toBe(
      "master_only",
    );
  });

  it("cae en auto cuando la escalada agent no trae decisión", () => {
    expect(escalationDecision("agent", {})).toBe("auto");
    expect(escalationDecision("agent", undefined)).toBe("auto");
  });

  it("ignora una decisión desconocida en vez de reenviarla", () => {
    expect(escalationDecision("agent", { decision: "inventada" })).toBe("auto");
  });
});
