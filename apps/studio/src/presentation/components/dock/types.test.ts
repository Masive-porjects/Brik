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

  it("no expone el módulo Live Engine (eliminado con su UI)", () => {
    // El Live Engine se retiró: el tab solo renderizaba un "próximamente"
    // y su motor no tenía ningún importador. Este guard evita que vuelva
    // un tab apuntando a código inexistente.
    expect(DOCK_MODULES.map((m) => m.key)).not.toContain("live");
  });
});