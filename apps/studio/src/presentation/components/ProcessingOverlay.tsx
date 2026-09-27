"use client";

import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState, useMemo } from "react";

type Phase = "upload" | "process";

interface ProcessingOverlayProps {
  progress: number;
  visible: boolean;
  phase?: Phase;
}

export function getSubtext(progress: number, phase: Phase = "process"): string {
  if (phase === "upload") {
    if (progress < 100) return "Subiendo tu track a WaveIA...";
    return "Subido — preparando el análisis...";
  }
  if (progress < 30) return "Analizando espectro y aplicando Gain Staging...";
  if (progress < 70) return "Aplicando algoritmos DSP de Brikman Paul...";
  if (progress < 100) return "Modelando True Peak y Noise Shaping...";
  return "Cargado";
}

export default function ProcessingOverlay({
  progress,
  visible,
  phase = "process",
}: ProcessingOverlayProps) {
  const clamped = Math.min(100, Math.max(0, Math.round(progress)));
  const subtext = useMemo(() => getSubtext(clamped, phase), [clamped, phase]);
  const [showCheck, setShowCheck] = useState(false);

  const radius = 72;
  const stroke = 6;
  const normalizedRadius = radius - stroke / 2;
  const circumference = 2 * Math.PI * normalizedRadius;
  const strokeDashoffset = circumference - (clamped / 100) * circumference;

  // When progress hits 100, show check mark briefly
  useEffect(() => {
    if (clamped === 100) {
      const t = setTimeout(() => setShowCheck(true), 300);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setShowCheck(false), 0);
    return () => clearTimeout(t);
  }, [clamped]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="processing-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{
            opacity: 0,
            scale: 1.04,
            transition: { duration: 0.5, ease: "easeOut" },
          }}
          className="fixed inset-0 z-[200] flex items-center justify-center"
          style={{
            background: "rgba(0, 0, 0, 0.35)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
          }}
        >
          <div className="flex flex-col items-center gap-6">
            {/* SVG Circular Progress Ring */}
            <div className="relative flex items-center justify-center">
              {/* Background glow ring */}
              <div
                className="absolute rounded-full"
                style={{
                  width: radius * 2 + 40,
                  height: radius * 2 + 40,
                  background:
                    "radial-gradient(circle, rgba(98,126,132,0.06) 0%, transparent 70%)",
                }}
              />

              <svg
                width={radius * 2}
                height={radius * 2}
                className="transform -rotate-90"
              >
                {/* Definition for gradient stroke */}
                <defs>
                  <linearGradient
                    id="progress-gradient"
                    x1="0%"
                    y1="0%"
                    x2="100%"
                    y2="100%"
                  >
                    <stop offset="0%" stopColor="#627e84" />
                    <stop offset="50%" stopColor="#829ca1" />
                    <stop offset="100%" stopColor="#627e84" />
                  </linearGradient>
                  <filter id="glow">
                    <feGaussianBlur stdDeviation="3" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>

                {/* Background track */}
                <circle
                  cx={radius}
                  cy={radius}
                  r={normalizedRadius}
                  fill="none"
                  stroke="var(--border-subtle)"
                  strokeWidth={stroke}
                />

                {/* Progress arc */}
                <motion.circle
                  cx={radius}
                  cy={radius}
                  r={normalizedRadius}
                  fill="none"
                  stroke="url(#progress-gradient)"
                  strokeWidth={stroke}
                  strokeLinecap="round"
                  strokeDasharray={circumference}
                  initial={false}
                  animate={{ strokeDashoffset }}
                  transition={{ duration: 0.3, ease: "easeOut" }}
                  filter="url(#glow)"
                />

                {/* Outer subtle ring glow */}
                <circle
                  cx={radius}
                  cy={radius}
                  r={normalizedRadius + 4}
                  fill="none"
                  stroke="rgba(98,126,132,0.08)"
                  strokeWidth={1}
                />
              </svg>

              {/* Center content: percentage or checkmark */}
              <div className="absolute inset-0 flex items-center justify-center">
                <AnimatePresence mode="wait">
                  {showCheck ? (
                    <motion.div
                      key="check"
                      initial={{ scale: 0, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{
                        type: "spring",
                        stiffness: 300,
                        damping: 20,
                      }}
                    >
                      <svg
                        width={48}
                        height={48}
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="var(--accent-primary)"
                        strokeWidth={2.5}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <motion.path
                          d="M5 13l4 4L19 7"
                          initial={{ pathLength: 0 }}
                          animate={{ pathLength: 1 }}
                          transition={{ duration: 0.4, ease: "easeOut" }}
                        />
                      </svg>
                    </motion.div>
                  ) : (
                    <motion.span
                      key="percent"
                      initial={{ opacity: 1 }}
                      exit={{ opacity: 0, scale: 0.8 }}
                      className="font-mono text-4xl font-extrabold text-[var(--text-primary)] tracking-tighter"
                    >
                      {clamped}%
                    </motion.span>
                  )}
                </AnimatePresence>
              </div>
            </div>

            {/* Subtext */}
            <AnimatePresence mode="wait">
              <motion.p
                key={subtext}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3 }}
                className="text-sm text-[var(--text-secondary)] text-center max-w-xs"
              >
                {showCheck ? (
                  <span className="text-[var(--accent-primary)] font-medium">
                    Cargado
                  </span>
                ) : (
                  subtext
                )}
              </motion.p>
            </AnimatePresence>

            {/* Subtle branding */}
            {!showCheck && (
              <p className="text-[10px] text-[var(--text-muted)] tracking-widest uppercase">
                {phase === "upload" ? "WAVEAI" : "WaveEngine"}
              </p>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
