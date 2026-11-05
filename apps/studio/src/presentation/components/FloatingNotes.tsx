"use client";

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { MusicNote } from "@/components/Player";

/* Same accent palette used by the note bursts in Player.tsx / page.tsx */
const NOTE_COLORS = ["#ff5a5f", "#ffb347", "#4ecdc4", "#7b68ee", "#ff6b9d"];

const NOTE_COUNT = 16;

interface NoteSpec {
  left: number;
  top: number;
  size: number;
  opacity: number;
  blurred: boolean;
  rotation: number;
  color: string;
  driftX: number;
  driftY: number;
  rotationAmp: number;
  duration: number;
}

/* Deterministic pseudo-random so the server and client renders produce
   the exact same note layout (hydration-safe), while still looking
   organic and scattered. */
function seeded(index: number): number {
  const x = Math.sin(index * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

/**
 * Redondea a 3 decimales.
 *
 * Los valores seeded son deterministas, pero React serializa un number en el
 * HTML del servidor con distinta precision que la que aplica en el cliente, y
 * eso dispara un hydration mismatch. Con valores ya redondeados los dos lados
 * escriben exactamente lo mismo.
 */
const r3 = (n: number): number => Math.round(n * 1000) / 1000;

const NOTE_SPECS: NoteSpec[] = Array.from({ length: NOTE_COUNT }, (_, i) => ({
  left: r3(2 + seeded(i * 2 + 1) * 96),
  top: r3(3 + seeded(i * 2 + 2) * 93),
  size: r3(14 + seeded(i * 3 + 3) * 20),
  opacity: r3(0.25 + seeded(i * 3 + 4) * 0.4),
  blurred: seeded(i * 3 + 5) > 0.5,
  rotation: r3(-45 + seeded(i * 3 + 6) * 90),
  color: NOTE_COLORS[Math.floor(seeded(i * 5 + 7) * NOTE_COLORS.length)],
  driftX: -20 + seeded(i * 5 + 8) * 40,
  driftY: -30 + seeded(i * 5 + 9) * 60,
  rotationAmp: 4 + seeded(i * 5 + 10) * 10,
  duration: 8 + seeded(i * 5 + 11) * 8,
}));

interface FloatingNotesProps {
  /** Stacking order of the layer; callers control it per mounting context. */
  zIndex?: number;
  /** Extra classes appended to the fixed layer (e.g. Tailwind z-* utilities). */
  className?: string;
}

/**
 * Ambient decorative music notes drifting slowly across the whole viewport.
 * Purely decorative: aria-hidden and pointer-events-none.
 */
export default function FloatingNotes({
  zIndex,
  className,
}: FloatingNotesProps) {
  const scopeRef = useRef<HTMLDivElement>(null);
  const noteRefs = useRef<(HTMLSpanElement | null)[]>([]);

  useGSAP(
    () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const els = noteRefs.current.filter(
        (el): el is HTMLSpanElement => el !== null,
      );
      els.forEach((el, i) => {
        const spec = NOTE_SPECS[i];
        gsap.fromTo(
          el,
          { x: 0, y: 0, rotation: spec.rotation },
          {
            x: spec.driftX,
            y: spec.driftY,
            rotation: spec.rotation + spec.rotationAmp,
            duration: spec.duration,
            ease: "sine.inOut",
            yoyo: true,
            repeat: -1,
            /* Negative delay starts each note mid-flight so the field
               feels alive from the first frame instead of synced. */
            delay: -spec.duration * 0.45,
          },
        );
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
      {NOTE_SPECS.map((spec, i) => (
        <span
          key={i}
          ref={(el) => {
            noteRefs.current[i] = el;
          }}
          className="absolute block [&>svg]:h-full [&>svg]:w-full"
          style={{
            left: `${spec.left}%`,
            top: `${spec.top}%`,
            width: `${spec.size}px`,
            height: `${spec.size}px`,
            opacity: spec.opacity,
            transform: `rotate(${spec.rotation}deg)`,
            filter: spec.blurred ? "blur(1.5px)" : "none",
          }}
        >
          <MusicNote color={spec.color} />
        </span>
      ))}
    </div>
  );
}
