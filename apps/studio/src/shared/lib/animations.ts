/**
 * GSAP-style easing curves and transition presets for framer-motion.
 * All curves are GPU-friendly (transform/opacity only) and mobile-optimized.
 */
export const easings = {
  // GSAP power3.out ≈ cubic-bezier(0.215, 0.61, 0.355, 1)
  power3Out: [0.215, 0.61, 0.355, 1] as const,
  // GSAP expo.out ≈ [0.16, 1, 0.3, 1]
  expoOut: [0.16, 1, 0.3, 1] as const,
  // GSAP power2.out
  power2Out: [0.25, 0.46, 0.45, 0.94] as const,
  // Suave para micro-interacciones (Material Design standard)
  smooth: [0.4, 0, 0.2, 1] as const,
  // B7 unified landing choreography curve (ease-out, long tail)
  brandOut: [0.32, 0.72, 0, 1] as const,
  // Spring suave para layout animations
  springGentle: { type: "spring", stiffness: 350, damping: 30 } as const,
  // Spring para enter/exit rápido
  springQuick: { type: "spring", stiffness: 400, damping: 35 } as const,
} as const;

export const transitions = {
  // Hero entrance - slow, majestic
  heroEnter: { duration: 0.7, ease: easings.expoOut },
  heroEnterDelayed: (delay: number) => ({ duration: 0.7, delay, ease: easings.expoOut }),

  // Stagger text (words/chars)
  staggerText: { duration: 0.5, ease: easings.power3Out },

  // Card hover/tap micro-interactions
  cardHover: { duration: 0.25, ease: easings.power2Out },
  cardTap: { duration: 0.12, ease: easings.power2Out },

  // AnimatePresence (drawers, tabs, modals)
  presence: { duration: 0.32, ease: easings.smooth },

  // Scroll reveal (viewport trigger)
  scrollReveal: { duration: 0.6, ease: easings.expoOut },

  // Fast UI feedback (buttons, chips)
  uiFast: { duration: 0.15, ease: easings.power2Out },
} as const;

/** Helper to add will-change for GPU acceleration */
export const gpuAccelerate = {
  style: {
    willChange: "transform, opacity",
  },
} as const;

/** Reduced motion guard - respects prefers-reduced-motion */
export const reducedMotionGuard = {
  initial: false,
  animate: false,
  transition: { duration: 0 },
} as const;