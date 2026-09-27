"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import gsap from "gsap";
import { motion, useReducedMotion } from "framer-motion";
import DockItem from "./DockItem";
import { LufsTile, MotorTile, ProgressTile } from "./DockTelemetryTile";
import { DOCK_MODULES, type DockModuleDef, type MasteringTab } from "./types";
import { useTranslation } from "@/i18n/useTranslation";
import { useFeatures } from "@/shared/hooks/useFeatures";

/* ── Onboarding micro ───────────────────────────────────
   The first time the dock mounts in a session, every label
   reveals for ~2.2s so a new user learns what each module does
   without a tutorial. sessionStorage = once per session, cheap. */
const ONBOARD_KEY = "brikmaster-dock-labels-v1";
const ONBOARD_MS = 2200;

interface ModuleDockProps {
  activeTab: MasteringTab | null;
  onSelect: (tab: MasteringTab) => void;
  /** 0 when idle; live % while processing. */
  processingProgress: number;
  /** Integrated LUFS of the master result (fallback analysis), null if unknown. */
  lufs: number | null;
}

/* ── Fisheye tuning ─────────────────────────────────────
   Gaussian falloff around the cursor: hovered ≈ 1.5×,
   immediate neighbours ≈ 1.25×, smooth decay back to 1×
   about two items away. */
const FISHEYE_AMPLITUDE = 0.5;
const FISHEYE_SIGMA_PX = 52;
const LIFT_PX = 12;

function scaleForDistance(distancePx: number): number {
  return (
    1 +
    FISHEYE_AMPLITUDE *
      Math.exp(
        -(distancePx * distancePx) /
          (2 * FISHEYE_SIGMA_PX * FISHEYE_SIGMA_PX),
      )
  );
}

/* ── Floating ModuleDock ────────────────────────────────
   THE module navigator of the mastering view. Fixed bottom-center,
   skeuomorphic pedestals, telemetry tiles in the middle and a
   pointer-proximity fisheye driven by gsap.quickTo writes only —
   zero React state on pointermove. */
export default function ModuleDock({
  activeTab,
  onSelect,
  processingProgress,
  lufs,
}: ModuleDockProps) {
  const dockRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const scalersRef = useRef<
    { scale: (value: number) => void; y: (value: number) => void }[]
  >([]);
  const centersRef = useRef<number[]>([]);
  const frameRef = useRef(0);

  const reduceMotion = useReducedMotion();

  /* Onboarding reveal — once per session (sessionStorage). Skips when
     reduced motion is preferred: the labels never animate. The state
     write happens in async timeouts (not sync in the effect body). */
  const [revealLabels, setRevealLabels] = useState<boolean>(false);

  useEffect(() => {
    if (reduceMotion || typeof window === "undefined") return;
    let seen = false;
    try {
      seen = sessionStorage.getItem(ONBOARD_KEY) === "1";
    } catch {
      // Private mode — replay the micro-tour each session.
    }
    if (seen) return;

    const showTimer = setTimeout(() => setRevealLabels(true), 80);
    const hideTimer = setTimeout(() => {
      setRevealLabels(false);
      try {
        sessionStorage.setItem(ONBOARD_KEY, "1");
      } catch {
        // Private mode — fine, this session already saw it.
      }
    }, 80 + ONBOARD_MS);
    return () => {
      clearTimeout(showTimer);
      clearTimeout(hideTimer);
    };
  }, [reduceMotion]);

  /* Fisheye only for fine pointers without reduced-motion preference.
     Lazy initializer keeps SSR markup identical (listeners attach in the
     effect below), so there is no hydration mismatch. Touch devices skip
     hover semantics entirely — taps activate directly. */
  const [fisheyeEnabled] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(pointer: fine)").matches &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const dock = dockRef.current;
    if (!fisheyeEnabled || reduceMotion || !dock) return;

    const items = itemRefs.current.filter(
      (el): el is HTMLButtonElement => el !== null,
    );
    // quickTo needs split properties: the "scale" shorthand is rejected by
    // GSAP here ("not eligible for reset"), so drive scaleX/scaleY instead.
    scalersRef.current = items.map((el) => {
      const scaleX = gsap.quickTo(el, "scaleX", {
        duration: 0.38,
        ease: "power3.out",
      });
      const scaleY = gsap.quickTo(el, "scaleY", {
        duration: 0.38,
        ease: "power3.out",
      });
      const y = gsap.quickTo(el, "y", { duration: 0.38, ease: "power3.out" });
      return {
        scale: (value: number): void => {
          scaleX(value);
          scaleY(value);
        },
        y,
      };
    });

    const resetAll = (): void => {
      if (frameRef.current) {
        cancelAnimationFrame(frameRef.current);
        frameRef.current = 0;
      }
      for (const scaler of scalersRef.current) {
        scaler.scale(1);
        scaler.y(0);
      }
    };

    // The dock is fixed — centers are stable between enter/leave cycles.
    const measureCenters = (): void => {
      centersRef.current = items.map((el) => {
        const rect = el.getBoundingClientRect();
        return rect.left + rect.width / 2;
      });
    };

    const applyMagnification = (clientX: number): void => {
      centersRef.current.forEach((center, i) => {
        const scaler = scalersRef.current[i];
        if (!scaler) return;
        const scale = scaleForDistance(Math.abs(clientX - center));
        scaler.scale(scale);
        scaler.y(-(scale - 1) * LIFT_PX);
      });
    };

    const onPointerEnter = (): void => {
      measureCenters();
    };

    const onPointerMove = (event: PointerEvent): void => {
      if (frameRef.current) return; // rAF throttle — one write per frame
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = 0;
        applyMagnification(event.clientX);
      });
    };

    dock.addEventListener("pointerenter", onPointerEnter);
    dock.addEventListener("pointermove", onPointerMove);
    dock.addEventListener("pointerleave", resetAll);
    return () => {
      dock.removeEventListener("pointerenter", onPointerEnter);
      dock.removeEventListener("pointermove", onPointerMove);
      dock.removeEventListener("pointerleave", resetAll);
      resetAll();
      gsap.killTweensOf(items);
      scalersRef.current = [];
    };
  }, [fisheyeEnabled, reduceMotion]);

  const { t } = useTranslation();
  const { filterDockModules } = useFeatures();

  const enabledModules = useMemo(
    () => filterDockModules(DOCK_MODULES),
    [filterDockModules],
  );

  const splitIndex = Math.min(3, Math.ceil(enabledModules.length / 2));
  const leftModules = enabledModules.slice(0, splitIndex);
  const rightModules = enabledModules.slice(splitIndex);

  const renderItem = useCallback(
    (mod: DockModuleDef, index: number) => (
      <DockItem
        key={mod.key}
        icon={mod.icon}
        label={t(`nav.${mod.key}`, mod.label)}
        testId={`dock-tab-${mod.key}`}
        active={activeTab === mod.key}
        revealLabels={revealLabels}
        onSelect={() => onSelect(mod.key)}
        buttonRef={(el) => {
          itemRefs.current[index] = el;
        }}
      />
    ),
    [activeTab, revealLabels, onSelect, t],
  );

  return (
    <nav
      aria-label="Módulos del estudio"
      className="pointer-events-none fixed inset-x-0 bottom-4 pb-safe z-40 flex justify-center"
    >
      <motion.div
        ref={dockRef}
        initial={reduceMotion ? false : { opacity: 0, y: 28 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, delay: 0.15, ease: "easeOut" }}
        className="glass-elevated pointer-events-auto flex items-center gap-2 rounded-2xl px-3 py-2"
        style={{
          border: "1px solid var(--border-strong)",
          boxShadow: "var(--shadow-heavy)",
        }}
      >
        <div className="flex items-end gap-2">
          {leftModules.map((mod, i) => renderItem(mod, i))}
        </div>
        <div className="mx-1 flex items-center gap-1.5">
          <ProgressTile progress={processingProgress} />
          <LufsTile lufs={lufs} />
          <MotorTile />
        </div>
        <div className="flex items-end gap-2">
          {rightModules.map((mod, i) => renderItem(mod, i + leftModules.length))}
        </div>
      </motion.div>
    </nav>
  );
}
