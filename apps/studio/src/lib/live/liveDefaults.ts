/**
 * Defaults del LiveParams — fuente de verdad: packages/contracts/live_params.schema.json
 *
 * Neutral = defaults del schema = master idéntico al original (regla AGENTS.md).
 * Se usa para el estado inicial del Live Engine.
 */
import type { LiveParams } from './liveParams.gen';

export const LIVE_PARAM_DEFAULTS: LiveParams = {
  ts: 0, // se sobreescribe con Date.now() al aplicar
  filter_cutoff: 12000,
  filter_res: 0.7,
  drive: 0,
  delay_time: 250,
  echo_feedback: 0,
  reverb_mix: 0,
  output_level: 0.9,
  fx_preset: null,
};
