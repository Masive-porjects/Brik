/**
 * Knob3D — 3D-styled rotary knob with reactive lighting.
 * Accessible: keyboard (arrows), mouse drag, touch.
 */

'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface Knob3DProps {
  /** Current value 0-1 */
  value: number;
  /** Callback on value change */
  onChange: (value: number) => void;
  /** Display label */
  label: string;
  /** Unit suffix */
  unit?: string;
  /** Disabled state */
  disabled?: boolean;
  /** Size in px */
  size?: number;
  /** Color theme */
  color?: 'primary' | 'accent' | 'drive' | 'filter' | 'reverb' | 'delay';
  /** Show value display */
  showValue?: boolean;
  /** Decimals for display */
  decimals?: number;
  /** Custom value formatter */
  formatValue?: (v: number) => string;
  /** Test id for E2E */
  dataTestid?: string;
}

const COLOR_THEMES: Record<string, { track: string; fill: string; glow: string; knob: string }> = {
  primary: { track: '#1a1a22', fill: 'linear-gradient(90deg, #627e84, #829ca1)', glow: '#627e84', knob: '#2a2a35' },
  accent:  { track: '#1a1a22', fill: 'linear-gradient(90deg, #829ca1, #627e84)', glow: '#829ca1', knob: '#2a2a35' },
  drive:   { track: '#2a1515', fill: 'linear-gradient(90deg, #ff3b30, #ff6b35)', glow: '#ff3b30', knob: '#3a1a1a' },
  filter:  { track: '#152a25', fill: 'linear-gradient(90deg, #00d4aa, #00b894)', glow: '#00d4aa', knob: '#1a3a33' },
  reverb:  { track: '#251a3a', fill: 'linear-gradient(90deg, #af52de, #8944b8)', glow: '#af52de', knob: '#2a1a3a' },
  delay:   { track: '#2a2515', fill: 'linear-gradient(90deg, #ff9500, #ffaa00)', glow: '#ff9500', knob: '#3a331a' },
};

export function Knob3D({
  value,
  onChange,
  label,
  unit = '',
  disabled = false,
  size = 80,
  color = 'primary',
  showValue = true,
  decimals = 2,
  formatValue,
  dataTestid,
}: Knob3DProps) {
  const theme = COLOR_THEMES[color] || COLOR_THEMES.primary;
  const knobRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [hovered, setHovered] = useState(false);
  const startY = useRef(0);
  const startValue = useRef(value);

  // Format display value
  const displayValue = formatValue 
    ? formatValue(value)
    : (value * 100).toFixed(decimals === 0 ? 0 : decimals).replace(/\.?0+$/, '');

  // Rotation: -135deg to +135deg (270° range)
  const rotation = -135 + value * 270;

  const handleMouseDown = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    if (disabled) return;
    e.preventDefault();
    setIsDragging(true);
    startY.current = 'touches' in e ? e.touches[0].clientY : e.clientY;
    startValue.current = value;
    document.body.style.userSelect = 'none';
  }, [disabled, value]);

  const handleMouseMove = useCallback((e: MouseEvent | TouchEvent) => {
    if (!isDragging || disabled) return;
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY;
    const deltaY = startY.current - clientY;
    const sensitivity = 0.003;
    let newValue = startValue.current + deltaY * sensitivity;
    newValue = Math.max(0, Math.min(1, newValue));
    onChange(newValue);
  }, [isDragging, disabled, onChange]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    document.body.style.userSelect = '';
  }, []);

  useEffect(() => {
    if (isDragging) {
      const moveHandler = (e: MouseEvent | TouchEvent) => handleMouseMove(e);
      const upHandler = () => handleMouseUp();
      window.addEventListener('mousemove', moveHandler);
      window.addEventListener('mouseup', upHandler);
      window.addEventListener('touchmove', moveHandler, { passive: false });
      window.addEventListener('touchend', upHandler);
      return () => {
        window.removeEventListener('mousemove', moveHandler);
        window.removeEventListener('mouseup', upHandler);
        window.removeEventListener('touchmove', moveHandler);
        window.removeEventListener('touchend', upHandler);
      };
    }
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // Keyboard support
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (disabled) return;
      const knob = knobRef.current;
      if (!knob || !knob.matches(':focus, :focus-within')) return;

      let delta = 0;
      if (e.key === 'ArrowUp') delta = 0.01;
      else if (e.key === 'ArrowDown') delta = -0.01;
      else if (e.key === 'ArrowRight') delta = 0.05;
      else if (e.key === 'ArrowLeft') delta = -0.05;
      else if (e.key === 'Home') delta = 1 - value;
      else if (e.key === 'End') delta = -value;
      else return;

      e.preventDefault();
      onChange(Math.max(0, Math.min(1, value + delta)));
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [disabled, value, onChange]);

  const knobStyle: React.CSSProperties = {
    width: size,
    height: size,
    transform: `rotate(${rotation}deg)`,
    transition: isDragging ? 'none' : 'transform 0.05s ease-out',
  };

  const indicatorStyle: React.CSSProperties = {
    width: size * 0.12,
    height: size * 0.45,
    background: theme.fill,
    borderRadius: size * 0.06,
    boxShadow: `0 0 ${size * 0.15}px ${theme.glow}`,
    transformOrigin: `center ${size * 0.55}px`,
  };

  return (
    <div
      ref={knobRef}
      className="knob3d"
      data-testid={dataTestid}
      tabIndex={disabled ? -1 : 0}
      role="slider"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={value}
      aria-disabled={disabled}
      onMouseDown={handleMouseDown}
      onTouchStart={(e) => handleMouseDown(e as React.TouchEvent)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative',
        width: size,
        height: size,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: size * 0.12,
        cursor: disabled ? 'not-allowed' : 'grab',
      }}
    >
      {/* 3D Knob Visual */}
      <div
        style={{
          position: 'relative',
          width: size,
          height: size,
          borderRadius: '50%',
          background: `
            radial-gradient(circle at 30% 30%, ${theme.knob}44 0%, transparent 70%),
            radial-gradient(circle at 70% 70%, #0a0a0c 0%, transparent 60%),
            ${theme.track}
          `,
          boxShadow: `
            inset 0 ${size * 0.04}px ${size * 0.08}px rgba(0,0,0,0.7),
            inset 0 -${size * 0.02}px ${size * 0.04}px rgba(255,255,255,0.03),
            0 ${size * 0.04}px ${size * 0.12}px rgba(0,0,0,0.5),
            ${isDragging || hovered ? `0 0 ${size * 0.2}px ${theme.glow}88` : ''}
          `,
          transition: 'box-shadow 0.15s ease',
        }}
      >
        {/* Rotating indicator */}
        <motion.div
          style={indicatorStyle}
          animate={{ rotate: rotation }}
          transition={{ duration: isDragging ? 0 : 0.05, ease: 'easeOut' }}
        />
        
        {/* Center cap */}
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: size * 0.28,
            height: size * 0.28,
            borderRadius: '50%',
            background: `radial-gradient(circle at 30% 30%, ${theme.knob} 0%, ${theme.track} 100%)`,
            boxShadow: `
              inset 0 -${size * 0.02}px ${size * 0.04}px rgba(0,0,0,0.5),
              inset 0 ${size * 0.01}px ${size * 0.02}px rgba(255,255,255,0.05)
            `,
          }}
        />
      </div>

      {/* Value Display */}
      <AnimatePresence mode="wait">
        {showValue && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            style={{
              fontSize: size * 0.18,
              fontWeight: 600,
              fontFamily: 'Inter, monospace',
              color: isDragging ? theme.glow : '#e8e8e8',
              textShadow: isDragging ? `0 0 ${size * 0.08}px ${theme.glow}` : 'none',
              transition: 'all 0.1s ease',
              display: 'flex',
              alignItems: 'center',
              gap: 2,
            }}
          >
            {displayValue}
            <span style={{ fontSize: size * 0.12, color: '#8a8a8a', fontWeight: 400 }}>{unit}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Label */}
      <span
        style={{
          fontSize: size * 0.14,
          color: '#8a8a8a',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontWeight: 500,
        }}
      >
        {label}
      </span>
    </div>
  );
}