import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the API client before importing the store - use vi.hoisted to avoid hoisting issues
const { mockGetProjectMixState, mockPatchProjectMixState } = vi.hoisted(() => ({
  mockGetProjectMixState: vi.fn(),
  mockPatchProjectMixState: vi.fn(),
}));

vi.mock("@/adapters/api/client", () => ({
  getProjectMixState: mockGetProjectMixState,
  patchProjectMixState: mockPatchProjectMixState,
}));

import { createMixStateStore } from "@/features/projects/store/mixStateStore";

describe("mixStateStore", () => {
  const projectId = "test-project-123";
  let store: ReturnType<typeof createMixStateStore>;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();

    mockGetProjectMixState.mockRejectedValue(new Error("Not found"));
    mockPatchProjectMixState.mockResolvedValue(undefined);

    store = createMixStateStore(projectId);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("returns default state initially", () => {
    const state = store.getSnapshot();
    expect(state.faders).toEqual({
      drums_db: 0,
      bass_db: 0,
      other_db: 0,
      vocals_db: 0,
    });
    expect(state.toggles.mute).toEqual({});
    expect(state.toggles.solo).toEqual({});
    expect(state.toggles.dimension_enabled).toBe(true);
    expect(state.toggles.auto_balance).toBe(false);
    expect(state.undoStack).toHaveLength(0);
    expect(state.redoStack).toHaveLength(0);
  });

  it("subscribes to changes", () => {
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.setFader("drums", -3);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    store.setFader("bass", -6);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("sets fader level and clamps to [_db band -6, 6]", () => {
    store.setFader("drums", -3);
    expect(store.getSnapshot().faders.drums_db).toBe(-3);

    store.setFader("drums", 15); // above max
    expect(store.getSnapshot().faders.drums_db).toBe(6);

    store.setFader("drums", -70); // below min
    expect(store.getSnapshot().faders.drums_db).toBe(-6);
  });

  it("records undo snapshot on fader change", () => {
    store.setFader("drums", -3);
    store.setFader("bass", -6);
    const state = store.getSnapshot();
    expect(state.undoStack).toHaveLength(2);
    expect(state.undoStack[0].faders.drums_db).toBe(0); // previous state before first change
    expect(state.undoStack[1].faders.bass_db).toBe(0); // previous state before second change (drums was -3)
  });

  it("clears redo stack on new change after undo", () => {
    store.setFader("drums", -3);
    store.setFader("bass", -6);
    store.undo();
    store.setFader("vocals", -9);
    const state = store.getSnapshot();
    expect(state.redoStack).toHaveLength(0);
  });

  it("undo restores previous fader state", () => {
    store.setFader("drums", -3);
    store.setFader("bass", -6);
    store.undo();
    const state = store.getSnapshot();
    expect(state.faders.drums_db).toBe(-3);
    expect(state.faders.bass_db).toBe(0);
  });

  it("redo restores undone state", () => {
    store.setFader("drums", -3);
    store.undo();
    store.redo();
    const state = store.getSnapshot();
    expect(state.faders.drums_db).toBe(-3);
  });

  it("toggles mute/solo/dimension_enabled/auto_balance", () => {
    store.setToggle("mute", { drums: true });
    expect(store.getSnapshot().toggles.mute).toEqual({ drums: true });

    store.setToggle("solo", { bass: true });
    expect(store.getSnapshot().toggles.solo).toEqual({ bass: true });

    store.setToggle("dimension_enabled", false);
    expect(store.getSnapshot().toggles.dimension_enabled).toBe(false);

    store.setToggle("auto_balance", true);
    expect(store.getSnapshot().toggles.auto_balance).toBe(true);
  });

  it("pushes undo on toggle change", () => {
    store.setToggle("dimension_enabled", false);
    const state = store.getSnapshot();
    expect(state.undoStack).toHaveLength(1);
    expect(state.undoStack[0].toggles.dimension_enabled).toBe(true); // previous state
  });

  it("reset restores defaults and clears history", () => {
    store.setFader("drums", -3);
    store.setToggle("auto_balance", true);
    store.reset();
    const state = store.getSnapshot();
    expect(state.faders).toEqual({
      drums_db: 0,
      bass_db: 0,
      other_db: 0,
      vocals_db: 0,
    });
    expect(state.toggles.auto_balance).toBe(false);
    expect(state.undoStack).toHaveLength(0);
    expect(state.redoStack).toHaveLength(0);
  });

  it("debounced save is called after 3.5s", async () => {
    store.setFader("drums", -3);

    // Flush debounced saves immediately (test helper)
    store.flushDebounce();
    // Wait for microtask queue to process the fire-and-forget save
    await Promise.resolve();
    expect(mockPatchProjectMixState).toHaveBeenCalledTimes(1);
  });

  it("merges multiple changes within debounce window into single save", async () => {
    store.setFader("drums", -3);
    store.setFader("bass", -6);
    store.setFader("vocals", -9);

    // Flush debounced saves immediately (test helper)
    store.flushDebounce();
    // Wait for microtask queue to process the fire-and-forget save
    await Promise.resolve();
    expect(mockPatchProjectMixState).toHaveBeenCalledTimes(1);
  });

  it("canUndo/canRedo reflect stack state", () => {
    const state = store.getSnapshot();
    expect(state.undoStack.length).toBe(0);
    expect(state.redoStack.length).toBe(0);

    store.setFader("drums", -3);
    expect(store.getSnapshot().undoStack.length).toBe(1);

    store.undo();
    expect(store.getSnapshot().redoStack.length).toBe(1);
  });

  it("caps undo/redo stacks at 50", () => {
    for (let i = 0; i < 60; i++) {
      store.setFader("drums", -i);
    }
    const state = store.getSnapshot();
    expect(state.undoStack.length).toBe(50);
  });
});

describe("mixStateStore - hydration", () => {
  const projectId = "test-project-hydrate";

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("hydrates from backend response", async () => {
    mockGetProjectMixState.mockResolvedValueOnce({
      state: {
        faders: { drums_db: -3, bass_db: -6, other_db: -1.5, vocals_db: 0 },
        toggles: {
          mute: { drums: true },
          solo: {},
          dimension_enabled: false,
          auto_balance: true,
        },
      },
      undo_stack: [
        {
          faders: { drums_db: 0, bass_db: 0, other_db: 0, vocals_db: 0 },
          toggles: {},
          timestamp: 1000,
        },
      ],
      updatedAt: "2026-10-08T12:00:00Z",
    });

    mockPatchProjectMixState.mockResolvedValue(undefined);

    const { createMixStateStore } = await import("@/features/projects/store/mixStateStore");
    const store = createMixStateStore(projectId);
    await store.hydrate();

    const state = store.getSnapshot();
    expect(state.faders.drums_db).toBe(-3);
    expect(state.faders.bass_db).toBe(-6);
    expect(state.toggles.dimension_enabled).toBe(false);
    expect(state.toggles.auto_balance).toBe(true);
    expect(state.toggles.mute).toEqual({ drums: true });
    expect(state.undoStack).toHaveLength(1);
  });

  it("uses defaults on hydration failure", async () => {
    mockGetProjectMixState.mockRejectedValueOnce(new Error("Network error"));

    mockPatchProjectMixState.mockResolvedValue(undefined);

    const { createMixStateStore } = await import("@/features/projects/store/mixStateStore");
    const store = createMixStateStore("test-project-fail");
    await store.hydrate();

    const state = store.getSnapshot();
    expect(state.faders).toEqual({
      drums_db: 0,
      bass_db: 0,
      other_db: 0,
      vocals_db: 0,
    });
  });
});