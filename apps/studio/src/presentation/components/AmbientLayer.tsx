"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import FloatingNotes from "@/components/FloatingNotes";
import FloatingGhosts from "@/components/FloatingGhosts";
import { isFocusMode } from "@/application/hooks/useFocusMode";

/* ── AmbientLayer ──────────────────────────────────────────
   Awwwards-style ambient layer for the studio: brand ghosts +
   music notes drift behind the UI, but NEVER compete with it.

   Rules enforced here:
   • Intro (≈1.8s) fades the whole field in after mount.
   • Vignette mask dims the layer near decision zones (center →
     dropzone/player; bottom → dock), keeping the edges airy.
   • Interaction attenuation: any pointerdown on the dock / drag
     over the canvas / play events drops the layer to a whisper
     for ~2.6s, then it breathes back.
   • Focus mode wins: layer goes fully off.
   • prefers-reduced-motion ⇒ near-static (half intensity, no intro).

   Performance: the whole layer is pointer-events-none + aria-hidden;
   opacity changes are CSS transitions (no per-frame React state).
   ─────────────────────────────────────────────────────────── */

const BASE_OPACITY = 0.25; // matches the previous <opacity-25> usage
const INTERACT_OPACITY = 0.03; // whisper
const INTERACT_MS = 2600;

export default function AmbientLayer() {
  const layerRef = useRef<HTMLDivElement>(null);
  /* Two nested wrappers keep intro (1.8s fade) and interaction
     (700ms dim) as independent CSS transitions — clean, no GSAP
     tween fighting React's style prop. */
  const introRef = useRef<HTMLDivElement>(null);
  const [entered, setEntered] = useState(false);
  const [dimmed, setDimmed] = useState(false);
  const [focus, setFocus] = useState<boolean>(isFocusMode);

  /* prefers-reduced-motion via useSyncExternalStore — no setState-in-
     effect, always matches the live media query (SSR snapshot false). */
  const reduced = useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );

  /* Keep the focus state in sync with the FocusMode bus. */
  useEffect(() => {
    const onBus = (e: Event) => {
      setFocus((e as CustomEvent<{ on: boolean }>).detail?.on ?? false);
    };
    window.addEventListener("brikmaster:focus-mode", onBus);
    return () => window.removeEventListener("brikmaster:focus-mode", onBus);
  }, []);

  /* Intro fade-in. */
  useEffect(() => {
    if (reduced) return;
    const t = setTimeout(() => setEntered(true), 120);
    return () => clearTimeout(t);
  }, [reduced]);

  /* Interaction attenuation — passive listener, CSS-transition driven. */
  useEffect(() => {
    if (reduced) return;
    let restoreTimer: ReturnType<typeof setTimeout> | null = null;

    const dim = () => {
      if (isFocusMode()) return; // focus mode wins
      if (restoreTimer) clearTimeout(restoreTimer);
      setDimmed(true);
      restoreTimer = setTimeout(() => setDimmed(false), INTERACT_MS);
    };

    /* Dim when the user works near the decision zones: pointer down on
       the dock, drag over the canvas, any <audio> play event. */
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest('[aria-label="Módulos del estudio"]')) dim();
    };
    const onDragEnter = () => dim();
    const onPlay = (e: Event) => {
      if (e.target instanceof HTMLAudioElement) dim();
    };

    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("play", onPlay, true);
    return () => {
      if (restoreTimer) clearTimeout(restoreTimer);
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("play", onPlay, true);
    };
  }, [reduced]);

  /* Effective opacity: focus wins, then reduced (half), then dimmed. */
  const effectiveOpacity = focus
    ? 0
    : reduced
      ? BASE_OPACITY * 0.5
      : dimmed
        ? INTERACT_OPACITY
        : BASE_OPACITY;

  return (
    <div
      ref={layerRef}
      aria-hidden="true"
      className="ambient-layer pointer-events-none fixed inset-0 z-0"
      data-focus={focus ? "true" : "false"}
    >
      {/* Intro wrapper — long, gentle fade-in once. */}
      <div
        ref={introRef}
        className="absolute inset-0 transition-opacity duration-[1800ms] ease-out"
        style={{ opacity: reduced ? 1 : entered ? 1 : 0 }}
      >
        {/* Vignette mask — dims the layer near decision zones. */}
        <div
          className="absolute inset-0"
          style={{
            maskImage:
              "radial-gradient(ellipse 78% 68% at 50% 42%, transparent 0%, transparent 34%, black 78%, black 100%)",
            WebkitMaskImage:
              "radial-gradient(ellipse 78% 68% at 50% 42%, transparent 0%, transparent 34%, black 78%, black 100%)",
          }}
        >
          {/* Interaction wrapper — fast dim back to base. */}
          <div
            className="absolute inset-0 transition-opacity duration-700 ease-out"
            style={{ opacity: effectiveOpacity }}
          >
            <FloatingNotes zIndex={0} />
            <FloatingGhosts zIndex={0} />
            {/* Extra dim band over the dock (bottom) so pedestals and
                labels always stay readable. */}
            <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-black/70 to-transparent" />
          </div>
        </div>
      </div>
    </div>
  );
}