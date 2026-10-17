"use client";

import { useEffect, type RefObject } from "react";
import gsap from "gsap";
import { SplitText } from "gsap/SplitText";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(SplitText, ScrollTrigger);

/**
 * Word-by-word tagline "lighting" controller.
 *
 * Ownership: the caller owns ONE `containerRef` on the tagline <section>. This
 * hook never returns refs and never reads or writes a ref during render — the
 * statement and its decorative elements are discovered through `data-tagline*`
 * hooks inside the effect, which keeps `react-hooks/refs` and
 * `react-hooks/immutability` satisfied.
 *
 * Motion policy:
 * - `prefers-reduced-motion: reduce`: no split and no animation. The statement
 *   stays at its natural, fully-opaque resting state.
 * - Default: `SplitText` splits the statement into words, then a scrubbed
 *   `ScrollTrigger` raises each word from 15% to full opacity in sequence.
 *
 * Resilience: there is no initial-hidden state. If JavaScript, GSAP, or
 * `SplitText` never run, the statement renders at full opacity from first
 * paint. `ScrollTrigger` runs in `scrub` mode only — no `pin`, and nothing
 * here intercepts native wheel or touch scrolling.
 */
export function useTaglineReveal(containerRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Respect the user's motion preference — no split, no animation.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let split: SplitText | null = null;

    const ctx = gsap.context(() => {
      const tagline = container.querySelector<HTMLElement>("[data-tagline]");
      const decos = gsap.utils.toArray<HTMLElement>("[data-tagline-deco]", container);

      if (tagline) {
        split = new SplitText(tagline, { type: "words" });

        gsap.fromTo(
          split.words,
          { opacity: 0.15 },
          {
            opacity: 1,
            stagger: 0.08,
            ease: "none",
            scrollTrigger: {
              trigger: container,
              start: "top 75%",
              end: "bottom 60%",
              scrub: true,
            },
          }
        );
      }

      // Ambient decorative bloom brightens across the same scroll range.
      if (decos.length) {
        gsap.fromTo(
          decos,
          { opacity: 0.35 },
          {
            opacity: 0.7,
            ease: "none",
            scrollTrigger: {
              trigger: container,
              start: "top 75%",
              end: "bottom 60%",
              scrub: true,
            },
          }
        );
      }
    }, container);

    return () => {
      split?.revert();
      ctx.revert();
    };
  }, [containerRef]);
}
