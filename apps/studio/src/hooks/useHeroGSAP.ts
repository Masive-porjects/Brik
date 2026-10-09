"use client";

import { useEffect, type RefObject } from "react";
import gsap from "gsap";
import { SplitText } from "gsap/SplitText";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Observer } from "gsap/Observer";

gsap.registerPlugin(SplitText, ScrollTrigger, Observer);

/**
 * Elite hero animation controller.
 *
 * Ownership: the caller owns ONE `containerRef` on the hero <section>. This
 * hook never returns refs and never reads or writes a ref during render — every
 * animated element is discovered through `data-hero-*` hooks inside the effect,
 * which keeps `react-hooks/refs` / `react-hooks/immutability` satisfied.
 *
 * Motion policy:
 * - Shared (desktop and touch): staggered text reveal + card/orb entrance.
 * - `(hover: hover) and (pointer: fine)`: cursor parallax, 3D tilt, glow pulse
 *   and a subtle ScrollTrigger parallax on the monitor card.
 * - `(hover: none), (pointer: coarse)`: scroll-only ambient drift, zero
 *   pointer-driven motion.
 * - `prefers-reduced-motion: reduce`: no motion at all.
 *
 * Nothing here hijacks or blocks native scroll; ScrollTrigger runs in `scrub`
 * mode only.
 */
export function useHeroGSAP(containerRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Respect the user's motion preference — no animation at all.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let titleSplit: SplitText | null = null;
    let subtitleSplit: SplitText | null = null;
    let media: ReturnType<typeof gsap.matchMedia> | null = null;

    const ctx = gsap.context(() => {
      const eyebrow = container.querySelector<HTMLElement>("[data-hero-eyebrow]");
      const title = container.querySelector<HTMLElement>("[data-hero-title]");
      const subtitle = container.querySelector<HTMLElement>("[data-hero-subtitle]");
      const ctas = gsap.utils.toArray<HTMLElement>("[data-hero-cta]", container);
      const layers = gsap.utils.toArray<HTMLElement>("[data-hero-bg]", container);
      const card = container.querySelector<HTMLElement>("[data-hero-card]");
      const cardWrap = container.querySelector<HTMLElement>("[data-hero-card-wrap]");
      const orb = container.querySelector<HTMLElement>("[data-hero-orb]");
      const glow = container.querySelector<HTMLElement>("[data-hero-glow]");

      // ---------- 1. STAGGERED TEXT + ENTRY REVEAL (all devices) ----------
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

      if (eyebrow) {
        tl.from(eyebrow, { y: 20, opacity: 0, duration: 0.6 }, 0);
      }
      if (title) {
        titleSplit = new SplitText(title, {
          type: "words,chars",
          mask: "chars",
          reduceWhiteSpace: false,
        });
        tl.from(
          titleSplit.chars,
          { y: 30, opacity: 0, duration: 0.5, stagger: 0.025, clearProps: "all" },
          "-=0.3"
        );
      }
      if (subtitle) {
        subtitleSplit = new SplitText(subtitle, { type: "words", mask: "words" });
        tl.from(
          subtitleSplit.words,
          { y: 20, opacity: 0, duration: 0.5, stagger: 0.03, clearProps: "all" },
          "-=0.35"
        );
      }
      if (ctas.length) {
        tl.from(ctas, { y: 24, opacity: 0, duration: 0.6, stagger: 0.08 }, "-=0.3");
      }

      if (card) {
        gsap.fromTo(
          card,
          { opacity: 0, scale: 0.92, y: 40, rotateX: -6 },
          { opacity: 1, scale: 1, y: 0, rotateX: 0, duration: 1.1, ease: "expo.out", delay: 0.4 }
        );
      }
      if (orb) {
        gsap.fromTo(
          orb,
          { opacity: 0, scale: 0.85 },
          { opacity: 1, scale: 1, duration: 0.9, ease: "elastic.out(1, 0.5)", delay: 0.7 }
        );
      }

      // ---------- 2. INPUT-AWARE BRANCHES ----------
      media = gsap.matchMedia();

      // Desktop with a precise pointer: full interactivity.
      media.add("(hover: hover) and (pointer: fine)", () => {
        const observers: Observer[] = [];

        // Cursor parallax on the ambient background layers.
        if (layers.length) {
          observers.push(
            Observer.create({
              target: container,
              type: "pointer",
              onMove: (self) => {
                const e = self.event as PointerEvent;
                const rect = container.getBoundingClientRect();
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                const dx = (e.clientX - cx) / cx;
                const dy = (e.clientY - cy) / cy;

                layers.forEach((el, i) => {
                  const depth = [0.06, 0.12, 0.2][i] ?? 0.1;
                  gsap.to(el, {
                    x: dx * depth * 100,
                    y: dy * depth * 100,
                    rotation: i === 1 ? dx * depth * 2 : 0,
                    duration: 0.7,
                    ease: "power2.out",
                    overwrite: "auto",
                  });
                });
              },
              onHoverEnd: () =>
                layers.forEach((el) =>
                  gsap.to(el, {
                    x: 0,
                    y: 0,
                    rotation: 0,
                    duration: 1.2,
                    ease: "elastic.out(1, 0.4)",
                  })
                ),
            })
          );
        }

        // 3D tilt on the monitor card.
        if (card) {
          observers.push(
            Observer.create({
              target: card,
              type: "pointer",
              onMove: (self) => {
                const e = self.event as PointerEvent;
                const rect = card.getBoundingClientRect();
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                const tiltX = ((e.clientY - cy) / (rect.height / 2)) * -6;
                const tiltY = ((e.clientX - cx) / (rect.width / 2)) * 6;
                gsap.to(card, {
                  rotateX: tiltX,
                  rotateY: tiltY,
                  transformPerspective: 1000,
                  duration: 0.35,
                  ease: "power2.out",
                  overwrite: "auto",
                });
              },
              onHoverEnd: () =>
                gsap.to(card, {
                  rotateX: 0,
                  rotateY: 0,
                  duration: 0.7,
                  ease: "elastic.out(1, 0.3)",
                }),
            })
          );
        }

        // Subtle scroll parallax on the card wrapper (never hijacks scroll).
        if (cardWrap) {
          gsap.to(cardWrap, {
            y: 64,
            ease: "none",
            scrollTrigger: {
              trigger: container,
              start: "top top",
              end: "bottom top",
              scrub: true,
            },
          });
        }

        // Reactive glow pulse on hover.
        if (card && glow) {
          const glowTL = gsap
            .timeline({ paused: true, repeat: -1, yoyo: true })
            .to(glow, {
              opacity: 0.5,
              scale: 1.12,
              filter: "blur(70px)",
              duration: 2.2,
              ease: "sine.inOut",
            })
            .to(glow, {
              opacity: 0.15,
              scale: 1,
              filter: "blur(40px)",
              duration: 2.8,
              ease: "sine.inOut",
            });

          const handleEnter = () => glowTL.play();
          const handleLeave = () => {
            glowTL.pause();
            gsap.to(glow, { opacity: 0.1, scale: 1, duration: 1 });
          };

          card.addEventListener("mouseenter", handleEnter);
          card.addEventListener("mouseleave", handleLeave);

          return () => {
            card.removeEventListener("mouseenter", handleEnter);
            card.removeEventListener("mouseleave", handleLeave);
            glowTL.kill();
            observers.forEach((o) => o.kill());
          };
        }

        return () => observers.forEach((o) => o.kill());
      });

      // Touch / coarse pointer: scroll-driven ambient drift only.
      media.add("(hover: none), (pointer: coarse)", () => {
        layers.forEach((el, i) => {
          gsap.to(el, {
            y: [-24, -48, -16][i] ?? -24,
            ease: "none",
            scrollTrigger: {
              trigger: container,
              start: "top top",
              end: "bottom top",
              scrub: true,
            },
          });
        });
      });
    }, container);

    return () => {
      titleSplit?.revert();
      subtitleSplit?.revert();
      media?.revert();
      ctx.revert();
    };
  }, [containerRef]);
}
