/**
 * AgentSidebar — widget de chat flotante (pop-up) de Brik en la esquina inferior derecha.
 *
 * Contrato que fija este test:
 * - El fantasma se dibuja siempre y es el control de apertura/cierre del widget.
 * - Tocarlo abre/cierra el panel de chat flotante.
 * - El panel cerrado no monta AgentPanel (no queda contenido vivo fuera de pantalla).
 * - La levitación es un tween de GSAP en el eje Y del icono interno, infinito y con yoyo.
 * - El fantasma permanece anclado fijo abajo a la derecha; su posición base no se mueve.
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
  "productor.status.idle": "inactivo",
  "common.close": "Cerrar",
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

  it("dibuja el fantasma anclado abajo a la derecha, cerrado por defecto", () => {
    render(<AgentSidebar sessionId={null} />);

    const ghost = screen.getByTestId("brik-ghost");
    expect(ghost.getAttribute("aria-expanded")).toBe("false");
    expect(ghost.className).toContain("fixed");
    expect(ghost.className).toContain("bottom-16");
    expect(ghost.className).toContain("right-6");
    expect(ghost.className).toContain("z-50");
    // Nada de `right` dinámico: sólo el span interno levita.
    expect((ghost as HTMLButtonElement).style.right).toBe("");
    expect(screen.queryByTestId("agent-panel")).toBeNull();
  });

  it("el fantasma dispara la apertura y el cierre del widget", () => {
    render(<AgentSidebar sessionId={null} />);

    // Cerrado: no hay panel
    expect(screen.queryByTestId("agent-panel")).toBeNull();

    // Click abre el widget
    fireEvent.click(screen.getByTestId("brik-ghost"));
    expect(screen.getByTestId("agent-panel")).toBeTruthy();

    // El botón X cierra el widget
    fireEvent.click(screen.getByLabelText("Cerrar"));
    expect(screen.queryByTestId("agent-panel")).toBeNull();
  });

  it("el fantasma está anclado fijo y solo el icono interno levita", () => {
    render(<AgentSidebar sessionId={null} />);

    const ghost = screen.getByTestId("brik-ghost") as HTMLButtonElement;
    expect(ghost.className).toContain("fixed");
    expect(ghost.className).toContain("bottom-16");
    expect(ghost.className).toContain("right-6");
    expect(ghost.className).toContain("z-50");
    expect(ghost.style.right).toBe("");
  });

  it("levita en el eje Y, infinito y con yoyo", () => {
    render(<AgentSidebar sessionId={null} />);

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
