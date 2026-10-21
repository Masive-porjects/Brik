/**
 * AgentSidebar — el fantasma levitante es el control del rail de Brik.
 *
 * Contrato que fija este test:
 * - El fantasma se dibuja siempre, expandido o colapsado, y apunta al rail
 *   con `aria-controls`/`aria-expanded`.
 * - Tocarlo y tocar el chevron del header disparan el mismo `onToggle`.
 * - La levitación es un tween de GSAP en el eje Y, infinito y con yoyo.
 * - Colapsado no monta el panel: no queda contenido vivo fuera de pantalla.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  to: vi.fn(() => ({ kill: vi.fn() })),
  set: vi.fn(),
}));

const LABELS: Record<string, string> = {
  "productor.sidebarTitle": "Brik",
  "productor.sidebarCollapse": "Colapsar",
  "productor.sidebarExpand": "Expandir",
};

vi.mock("@/i18n", () => ({
  useTranslation: () => ({
    t: (key: string) => LABELS[key] ?? key,
  }),
}));

vi.mock("./AgentPanel", () => ({
  default: () => <div data-testid="agent-panel" />,
}));

vi.mock("gsap", () => ({
  default: { to: mocks.to, set: mocks.set },
}));

import AgentSidebar from "./AgentSidebar";

describe("AgentSidebar", () => {
  beforeEach(() => {
    mocks.to.mockClear();
    mocks.set.mockClear();
  });

  afterEach(cleanup);

  it("dibuja el fantasma apuntando al rail cuando está colapsado", () => {
    render(
      <AgentSidebar sessionId={null} open={false} onToggle={() => {}} />,
    );

    const ghost = screen.getByTestId("brik-ghost");
    expect(ghost.getAttribute("aria-expanded")).toBe("false");
    expect(ghost.getAttribute("aria-controls")).toBe("brik-rail");
    expect(screen.getByLabelText("Brik").id).toBe("brik-rail");
    expect(screen.queryByTestId("agent-panel")).toBeNull();
  });

  it("el fantasma dispara el toggle", () => {
    const onToggle = vi.fn();
    render(
      <AgentSidebar sessionId={null} open={false} onToggle={onToggle} />,
    );

    fireEvent.click(screen.getByTestId("brik-ghost"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("el chevron del header dispara el mismo toggle y monta el panel", () => {
    const onToggle = vi.fn();
    render(<AgentSidebar sessionId={null} open onToggle={onToggle} />);

    expect(screen.getByTestId("agent-panel")).toBeTruthy();
    expect(screen.getByTestId("brik-ghost").getAttribute("aria-expanded")).toBe(
      "true",
    );

    fireEvent.click(screen.getByTestId("brik-rail-toggle"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("levita en el eje Y, infinito y con yoyo", () => {
    render(<AgentSidebar sessionId={null} open={false} onToggle={() => {}} />);

    expect(mocks.to).toHaveBeenCalledTimes(1);
    const [target, vars] = mocks.to.mock.calls[0] as unknown as [
      HTMLElement,
      Record<string, unknown>,
    ];
    expect(target.tagName).toBe("SPAN");
    expect(vars.yoyo).toBe(true);
    expect(vars.repeat).toBe(-1);
    expect((vars.y as number) < 0).toBe(true);
  });
});
