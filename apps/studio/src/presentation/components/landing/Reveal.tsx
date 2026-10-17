"use client";

import { useEffect, useRef } from "react";

/**
 * Reveal — viewport-triggered, blur-fade-up entrance.
 *
 * The base `.animate-blur-fade-up` recipe is time-based (it fires on mount),
 * so applying it directly to below-the-fold sections finishes the animation
 * before the user ever scrolls to them. This wrapper instead hides the
 * element via the `data-reveal` attribute and adds the animation class
 * through an IntersectionObserver only once the element enters the viewport
 * (fire once).
 *
 * The browser DOM is an external system, so the effect synchronizes it
 * directly rather than driving it through React state.
 *
 * Accessibility / resilience:
 * • `prefers-reduced-motion: reduce` → never observed and never animated; the
 *   hidden state is lifted immediately, and the reduced-motion CSS guard
 *   forces `[data-reveal]` visible from first paint so content is never stuck
 *   hidden before hydration runs.
 * • No `IntersectionObserver` → fail open by lifting the hidden state.
 */
type RevealTag = "div" | "section";

interface RevealProps extends React.HTMLAttributes<HTMLElement> {
  children: React.ReactNode;
  /** Element to render. Defaults to `div`. */
  as?: RevealTag;
  /** Fraction of the element that must be visible to trigger. Defaults to 0.15. */
  amount?: number;
}

export default function Reveal({
  children,
  className,
  as = "div",
  amount = 0.15,
  id,
  ...rest
}: RevealProps) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const prefersReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    // Fail open: never leave content invisible.
    if (prefersReduced || typeof IntersectionObserver === "undefined") {
      el.removeAttribute("data-reveal");
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            el.classList.add("animate-blur-fade-up");
            el.removeAttribute("data-reveal");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: amount },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [amount]);

  const Tag = as as React.ElementType;

  return (
    <Tag ref={ref} id={id} data-reveal="" className={className} {...rest}>
      {children}
    </Tag>
  );
}
