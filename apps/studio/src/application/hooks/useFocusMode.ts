"use client";

import { useCallback, useEffect, useState } from "react";

/* ── Focus mode ("Modo foco") ─────────────────────────────
   Switches the studio into a clean, decoration-free state:
   AmbientLayer goes off and glass blur/shine is reduced via the
   html[data-focus="true"] selector in globals.css.

   Persisted in localStorage and propagated through a data attribute
   on <html> + a tiny CustomEvent bus, so any component (AmbientLayer,
   glass surfaces) can react without a shared context provider.

   IMPORTANT: the state updater is kept pure — persisting and notifying
   happen in an effect AFTER commit. Putting applyFocus() inside the
   updater would dispatch the CustomEvent synchronously during the
   render phase and make React throw "Cannot update a component while
   rendering a different component" (AmbientLayer updating during
   UserMenu's render), silently dropping the update. */

const FOCUS_KEY = "brikmaster-focus-mode";
const FOCUS_EVENT = "brikmaster:focus-mode";

function readStored(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(FOCUS_KEY) === "1";
  } catch {
    return false; // Private mode — default off
  }
}

/** Apply the attribute + notify the bus. Export read helper for
 *  components that mount after the first change. */
function applyFocus(on: boolean): void {
  document.documentElement.dataset.focus = on ? "true" : "false";
  window.dispatchEvent(new CustomEvent(FOCUS_EVENT, { detail: { on } }));
}

export function isFocusMode(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.dataset.focus === "true";
}

export function useFocusMode() {
  const [focus, setFocus] = useState<boolean>(readStored);

  /* After every committed change (and once on mount to normalise a
     stale attribute), persist + notify the bus. Pure updaters above,
     side effects live here — post-commit, never during another
     component's render. */
  useEffect(() => {
    try {
      localStorage.setItem(FOCUS_KEY, focus ? "1" : "0");
    } catch {
      // Private mode — still applies for the session
    }
    applyFocus(focus);
  }, [focus]);

  /* Keep in sync across instances via the bus. */
  useEffect(() => {
    const onBus = (e: Event) => {
      setFocus((e as CustomEvent<{ on: boolean }>).detail?.on ?? false);
    };
    window.addEventListener(FOCUS_EVENT, onBus);
    return () => window.removeEventListener(FOCUS_EVENT, onBus);
  }, []);

  const toggle = useCallback(() => {
    setFocus((prev) => !prev);
  }, []);

  return { focus, toggle };
}