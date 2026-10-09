"use client";

import { useSyncExternalStore, useState, useCallback } from "react";
import {
  getProjectMixState,
  patchProjectMixState,
} from "@/adapters/api/client";

/** The four stems in a mix. */
export type StemName = "drums" | "bass" | "other" | "vocals";

/**
 * Fader keys as persisted in `project_states.state` — the backend contract
 * uses the `{stem}_db` suffix (spec §4, `api/mix.py` `_STEM_TRIM_KEYS`).
 */
export type FaderKey = `${StemName}_db`;

/** Fader level in dB, clamped to the backend trim band at runtime. */
export type FaderLevel = number;

/** Trim range in dB — mirrors backend `TRIM_STEM_RANGE` (`processing/stem_balance.py`). */
export const FADER_MIN_DB = -6;
export const FADER_MAX_DB = 6;

/**
 * Toggleable mix controls. The `dimension_enabled` / `auto_balance` keys are
 * the persisted contract read by the compiler (`compile_project.py`); the
 * `mute` / `solo` maps are UI-only monitoring state.
 */
export interface MixToggles {
  /** Per-stem mute state (UI-only; not compiled by the backend). */
  mute: Partial<Record<StemName, boolean>>;
  /** Per-stem solo state (UI-only; not compiled by the backend). */
  solo: Partial<Record<StemName, boolean>>;
  /** Spatial dimension stage (tempo delay + reverb). */
  dimension_enabled: boolean;
  /** Auto-balance toward genre target. */
  auto_balance: boolean;
}

/** A single snapshot of the mix state for undo/redo. */
export interface MixSnapshot {
  faders: Record<FaderKey, FaderLevel>;
  toggles: MixToggles;
  timestamp: number;
}

/** Full live mix state shape stored in project_states.state JSONB. */
export interface MixState {
  faders: Record<FaderKey, FaderLevel>;
  toggles: MixToggles;
  undoStack: MixSnapshot[];
  redoStack: MixSnapshot[];
  updatedAt: string | null;
}

/** Default neutral mix state. */
export const DEFAULT_MIX_STATE: MixState = {
  faders: { drums_db: 0, bass_db: 0, other_db: 0, vocals_db: 0 },
  toggles: {
    mute: {},
    solo: {},
    dimension_enabled: true,
    auto_balance: false,
  },
  undoStack: [],
  redoStack: [],
  updatedAt: null,
};

/** Payload sent to backend via PATCH /projects/{id}/state. */
export interface MixStatePayload {
  state: Pick<MixState, "faders" | "toggles">;
  undo_stack: MixSnapshot[];
}

/** Store subscriber type for useSyncExternalStore. */
type Subscriber = () => void;

/** Debounce timer map: projectId -> timer. */
const debounceTimers = new Map<string, ReturnType<typeof setTimeout>>();

/** In-flight request guard to prevent double-sends. */
const inflightRequests = new Set<string>();

/** Creates a store instance for a specific project. */
export function createMixStateStore(projectId: string) {
  let currentState: MixState = { ...DEFAULT_MIX_STATE };
  const subscribers = new Set<Subscriber>();
  let isHydrated = false;
  let saveAbortController: AbortController | null = null;

  /** Notifies all subscribers of a state change. */
  const emitChange = () => {
    subscribers.forEach((cb) => cb());
  };

  /** Loads state from backend. */
  async function hydrate(): Promise<void> {
    if (isHydrated) return;
    try {
      const res = await getProjectMixState(projectId);
      if (res && res.state) {
        currentState = {
          ...DEFAULT_MIX_STATE,
          ...res.state,
          faders: { ...DEFAULT_MIX_STATE.faders, ...res.state.faders },
          toggles: { ...DEFAULT_MIX_STATE.toggles, ...res.state.toggles },
          undoStack: (res.undo_stack as unknown as MixSnapshot[]) ?? [],
          redoStack: [],
          updatedAt: res.updatedAt ?? null,
        };
      }
    } catch (err) {
      console.warn("[mixStateStore] Hydration failed, using defaults:", err);
    } finally {
      isHydrated = true;
      emitChange();
    }
  }

  /** Gets the current state snapshot. */
  const getSnapshot = (): MixState => currentState;

  /** Subscribes to store changes. */
  const subscribe = (callback: Subscriber): (() => void) => {
    subscribers.add(callback);
    return () => subscribers.delete(callback);
  };

  /** Subscribes for server-side rendering (no-op). */
  const subscribeSSR = () => () => {};

/** Debounced save to backend. */
function save(state: MixState) {
  const key = `${projectId}:save`;
  if (inflightRequests.has(key)) return;
  inflightRequests.add(key);

  // Cancel any pending debounce
  const existingTimer = debounceTimers.get(key);
  if (existingTimer) clearTimeout(existingTimer);

  // New debounce timer - use synchronous callback that triggers async save
  const timer = setTimeout(() => {
    debounceTimers.delete(key);
    inflightRequests.delete(key);

    if (saveAbortController) saveAbortController.abort();
    saveAbortController = new AbortController();

    const payload: MixStatePayload = {
      state: { faders: currentState.faders, toggles: currentState.toggles },
      undo_stack: currentState.undoStack,
    };
    // Fire and forget - the async operation runs after timer fires
    const apiPayload = payload as unknown as Parameters<
      typeof patchProjectMixState
    >[1];
    patchProjectMixState(projectId, apiPayload).catch((err) => {
      if ((err as Error).name !== "AbortError") {
        console.error("[mixStateStore] Save failed:", err);
      }
    });
  }, 3500); // 3.5s debounce

  debounceTimers.set(key, timer);
}

/** Flushes all pending debounced saves immediately (for testing). */
function flushDebounce() {
  for (const [key, timer] of debounceTimers.entries()) {
    clearTimeout(timer);
    // Manually execute the timer callback
    debounceTimers.delete(key);
    inflightRequests.delete(key);

    if (saveAbortController) saveAbortController.abort();
    saveAbortController = new AbortController();

    const payload: MixStatePayload = {
      state: { faders: currentState.faders, toggles: currentState.toggles },
      undo_stack: currentState.undoStack,
    };
    const apiPayload = payload as unknown as Parameters<
      typeof patchProjectMixState
    >[1];
    patchProjectMixState(projectId, apiPayload).catch((err) => {
      if ((err as Error).name !== "AbortError") {
        console.error("[mixStateStore] Save failed:", err);
      }
    });
  }
}

  /**
   * Applies a fader (stem trim) change in dB and records it for undo.
   * Clamped to the backend trim band ±6 dB (spec §4, `TRIM_STEM_RANGE`).
   */
  const setFader = (stem: StemName, level: FaderLevel) => {
    const clamped = Math.max(FADER_MIN_DB, Math.min(FADER_MAX_DB, level));
    const key: FaderKey = `${stem}_db`;
    const newFaders = { ...currentState.faders, [key]: clamped };
    applyAndPushUndo(newFaders, currentState.toggles);
  };

  /** Toggles a mute/solo/dimension_enabled/auto_balance flag. */
  const setToggle = <K extends keyof MixToggles>(
    key: K,
    value: MixToggles[K]
  ) => {
    const newToggles = { ...currentState.toggles, [key]: value };
    applyAndPushUndo(currentState.faders, newToggles);
  };

  /** Pushes current snapshot to undo stack, clears redo. */
  const pushUndo = (snapshot: Omit<MixSnapshot, "timestamp">) => {
    const undoEntry: MixSnapshot = {
      ...snapshot,
      timestamp: Date.now(),
    };
    currentState = {
      ...currentState,
      undoStack: [...currentState.undoStack, undoEntry].slice(-50), // cap at 50
      redoStack: [],
    };
  };

  /** Internal: apply a state update and push to undo stack atomically. */
  const applyAndPushUndo = (
    newFaders: Record<FaderKey, FaderLevel>,
    newToggles: MixToggles
  ) => {
    pushUndo({ faders: currentState.faders, toggles: currentState.toggles });
    currentState = { ...currentState, faders: newFaders, toggles: newToggles };
    save(currentState);
    emitChange();
  };

  /** Undo last change. */
  const undo = () => {
    if (currentState.undoStack.length === 0) return;
    const previous = currentState.undoStack[currentState.undoStack.length - 1];
    const current: MixSnapshot = {
      faders: currentState.faders,
      toggles: currentState.toggles,
      timestamp: Date.now(),
    };
    currentState = {
      ...currentState,
      faders: previous.faders,
      toggles: previous.toggles,
      undoStack: currentState.undoStack.slice(0, -1),
      redoStack: [current, ...currentState.redoStack].slice(0, 50),
    };
    save(currentState);
    emitChange();
  };

  /** Redo last undone change. */
  const redo = () => {
    if (currentState.redoStack.length === 0) return;
    const next = currentState.redoStack[0];
    const current: MixSnapshot = {
      faders: currentState.faders,
      toggles: currentState.toggles,
      timestamp: Date.now(),
    };
    currentState = {
      ...currentState,
      faders: next.faders,
      toggles: next.toggles,
      undoStack: [...currentState.undoStack, current].slice(0, 50),
      redoStack: currentState.redoStack.slice(1),
    };
    save(currentState);
    emitChange();
  };

  /** Resets to defaults and clears history. */
  const reset = () => {
    currentState = { ...DEFAULT_MIX_STATE };
    save(currentState);
    emitChange();
  };

  // Trigger hydration on creation
  hydrate();

  return {
    getSnapshot,
    subscribe,
    subscribeSSR,
    getState: () => currentState,
    setFader,
    setToggle,
    undo,
    redo,
    reset,
    hydrate,
    save,
    flushDebounce,
  };
}

/** React hook to use the mix state store for a project. */
export function useMixStateStore(projectId: string) {
  const [store] = useState(() => createMixStateStore(projectId));

  const state = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot
  );

  // Actions
  const setFader = useCallback(
    (stem: StemName, level: FaderLevel) => store.setFader(stem, level),
    [store]
  );
  const setToggle = useCallback(
    <K extends keyof MixToggles>(key: K, value: MixToggles[K]) =>
      store.setToggle(key, value),
    [store]
  );
  const undo = useCallback(() => store.undo(), [store]);
  const redo = useCallback(() => store.redo(), [store]);
  const reset = useCallback(() => store.reset(), [store]);
  const hydrate = useCallback(() => store.hydrate(), [store]);

  return {
    state,
    setFader,
    setToggle,
    undo,
    redo,
    reset,
    hydrate,
    canUndo: state.undoStack.length > 0,
    canRedo: state.redoStack.length > 0,
  };
}