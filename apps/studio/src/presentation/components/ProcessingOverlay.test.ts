/**
 * ProcessingOverlay — `getSubtext` (subtexto del overlay de progreso).
 *
 * Regresión (T6): el subtexto decía "Cargado" desde 99% mientras el check
 * del anillo solo aparece en 100%. La UI se contradecía a sí misma: el
 * número decía 99% con el texto de algo ya cargado. "Cargado" es terminal
 * (100%), igual que el check.
 */
import { describe, it, expect } from "vitest";
import { getSubtext } from "./ProcessingOverlay";

describe("getSubtext — fase upload", () => {
  it("sube hasta 99% sin cambiar el texto", () => {
    expect(getSubtext(0, "upload")).toBe("Subiendo tu track a WaveIA...");
    expect(getSubtext(50, "upload")).toBe("Subiendo tu track a WaveIA...");
    expect(getSubtext(99, "upload")).toBe("Subiendo tu track a WaveIA...");
  });

  it("100% confirma la subida y anuncia el análisis", () => {
    expect(getSubtext(100, "upload")).toBe("Subido — preparando el análisis...");
  });
});

describe("getSubtext — fase process (default)", () => {
  it("0–29%: análisis de espectro y gain staging", () => {
    expect(getSubtext(0)).toBe("Analizando espectro y aplicando Gain Staging...");
    expect(getSubtext(29)).toBe("Analizando espectro y aplicando Gain Staging...");
  });

  it("30–69%: algoritmos DSP", () => {
    expect(getSubtext(30)).toBe("Aplicando algoritmos DSP de Brikman Paul...");
    expect(getSubtext(69)).toBe("Aplicando algoritmos DSP de Brikman Paul...");
  });

  it("70–98%: modelado de true peak y noise shaping", () => {
    expect(getSubtext(70)).toBe("Modelando True Peak y Noise Shaping...");
    expect(getSubtext(98)).toBe("Modelando True Peak y Noise Shaping...");
  });

  it("99% SIGUE en modelado: 'Cargado' solo al 100% (regresión)", () => {
    // El check del anillo solo se dibuja en `clamped === 100`; el subtexto
    // tiene que contar la misma historia.
    expect(getSubtext(99)).toBe("Modelando True Peak y Noise Shaping...");
  });

  it("100% muestra 'Cargado' (estado terminal)", () => {
    expect(getSubtext(100)).toBe("Cargado");
  });
});
