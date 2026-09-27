/**
 * FX Presets — Pre-defined parameter sets for instant vibe switching.
 * Each preset maps to a specific IR type and parameter values.
 */

import type { LiveParams } from '@/lib/live/liveParams.gen';

export type FxPresetName = 'clean' | 'dub' | 'big_room' | 'radio';

export interface FxPresetDef {
  name: FxPresetName;
  label: string;
  description: string;
  irType: 'plate' | 'hall' | 'room' | 'chamber' | 'spring';
  params: Partial<LiveParams>;
  icon: string;
}

export const FX_PRESETS: Record<FxPresetName, FxPresetDef> = {
  clean: {
    name: 'clean',
    label: 'Clean',
    description: 'Transparent bypass — no coloration',
    irType: 'room',
    icon: '✨',
    params: {
      filter_cutoff: 12000,
      filter_res: 0.7,
      drive: 0,
      delay_time: 250,
      echo_feedback: 0,
      reverb_mix: 0.05,
      output_level: 0.9,
    },
  },
  dub: {
    name: 'dub',
    label: 'Dub',
    description: 'Deep echo with heavy feedback — classic dub style',
    irType: 'plate',
    icon: '🎛️',
    params: {
      filter_cutoff: 4000,
      filter_res: 2.5,
      drive: 0.15,
      delay_time: 375,      // Dotted 8th at 120 BPM
      echo_feedback: 0.65,
      reverb_mix: 0.4,
      output_level: 0.85,
    },
  },
  big_room: {
    name: 'big_room',
    label: 'Big Room',
    description: 'Massive hall reverb — festival mainstage energy',
    irType: 'hall',
    icon: '🏟️',
    params: {
      filter_cutoff: 8000,
      filter_res: 0.7,
      drive: 0.25,
      delay_time: 120,
      echo_feedback: 0.2,
      reverb_mix: 0.7,
      output_level: 0.8,
    },
  },
  radio: {
    name: 'radio',
    label: 'Radio',
    description: 'Lo-fi bandpass + spring reverb — vintage broadcast',
    irType: 'spring',
    icon: '📻',
    params: {
      filter_cutoff: 3500,
      filter_res: 8.0,       // Sharp bandpass
      drive: 0.5,
      delay_time: 50,
      echo_feedback: 0.1,
      reverb_mix: 0.3,
      output_level: 0.9,
    },
  },
};

/**
 * Ordered list for UI selectors
 */
export const FX_PRESET_ORDER: FxPresetName[] = ['clean', 'dub', 'big_room', 'radio'];

/**
 * Get preset by name with fallback
 */
export function getPreset(name: string): FxPresetDef {
  return FX_PRESETS[name as FxPresetName] ?? FX_PRESETS.clean;
}

/**
 * Apply preset to LiveParams (returns new params object)
 */
export function applyPreset(params: LiveParams, presetName: FxPresetName): LiveParams {
  const preset = getPreset(presetName);
  return {
    ...params,
    ...preset.params,
    fx_preset: presetName,
    ts: Date.now(),
  };
}