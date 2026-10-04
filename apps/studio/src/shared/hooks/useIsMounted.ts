"use client";

import { useSyncExternalStore } from "react";

// No external store to watch: we only need React to distinguish the server/SSR pass
// (getServerSnapshot) from the browser pass (getClientSnapshot) and re-render once
// hydration completes. The empty unsubscribe makes this subscription inert.
const subscribeToNothing = () => () => {};
const hasHydrated = () => true;
const hasNotHydrated = () => false;

/**
 * Returns true only after the component has mounted in the browser DOM.
 * Use this to postpone rendering browser-dependent / client-only UI
 * and prevent Next.js / React Hydration Mismatch errors.
 */
export function useIsMounted(): boolean {
  return useSyncExternalStore(subscribeToNothing, hasHydrated, hasNotHydrated);
}
