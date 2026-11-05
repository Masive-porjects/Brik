"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { GhostIcon } from "@/components/ThemeToggle";

const GHOST_COUNT = 8;

interface GhostSpec {
  left: number;
  top: number;
  size: number;
  opacity: number;
  blurred: boolean;
  driftX: number;
  driftY: number;
  rotationAmp: number;
  duration: number;
  phase: number;
}

/* Deterministic pseudo-random so the server and client renders produce
   the exact same ghost layout (hydration-safe), like FloatingNotes. */
function seeded(index: number): number {
  const x = Math.sin(index * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

const GHOST_SPECS: GhostSpec[] = Array.from({ length: GHOST_COUNT }, (_, i) => ({
  left: 3 + seeded(i * 2 + 1) * 94,
  top: 5 + seeded(i * 2 + 2) * 88,
  size: 26 + seeded(i * 3 + 3) * 30,
  opacity: 0.18 + seeded(i * 3 + 4) * 0.28,
  blurred: seeded(i * 3 + 5) > 0.55,
  driftX: -26 + seeded(i * 5 + 8) * 52,
  driftY: -40 + seeded(i * 5 + 9) * 80,
  rotationAmp: 3 + seeded(i * 5 + 10) * 8,
  duration: 9 + seeded(i * 5 + 11) * 8,
  phase: seeded(i * 5 + 12),
}));

interface FloatingGhostsProps {
  /** Stacking order of the layer; callers control it per mounting context. */
  zIndex?: number;
  /** Extra classes appended to the fixed layer. */
  className?: string;
}

/**
 * Ambient brand ghosts ("Mente y Alma") drifting across the viewport,
 * appearing and disappearing in a slow loop. Purely decorative.
 */
export default function FloatingGhosts({
  zIndex,
  className,
}: FloatingGhostsProps) {
  const scopeRef = useRef<HTMLDivElement>(null);
  const ghostRefs = useRef<(HTMLSpanElement | null)[]>([]);

  useGSAP(
    () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const els = ghostRefs.current.filter(
        (el): el is HTMLSpanElement => el !== null,
      );
      els.forEach((el, i) => {
        const spec = GHOST_SPECS[i];
        /* Ghosts appear, drift, then vanish in a slow loop. Negative delays
           desync the loops so the scene feels alive from the first frame. */
        gsap
          .timeline({ repeat: -1, delay: -spec.duration * spec.phase })
          .fromTo(
            el,
            { opacity: 0, x: 0, y: 0, rotation: 0 },
            {
              opacity: spec.opacity,
              duration: spec.duration * 0.22,
              ease: "power1.inOut",
            },
          )
          .to(
            el,
            {
              x: spec.driftX,
              y: spec.driftY,
              rotation: spec.rotationAmp,
              duration: spec.duration * 0.5,
              ease: "sine.inOut",
            },
            "<",
          )
          .to(el, {
            opacity: 0,
            duration: spec.duration * 0.28,
            ease: "power1.inOut",
          });
      });
    },
    { scope: scopeRef },
  );

  return (
    <div
      ref={scopeRef}
      aria-hidden="true"
      className={`pointer-events-none fixed inset-0 overflow-hidden [contain:layout] ${className ?? ""}`}
      style={{ zIndex }}
    >
      {GHOST_SPECS.map((spec, i) => (
        <span
          key={i}
          ref={(el) => {
            ghostRefs.current[i] = el;
          }}
          className="absolute block [&>svg]:h-full [&>svg]:w-full text-[var(--accent-primary)]"
          style={{
            left: `${spec.left}%`,
            top: `${spec.top}%`,
            width: spec.size,
            height: spec.size,
            opacity: 0,
            transform: "rotate(0deg)",
            filter: spec.blurred ? "blur(1.5px)" : "none",
          }}
        >
          <GhostIcon size={spec.size} />
        </span>
      ))}
    </div>
  );
}
