import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { useIsMobile } from "./useIsMobile";

type ChangeListener = (event: MediaQueryListEvent) => void;

/**
 * jsdom does not implement matchMedia. This stub records the listeners so a
 * test can fire a viewport change the same way a real browser would.
 */
function stubMatchMedia(matches: boolean) {
  const listeners = new Set<ChangeListener>();

  const mql = {
    matches,
    media: "",
    onchange: null,
    addEventListener: (_type: string, listener: ChangeListener) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: ChangeListener) => {
      listeners.delete(listener);
    },
    addListener: (listener: ChangeListener) => {
      listeners.add(listener);
    },
    removeListener: (listener: ChangeListener) => {
      listeners.delete(listener);
    },
    dispatchEvent: () => false,
  };

  const matchMedia = vi.fn().mockReturnValue(mql);
  window.matchMedia = matchMedia as unknown as typeof window.matchMedia;

  return { matchMedia, listeners, mql };
}

beforeEach(() => {
  stubMatchMedia(false);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useIsMobile", () => {
  /**
   * The regression this pins: the hook used to start at `false`, so the first
   * client paint on a phone rendered the desktop branch (a 614px dock on a
   * 390px screen) before the media query was measured.
   */
  it("renders as null on the server instead of guessing desktop", () => {
    function Probe() {
      return <span>{String(useIsMobile())}</span>;
    }

    expect(renderToString(<Probe />)).toContain("null");
  });

  it("queries the Tailwind md breakpoint", () => {
    const { matchMedia } = stubMatchMedia(false);
    renderHook(() => useIsMobile());

    expect(matchMedia).toHaveBeenCalledWith("(max-width: 767px)");
  });

  it("reports true below the md breakpoint", () => {
    stubMatchMedia(true);
    const { result } = renderHook(() => useIsMobile());

    expect(result.current).toBe(true);
  });

  it("reports false at or above the md breakpoint", () => {
    stubMatchMedia(false);
    const { result } = renderHook(() => useIsMobile());

    expect(result.current).toBe(false);
  });

  it("follows viewport changes after mount", () => {
    const { listeners } = stubMatchMedia(true);
    const { result } = renderHook(() => useIsMobile());

    expect(result.current).toBe(true);

    act(() => {
      for (const listener of listeners) {
        listener({ matches: false } as MediaQueryListEvent);
      }
    });

    expect(result.current).toBe(false);
  });
});
