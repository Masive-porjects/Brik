"use client";

import { useGSAP } from "@gsap/react";
import { useRef } from "react";
import gsap from "gsap";
import { SplitText } from "gsap/SplitText";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Observer } from "gsap/Observer";

gsap.registerPlugin(SplitText, ScrollTrigger, Observer);

export function useHeroGSAP() {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const ctaPrimaryRef = useRef<HTMLAnchorElement>(null);
  const ctaGhostRef = useRef<HTMLAnchorElement>(null);
  const bgLayersRef = useRef<(HTMLDivElement | null)[]>([null, null, null]);
  const monitorRef = useRef<HTMLDivElement>(null);
  const orbRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const eyebrowRef = useRef<HTMLSpanElement>(null);

  useGSAP(() => {
    const ctx = gsap.context(() => {
      // ---------- 1. SPLIT TEXT REVEAL (GSAP-style) ----------
      const titleSplit = new SplitText(titleRef.current!, { type: "chars", mask: "chars" });
      const subtitleSplit = new SplitText(subtitleRef.current!, { type: "words", mask: "words" });

      const masterTL = gsap.timeline({ defaults: { ease: "power3.out" } });

      masterTL
        // Eyebrow
        .from(eyebrowRef.current!, {
          y: 20,
          opacity: 0,
          duration: 0.6,
          ease: "power3.out",
        })
        // Title chars - stagger 0.025, y: 30
        .from(titleSplit.chars, {
          y: 30,
          opacity: 0,
          duration: 0.5,
          stagger: 0.025,
          ease: "power3.out",
          clearProps: "all",
        }, "-=0.3")
        // Subtitle words
        .from(subtitleSplit.words, {
          y: 20,
          opacity: 0,
          duration: 0.5,
          stagger: 0.03,
          ease: "power3.out",
          clearProps: "all",
        }, "-=0.35")
        // CTAs
        .from([ctaPrimaryRef.current!, ctaGhostRef.current!], {
          y: 24,
          opacity: 0,
          duration: 0.6,
          stagger: 0.08,
          ease: "power3.out",
        }, "-=0.3");

      // Cleanup function for SplitText
      const cleanup = () => {
        titleSplit.revert();
        subtitleSplit.revert();
      };

      // ---------- 2. PARALLAX MOUSE ----------
      const container = titleRef.current!.closest("section") as HTMLElement;
      const layers = bgLayersRef.current.filter(Boolean) as HTMLDivElement[];

      Observer.create({
        target: container,
        type: "pointer",
        onMove: (self: { event: Event }) => {
          const e = self.event as PointerEvent;
          const { clientX: x, clientY: y } = e;
          const rect = container.getBoundingClientRect();
          const cx = rect.left + rect.width / 2;
          const cy = rect.top + rect.height / 2;
          const dx = (x - cx) / cx;
          const dy = (y - cy) / cy;

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
        onLeave: () => layers.forEach(el => gsap.to(el, { x: 0, y: 0, rotation: 0, duration: 1.2, ease: "elastic.out(1, 0.4)" })),
      } as any);

      // ---------- 3. MONITOR CARD: ENTRADA + 3D TILT + GLOW ----------
      if (monitorRef.current) {
        const card = monitorRef.current;
        const orb = orbRef.current!;
        const glow = glowRef.current!;

        // Entrada
        gsap.fromTo(card, 
          { opacity: 0, scale: 0.92, y: 40, rotateX: -6 },
          { opacity: 1, scale: 1, y: 0, rotateX: 0, duration: 1.1, ease: "expo.out", delay: 0.4 }
        );
        gsap.fromTo(orb, 
          { opacity: 0, scale: 0.85 },
          { opacity: 1, scale: 1, duration: 0.9, ease: "elastic.out(1, 0.5)", delay: 0.7 }
        );

        // 3D Tilt (desktop only - no touch)
        if (!("ontouchstart" in window)) {
          Observer.create({
            target: card,
            type: "pointer",
            onMove: (self: { event: Event }) => {
              const e = self.event as PointerEvent;
              const rect = card.getBoundingClientRect();
              const cx = rect.left + rect.width / 2;
              const cy = rect.top + rect.height / 2;
              const tiltX = (e.clientY - cy) / (rect.height / 2) * -6;
              const tiltY = (e.clientX - cx) / (rect.width / 2) * 6;
              gsap.to(card, { rotateX: tiltX, rotateY: tiltY, transformPerspective: 1000, duration: 0.35, ease: "power2.out", overwrite: "auto" });
            },
            onLeave: () => gsap.to(card, { rotateX: 0, rotateY: 0, duration: 0.7, ease: "elastic.out(1, 0.3)" }),
          } as any);
        }

        // Glow pulsante reactivo al hover
        const glowTL = gsap.timeline({ paused: true, repeat: -1, yoyo: true })
          .to(glow, { opacity: 0.5, scale: 1.12, filter: "blur(70px)", duration: 2.2, ease: "sine.inOut" })
          .to(glow, { opacity: 0.15, scale: 1, filter: "blur(40px)", duration: 2.8, ease: "sine.inOut" });

        const handleEnter = () => glowTL.play();
        const handleLeave = () => { glowTL.pause(); gsap.to(glow, { opacity: 0.1, scale: 1, duration: 1 }); };

        card.addEventListener("mouseenter", handleEnter);
        card.addEventListener("mouseleave", handleLeave);

        return () => {
          cleanup();
          card.removeEventListener("mouseenter", handleEnter);
          card.removeEventListener("mouseleave", handleLeave);
          glowTL.kill();
        };
      }

      return cleanup;
    }, titleRef);

    return () => ctx.revert();
  }, []);

  return { 
    titleRef, 
    subtitleRef, 
    ctaPrimaryRef, 
    ctaGhostRef, 
    bgLayersRef, 
    monitorRef, 
    orbRef, 
    glowRef,
    eyebrowRef,
  };
}