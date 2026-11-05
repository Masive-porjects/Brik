"use client";

import { useState, useEffect } from "react";

const MOBILE_BREAKPOINT = 768; // md breakpoint in Tailwind

/**
 * Detects if the viewport is mobile-sized.
 * Uses matchMedia for performance (no resize listener polling).
 * Updates automatically on viewport resize / device rotation.
 *
 * Returns `null` until the media query has been measured on the client.
 * Guessing `false` first painted the DESKTOP branch on phones for one frame —
 * a 614px dock on a 390px screen — so callers must treat `null` as "not
 * measured yet" and render a neutral placeholder.
 */
export function useIsMobile(): boolean | null {
  const [isMobile, setIsMobile] = useState<boolean | null>(null);

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
