/**
 * Etapas reales de la cadena DSP del módulo de mezcla.
 *
 * Honestidad técnica: las 7 etapas existen SIEMPRE en la cadena real de
 * ``build_mix`` (apps/audiomind/processing/mix_engine.py: split → EQ mágico
 * → paneo → dimensión delay/reverb → compresión → énfasis por género →
 * bus). Lo único simulado es el timing de cuándo se muestra cada etapa en
 * la UI (mismo ticker de la barra: cap 95 %, 100 % solo con la respuesta
 * real del backend). Con ``dimension_enabled: false`` el backend omite el
 * paso de dimensión y la UI filtra la etapa "dimension".
 */

export interface MixStatusStage {
  id: string;
  label: string;
}

export const MIX_STATUS_STAGES: MixStatusStage[] = [
  { id: "split", label: "Análisis de espectro: separando stems" },
  { id: "eq", label: "EQ correctiva por banda" },
  { id: "pan", label: "Balance y paneo estéreo" },
  { id: "dimension", label: "Dimensión espacial (delay + reverb)" },
  { id: "dynamics", label: "Compresión multibanda" },
  { id: "emphasis", label: "Énfasis por género" },
  { id: "bus", label: "LUFS / limitador: normalizando el bus" },
];