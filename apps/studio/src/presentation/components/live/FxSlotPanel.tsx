/**
 * FxSlotPanel — 4-slot FX chain with Knob3D controls and preset selector.
 * Slot order: Filter → Drive → Delay → Reverb
 */

'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Knob3D } from './Knob3D';
import { FX_PRESETS, FX_PRESET_ORDER, FxPresetName } from '@/adapters/live/fxPresets';
import type { LiveParams } from '@/lib/live/liveParams.gen';

interface FxSlotPanelProps {
  params: LiveParams;
  onParamsChange: (params: Partial<LiveParams>) => void;
  onPresetChange: (preset: FxPresetName) => void;
  disabled?: boolean;
}

interface SlotDef {
  key: keyof LiveParams;
  label: string;
  param: Exclude<keyof LiveParams, 'ts'>;
  unit: string;
  color: 'primary' | 'accent' | 'drive' | 'filter' | 'reverb' | 'delay';
  secondary?: {
    key: Exclude<keyof LiveParams, 'ts'>;
    label: string;
    param: Exclude<keyof LiveParams, 'ts'>;
    unit: string;
    color: 'primary' | 'accent' | 'drive' | 'filter' | 'reverb' | 'delay';
  };
}

const SLOTS: readonly SlotDef[] = [
  { key: 'filter_cutoff', label: 'FILTER', param: 'filter_cutoff', unit: 'Hz', color: 'filter' as const, secondary: { key: 'filter_res', label: 'RES', param: 'filter_res', unit: '', color: 'filter' as const } },
  { key: 'drive', label: 'DRIVE', param: 'drive', unit: '', color: 'drive' as const },
  { key: 'delay_time', label: 'DELAY', param: 'delay_time', unit: 'ms', color: 'delay' as const, secondary: { key: 'echo_feedback', label: 'FEEDBACK', param: 'echo_feedback', unit: '', color: 'delay' as const } },
  { key: 'reverb_mix', label: 'REVERB', param: 'reverb_mix', unit: '', color: 'reverb' as const },
] as const;

export function FxSlotPanel({ params, onParamsChange, onPresetChange, disabled = false }: FxSlotPanelProps) {
  const [activePreset, setActivePreset] = useState<FxPresetName | null>(params.fx_preset ?? null);
  const [showPresetMenu, setShowPresetMenu] = useState(false);

  const handlePresetSelect = (preset: FxPresetName) => {
    setActivePreset(preset);
    setShowPresetMenu(false);
    onPresetChange(preset);
  };

  const formatFilterValue = (v: number) => {
    if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
    return `${Math.round(v)}`;
  };

  const formatDelayValue = (v: number) => `${Math.round(v)}`;

  return (
    <div
      className="fx-slot-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        padding: 16,
        background: 'rgba(18,18,22,0.6)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 16,
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Preset Selector */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.05)',
            borderRadius: 10,
            cursor: disabled ? 'not-allowed' : 'pointer',
          }}
          onClick={() => !disabled && setShowPresetMenu(true)}
        >
          <span style={{ fontSize: 12, color: '#8a8a8a', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Preset
          </span>
          <span style={{ fontWeight: 600, color: '#e8e8e8', textTransform: 'capitalize' }}>
            {activePreset || 'Custom'}
          </span>
          <motion.span
            animate={{ rotate: showPresetMenu ? 180 : 0 }}
            style={{ marginLeft: 'auto', color: '#627e84', fontSize: 14 }}
          >
            ▼
          </motion.span>
        </motion.div>

        {/* Live indicator */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 10px',
            background: 'rgba(52,199,89,0.15)',
            border: '1px solid rgba(52,199,89,0.3)',
            borderRadius: 20,
            fontSize: 11,
            color: '#34c759',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34c759', animation: 'pulse 1.5s infinite' }} />
          Live
        </div>
      </div>

      {/* Preset Dropdown */}
      <AnimatePresence>
        {showPresetMenu && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              marginTop: 8,
              zIndex: 10,
              background: 'rgba(26,26,32,0.98)',
              border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 12,
              padding: 8,
              backdropFilter: 'blur(16px)',
              boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
            }}
          >
            {FX_PRESET_ORDER.map((preset) => (
              <button
                key={preset}
                onClick={() => handlePresetSelect(preset)}
                disabled={disabled}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '12px 16px',
                  background: activePreset === preset ? 'rgba(98,126,132,0.15)' : 'transparent',
                  border: 'none',
                  borderRadius: 8,
                  color: '#e8e8e8',
                  fontSize: 13,
                  textAlign: 'left',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = activePreset === preset ? 'rgba(98,126,132,0.15)' : 'transparent'; }}
              >
                <span style={{ fontSize: 16 }}>{FX_PRESETS[preset].icon || '✨'}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>{preset}</div>
                  <div style={{ fontSize: 11, color: '#8a8a8a' }}>{FX_PRESETS[preset].description}</div>
                </div>
                {activePreset === preset && (
                  <span style={{ color: '#627e84', fontSize: 14 }}>✓</span>
                )}
              </button>
            ))}
            <button
              onClick={() => { setActivePreset(null); setShowPresetMenu(false); onParamsChange({ fx_preset: null }); }}
              disabled={disabled}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '12px 16px',
                background: 'transparent',
                border: 'none',
                borderRadius: 8,
                color: '#8a8a8a',
                fontSize: 13,
                textAlign: 'left',
                cursor: disabled ? 'not-allowed' : 'pointer',
                marginTop: 4,
              }}
            >
              <span style={{ fontSize: 16 }}>↩️</span>
              <span>Clear preset (Custom)</span>
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* FX Slots Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 16,
        }}
      >
        {SLOTS.map((slot) => (
          <motion.div
            key={slot.key}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * (SLOTS.indexOf(slot)) }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            {/* Slot Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: '#8a8a8a',
                  textTransform: 'uppercase',
                  letterSpacing: '0.1em',
                }}
              >
                {slot.label}
              </span>
            </div>

            {/* Primary Knob */}
            <Knob3D
              value={params[slot.param as keyof LiveParams] as number}
              onChange={(v) => onParamsChange({ [slot.param]: v })}
              label={slot.label}
              unit={slot.unit}
              color={slot.color}
              disabled={disabled}
              size={72}
              dataTestid={slot.key === 'filter_cutoff' ? 'knob-filter_cutoff' : undefined}
              decimals={slot.param === 'filter_cutoff' ? 0 : slot.param === 'delay_time' ? 0 : 2}
              formatValue={slot.param === 'filter_cutoff' ? formatFilterValue : slot.param === 'delay_time' ? formatDelayValue : undefined}
            />

            {/* Secondary Knob (if applicable) */}
            {slot.secondary && (() => {
              const sec = slot.secondary;
              return (
                <>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginTop: 8,
                      gap: 8,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: '#8a8a8a',
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                      }}
                    >
                      {sec.label}
                    </span>
                  </div>
                  <Knob3D
                    value={params[sec.param as keyof LiveParams] as number}
                    onChange={(v) => onParamsChange({ [sec.param]: v })}
                    label={sec.label}
                    unit={sec.unit}
                    color={sec.color}
                    disabled={disabled}
                    size={56}
                    decimals={1}
                  />
                </>
              );
            })()}
          </motion.div>
        ))}

        {/* Output Level Slot */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 8,
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: '#8a8a8a',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
              }}
            >
              OUTPUT
            </span>
            <span
              style={{
                fontSize: 11,
                color: '#627e84',
                fontWeight: 500,
              }}
            >
              {Math.round((params.output_level ?? 0.9) * 100)}%
            </span>
          </div>
          <Knob3D
            value={params.output_level ?? 0.9}
            onChange={(v) => onParamsChange({ output_level: v })}
            label="LEVEL"
            unit=""
            color="primary"
            disabled={disabled}
            size={72}
            decimals={0}
            formatValue={(v) => `${Math.round(v * 100)}%`}
          />
        </motion.div>
      </div>

      {/* Style for pulse animation */}
      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}