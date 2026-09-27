/**
 * dock/types — orden de los módulos del dock.
 * El dock renderiza slice(0,3) a la izquierda: Mezcla de Audio, Masterizar
 * Audio y Splitter deben ocupar esos slots (antes de la telemetría central).
 */
import { describe, it, expect } from "vitest";
import { DOCK_MODULES } from "./types";

describe("DOCK_MODULES", () => {
  it("empieza con Mezcla de Audio y Masterizar Audio a la izquierda", () => {
    expect(DOCK_MODULES[0].key).toBe("mezcla");
    expect(DOCK_MODULES[0].label).toBe("Mezcla de Audio");
    expect(DOCK_MODULES[1].key).toBe("modules");
    expect(DOCK_MODULES[1].label).toBe("Masterizar Audio");
  });

  it("mantiene Splitter como tercer módulo izquierdo", () => {
    expect(DOCK_MODULES[2].key).toBe("splitter");
  });
});