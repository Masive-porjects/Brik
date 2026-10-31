import { describe, expect, it } from "vitest";

import type { AgentNarrativeItem } from "@/lib/api";
import en from "@/i18n/locales/en.json";
import es from "@/i18n/locales/es.json";

import { narrativeSentence } from "./narrativeText";

/**
 * `narrativeSentence` — cómo se convierte un item del backend en una frase.
 *
 * El backend manda un `code` estable y números; nunca prosa. Este test fija el
 * contrato completo: que los números se muestren con los decimales que
 * corresponden, que un `null` diga "sin medir" en vez de inventar un cero, que
 * un `code` desconocido no desaparezca en silencio, y que todo `code` que el
 * backend puede emitir exista en los DOS idiomas con los mismos placeholders.
 */

const dictionaries: Record<"es" | "en", unknown> = { es, en };

function resolvePath(source: unknown, path: string): string | null {
  let current: unknown = source;

  for (const part of path.split(".")) {
    if (current && typeof current === "object" && part in current) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return null;
    }
  }

  return typeof current === "string" ? current : null;
}

/** The same resolution `I18nContext` does: active locale, Spanish fallback,
 *  single-brace interpolation, and the path as the last resort. */
function translator(locale: "es" | "en") {
  return (
    path: string,
    params?: Record<string, string | number>,
    fallback?: string,
  ): string => {
    const value =
      resolvePath(dictionaries[locale], path) ??
      (locale === "es" ? null : resolvePath(dictionaries.es, path));

    if (value === null) return fallback ?? path;

    return Object.entries(params ?? {}).reduce(
      (acc, [key, val]) => acc.replace(new RegExp(`{${key}}`, "g"), String(val)),
      value,
    );
  };
}

function item(
  code: string,
  params: AgentNarrativeItem["params"] = {},
  severity: AgentNarrativeItem["severity"] = "info",
): AgentNarrativeItem {
  return { code, severity, params };
}

describe("narrativeSentence", () => {
  it("un número no medido dice 'sin medir', nunca 0", () => {
    const sentence = narrativeSentence(
      translator("es"),
      item("master_from_mix", { attempt: 1, lufs: null, peak: -1, crest: 9 }),
    );

    expect(sentence).not.toContain("0.0 LUFS");
    expect(sentence).toContain("— LUFS");
    expect(sentence).toContain("-1.0 dBTP");
  });

  it("los conteos son enteros y las mediciones llevan un decimal", () => {
    const sentence = narrativeSentence(
      translator("es"),
      item("mix_flagged", { iteration: 2, flags: 3 }),
    );

    expect(sentence).toContain("3 cosas");
    expect(sentence).toContain("iteración 2 ");
  });

  it("un conteo redondeado nunca muestra decimales", () => {
    const sentence = narrativeSentence(
      translator("en"),
      item("separated", { stems: 4 }),
    );

    expect(sentence).toContain("4 stems");
    expect(sentence).not.toContain("4.0");
  });

  it("el nombre de la herramienta se traduce, no se imprime crudo", () => {
    const sentence = narrativeSentence(
      translator("es"),
      item("step_failed", { tool: "render_mix" }),
    );

    expect(sentence).toContain("Renderizar la mezcla");
    expect(sentence).not.toContain("render_mix");
  });

  it("un código que el diccionario no conoce se muestra tal cual", () => {
    // Silenciarlo escondería un paso que la corrida realmente dio.
    expect(narrativeSentence(translator("es"), item("code_futuro"))).toBe(
      "code_futuro",
    );
  });

  it("la misma corrida se lee en español y en inglés", () => {
    const payload = item("master_from_mix", {
      attempt: 1,
      lufs: -14,
      peak: -1,
      crest: 9,
    });

    const spanish = narrativeSentence(translator("es"), payload);
    const english = narrativeSentence(translator("en"), payload);

    expect(spanish).toContain("Mastericé la mezcla");
    expect(english).toContain("I mastered the mix");
    expect(spanish).not.toBe(english);
  });
});

describe("el contrato con los diccionarios", () => {
  /** Every code `services.narrative.build_narrative` can emit, plus the
   *  dictionary-only key used for an unmeasured number. */
  const CODES = [
    "route_master_only",
    "analyzed_original",
    "separated",
    "mix_rendered",
    "mix_clean",
    "mix_flagged",
    "knowledge_consulted",
    "master_from_mix",
    "master_from_original",
    "master_corrected",
    "master_correction_reverted",
    "master_dynamic_warning",
    "step_failed",
  ];

  const placeholders = (text: string): string[] =>
    [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

  it("todo código del backend existe en los dos idiomas", () => {
    for (const code of CODES) {
      expect(resolvePath(es, `productor.narrative.${code}`), `es: ${code}`).toBeTypeOf(
        "string",
      );
      expect(resolvePath(en, `productor.narrative.${code}`), `en: ${code}`).toBeTypeOf(
        "string",
      );
    }
  });

  it("español e inglés interpolan exactamente los mismos parámetros", () => {
    for (const code of CODES) {
      const path = `productor.narrative.${code}`;

      expect(placeholders(resolvePath(es, path) ?? ""), `es: ${code}`).toEqual(
        placeholders(resolvePath(en, path) ?? ""),
      );
    }
  });

  it("ninguna frase deja un placeholder sin reemplazar", () => {
    for (const code of CODES) {
      for (const locale of ["es", "en"] as const) {
        const template = resolvePath(dictionaries[locale], `productor.narrative.${code}`) ?? "";
        const params = Object.fromEntries(
          placeholders(template).map((name) => [name, 1]),
        );

        const sentence = narrativeSentence(translator(locale), item(code, params));

        expect(sentence, `${locale}: ${code}`).not.toMatch(/\{\w+\}/);
        expect(sentence, `${locale}: ${code}`).not.toBe(code);
      }
    }
  });
});
