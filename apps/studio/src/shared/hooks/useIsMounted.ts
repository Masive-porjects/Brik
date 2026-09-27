"use client";

import { useState, useEffect } from "react";

/**
 * Returns true only after the component has mounted in the browser DOM.
 * Use this to postpone rendering browser-dependent / client-only UI
 * and prevent Next.js / React Hydration Mismatch errors.
 */
export function useIsMounted(): boolean {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  return isMounted;
}
