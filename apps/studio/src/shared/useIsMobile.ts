"use client";

import { useState, useEffect } from "react";

const MOBILE_BREAKPOINT = 768; // md breakpoint in Tailwind

/**
 * Detects if the viewport is mobile-sized.
 * Uses matchMedia for performance (no resize listener polling).
 * Updates automatically on viewport resize / device rotation.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);

    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(e.matches);
    };

    // Set initial value
    handler(mql);

    // Listen for changes (viewport resize, rotation)
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}
