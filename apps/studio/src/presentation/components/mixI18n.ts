/**
 * Etapas reales de la cadena DSP del módulo de mezcla.
 *
 * Honestidad técnica: las etapas existen SIEMPRE en la cadena real de
 * ``build_mix`` y están en el MISMO orden en que el engine reporta cada
 * ``(percent, stage)``: split (Demucs) → paneo → EQ/compresión por stem →
 * dimensión delay/reverb → compresión de bus → énfasis por género → bus
 * (LUFS/limitador) → upload a R2. El backend no inventa porcentajes: los
 * reporta el propio engine, y la UI solo muestra lo que ya midió. Con
 * ``dimension_enabled: false`` el backend omite el paso de dimensión y la
 * UI filtra la etapa "dimension".
 */

export interface MixStatusStage {
  id: string;
  label: string;
}

export const MIX_STATUS_STAGES: MixStatusStage[] = [
  { id: "split", label: "Análisis de espectro: separando stems" },
  { id: "pan", label: "Balance y paneo estéreo" },
  { id: "eq", label: "EQ correctiva por banda" },
  { id: "dimension", label: "Dimensión espacial (delay + reverb)" },
  { id: "dynamics", label: "Compresión multibanda" },
  { id: "emphasis", label: "Énfasis por género" },
  { id: "bus", label: "LUFS / limitador: normalizando el bus" },
  { id: "upload", label: "Subiendo el master a la nube" },
];
