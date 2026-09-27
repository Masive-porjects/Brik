"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { useIsClient } from "@/lib/audioUtils";

interface WaveformBarsProps {
  isPlaying?: boolean;
  bars?: number;
}

export default function WaveformBars({ isPlaying = true, bars = 32 }: WaveformBarsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const barRefs = useRef<(HTMLDivElement | null)[]>([]);
  const tweensRef = useRef<gsap.core.Tween[]>([]);
  const isClient = useIsClient();

  useGSAP(
    () => {
      const els = barRefs.current.filter((el): el is HTMLDivElement => el !== null);
      tweensRef.current = els.map((el, i) =>
        gsap.to(el, {
          scaleY: gsap.utils.random(0.35, 1.45),
          duration: gsap.utils.random(0.9, 1.8),
          ease: "sine.inOut",
          repeat: -1,
          yoyo: true,
          delay: (i % 8) * 0.12,
        }),
      );
      tweensRef.current.forEach((t) => t.timeScale(isPlaying ? 1.6 : 0.7));
      return () => {
        tweensRef.current.forEach((t) => t.kill());
        tweensRef.current = [];
      };
    },
    { scope: containerRef, dependencies: [isClient] },
  );

  useEffect(() => {
    tweensRef.current.forEach((t) => t.timeScale(isPlaying ? 1.6 : 0.7));
  }, [isPlaying]);

  if (!isClient) return <div className="waveform-container" />;

  return (
    <div ref={containerRef} className="waveform-container">
      {Array.from({ length: bars }).map((_, i) => {
        const height = 12 + Math.sin(i * 0.5) * 18 + Math.cos(i * 0.3) * 8;
        return (
          <div
            key={i}
            ref={(el) => {
              barRefs.current[i] = el;
            }}
            className="waveform-bar"
            style={{
              height: `${height}px`,
              background: `linear-gradient(to top, var(--accent-primary), var(--accent-secondary))`,
              opacity: isPlaying ? 0.9 : 0.25,
              transition: "opacity 300ms",
            }}
          />
        );
      })}
    </div>
  );
}
