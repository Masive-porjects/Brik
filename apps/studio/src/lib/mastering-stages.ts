/**
 * 13 etapas del pipeline DSP de mastering (backend AudioMind)
 * Fuente: docs/reference/specs/08_implementacion_llm.md §5.2
 * 
 * NOTA: Las etapas 7a–7e y "Bloque espacial" son opt-in (flags *_enabled).
 * Neutral = bypass bit-exacto: cuando todos los parámetros están en defaults,
 * el master suena idéntico al original.
 */

export interface MasteringStage {
  /** Número de etapa (1–13, con sub-etapas 7a–7e) */
  index: number | string;
  /** Nombre identificador para claves/i18n */
  key: string;
  /** Etiqueta legible para UI (español latino neutro) */
  label: string;
  /** Descripción técnica corta */
  description: string;
  /** Si la etapa es opcional/opt-in */
  optional: boolean;
  /** Parámetros principales que afectan esta etapa (referencia a MasteringParameters) */
  parameters: string[];
  /** Si es bypass bit-exacto en modo neutral */
  neutralBypass: boolean;
}

export const MASTERING_STAGES: readonly MasteringStage[] = [
  {
    index: 1,
    key: 'gainStaging',
    label: 'Gain Staging',
    description: 'Peak-normalize a −6 dBFS',
    optional: false,
    parameters: [],
    neutralBypass: false, // siempre se ejecuta
  },
  {
    index: 2,
    key: 'highPass',
    label: 'High-pass 30 Hz',
    description: 'Filtro high-pass a 30 Hz (pedalboard HighpassFilter)',
    optional: false,
    parameters: [],
    neutralBypass: false,
  },
  {
    index: 3,
    key: 'matchEq',
    label: 'Match EQ',
    description: 'Delta = (target−current)×1.8; ×0.8 si already-mastered; clamp ±2 dB; skip < 0.3 dB',
    optional: false,
    parameters: ['clarity_wet', 'clarity_brightness_db'],
    neutralBypass: true,
  },
  {
    index: 4,
    key: 'clarityShelf',
    label: 'Clarity Shelf 8 kHz',
    description: 'Shelf 8 kHz Q 0.6, gain = brightness; skip si 0',
    optional: false,
    parameters: ['clarity_brightness_db'],
    neutralBypass: true,
  },
  {
    index: 5,
    key: 'warmthTilt',
    label: 'Warmth Tilt 10 kHz',
    description: 'Tilt 10 kHz Q 0.5, skip si 0',
    optional: false,
    parameters: ['saturation_warmth_db'],
    neutralBypass: true,
  },
  {
    index: 6,
    key: 'mainCompressor',
    label: 'Compresor Principal',
    description: 'Threshold = −16 − 1.5·punch; ratio ×0.8 si mastered; attack max(3, 20−3·punch) ms; release 200 ms',
    optional: false,
    parameters: ['compression_ratio', 'transient_boost_db'],
    neutralBypass: true,
  },
  {
    index: 7,
    key: 'boardRender',
    label: 'Board Render (Pedalboard)',
    description: 'Una pasada completa del grafo pedalboard',
    optional: false,
    parameters: [],
    neutralBypass: false,
  },
  {
    index: '7a',
    key: 'adaptiveCompressor',
    label: 'Compresor Adaptativo',
    description: 'Opcional; neutral ratio 1.0 = bypass bit-exacto',
    optional: true,
    parameters: ['adaptive_comp_enabled', 'adaptive_comp_ratio', 'adaptive_comp_attack_ms', 'adaptive_comp_release_ms'],
    neutralBypass: true,
  },
  {
    index: '7b',
    key: 'multiband',
    label: 'Multiband LR4',
    description: 'Opcional; crossover 150 Hz / 3 kHz; neutral = bypass',
    optional: true,
    parameters: ['multiband_enabled', 'multiband_low_gain_db', 'multiband_mid_gain_db', 'multiband_high_gain_db'],
    neutralBypass: true,
  },
  {
    index: '7c',
    key: 'dynamicEq',
    label: 'Dynamic EQ (Cuts Only)',
    description: 'Opcional; solo cortes; neutral = bypass',
    optional: true,
    parameters: ['dyn_eq_enabled', 'dyn_eq_band1_freq_hz', 'dyn_eq_band1_gain_db', 'dyn_eq_band2_freq_hz', 'dyn_eq_band2_gain_db', 'dyn_eq_band3_freq_hz', 'dyn_eq_band3_gain_db', 'dyn_eq_band4_freq_hz', 'dyn_eq_band4_gain_db'],
    neutralBypass: true,
  },
  {
    index: '7d',
    key: 'harmonicExciter',
    label: 'Excitador Armónico 4 Bandas',
    description: 'Opcional; neutral = bypass',
    optional: true,
    parameters: ['exciter_band1_enabled', 'exciter_band1_drive', 'exciter_band2_enabled', 'exciter_band2_drive', 'exciter_band3_enabled', 'exciter_band3_drive', 'exciter_band4_enabled', 'exciter_band4_drive'],
    neutralBypass: true,
  },
  {
    index: '7e',
    key: 'stereoImaging',
    label: 'Stereo Imaging LR4',
    description: 'Opcional; neutral = bypass',
    optional: true,
    parameters: ['stereo_imaging_enabled', 'stereo_imaging_width', 'stereo_imaging_crossover_hz'],
    neutralBypass: true,
  },
  {
    index: 'spatial',
    key: 'spatialBlock',
    label: 'Bloque Espacial (M/S, Reverb Side, Haas)',
    description: 'Opcional; check correlación < 0 → safety',
    optional: true,
    parameters: ['stereo_width', 'haas_delay_ms'],
    neutralBypass: true,
  },
  {
    index: 8,
    key: 'saturation',
    label: 'Saturación (Tape / Tanh)',
    description: 'Tape real o tanh legacy; neutral = untouched',
    optional: false,
    parameters: ['saturation_drive_db', 'saturation_warmth_db'],
    neutralBypass: true,
  },
  {
    index: 9,
    key: 'monoCompat',
    label: 'Mono Compat Lows < 120 Hz',
    description: 'Colapsa bajos a mono; skip si 7e ya colapsó lows',
    optional: false,
    parameters: [],
    neutralBypass: true,
  },
  {
    index: 10,
    key: 'loudnessTarget',
    label: 'Loudness Target',
    description: 'Target explícito o derivado: −14 + (1 − ceiling/−0.3)·6, clamp [−14, −8]; corrección −12…+6 dB',
    optional: false,
    parameters: ['target_lufs_db', 'limiter_ceiling_db'],
    neutralBypass: false,
  },
  {
    index: '11a',
    key: 'codecPreMatching',
    label: 'Codec Pre-matching',
    description: 'Ceiling seguro por crest factor',
    optional: false,
    parameters: ['limiter_ceiling_db'],
    neutralBypass: false,
  },
  {
    index: '11b',
    key: 'softClipper',
    label: 'Soft Clipper 16× Oversampled',
    description: 'erf-knee, threshold = safe ceiling − 1.5 dB',
    optional: false,
    parameters: ['limiter_ceiling_db'],
    neutralBypass: false,
  },
  {
    index: '11c',
    key: 'truePeakLimiter',
    label: 'True-Peak Limiter 8× Oversampled',
    description: 'Lookahead L=4 ms, release ~30 ms, safety net 0 dBFS',
    optional: false,
    parameters: ['limiter_ceiling_db'],
    neutralBypass: false,
  },
  {
    index: 12,
    key: 'safetyNormalize',
    label: 'Safety Normalize',
    description: 'Sample > 1.0 → 0.99',
    optional: false,
    parameters: [],
    neutralBypass: false,
  },
  {
    index: 'dither',
    key: 'dither',
    label: 'Dither (16-bit: TPDF + Lipshitz; 24-bit: nada)',
    description: 'Ruido TPDF con noise shaping Lipshitz solo en 16-bit',
    optional: false,
    parameters: ['output_bit_depth'],
    neutralBypass: false,
  },
  {
    index: 13,
    key: 'drValidation',
    label: 'Validación DR',
    description: 'Warn si output/input DR < 0.8',
    optional: false,
    parameters: [],
    neutralBypass: false,
  },
] as const;

/** Etapas obligatorias (no opt-in) */
export const REQUIRED_STAGES = MASTERING_STAGES.filter(s => !s.optional);

/** Etapas opt-in (requieren flag *_enabled) */
export const OPTIONAL_STAGES = MASTERING_STAGES.filter(s => s.optional);

/** Etapas que son neutral bypass (sonido idéntico en defaults) */
export const NEUTRAL_BYPASS_STAGES = MASTERING_STAGES.filter(s => s.neutralBypass);

/** Mapa rápido por key */
export const STAGES_BY_KEY = Object.fromEntries(
  MASTERING_STAGES.map(s => [s.key, s])
) as Record<string, MasteringStage>;

/** Para selectores de UI: solo etapas visibles (agrupa 7a–7e bajo "Procesamiento Avanzado") */
export const UI_STAGE_GROUPS = [
  {
    groupKey: 'core',
    groupLabel: 'Procesamiento Base',
    stages: REQUIRED_STAGES.filter(s => typeof s.index === 'number' && s.index <= 7),
  },
  {
    groupKey: 'advanced',
    groupLabel: 'Procesamiento Avanzado (Opt-in)',
    stages: OPTIONAL_STAGES,
  },
  {
    groupKey: 'final',
    groupLabel: 'Finalización y Seguridad',
    stages: REQUIRED_STAGES.filter(s => typeof s.index !== 'number' || s.index >= 8),
  },
] as const;

export type StageKey = typeof MASTERING_STAGES[number]['key'];
export type StageIndex = typeof MASTERING_STAGES[number]['index'];