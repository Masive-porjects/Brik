/**
 * lib/audioUtils — funciones puras de mapeo de género:
 *  - genreToParams: el backend emite ids con underscore ("hip_hop");
 *    el perfil urbano debe aplicarse igual que con "hip-hop"/"urban".
 *  - genreDisplayLabel: etiqueta legible; "hip_hop" tiene nombre propio
 *    ("Rap / Hip-Hop"), el resto reemplaza "_" por espacio, null/other
 *    se normalizan a "Otro".
 *  - hasCompletedMix: T3 — el estado de mezcla viene del backend
 *    (session.mix_status) y solo "completed" habilita source=mix.
 *  - getMixGate / resolveMixStatus: T4 — el gate NO-bloqueante hacia el
 *    master: bloquea solo con mezcla iniciada y no entregada.
 */
import { describe, it, expect } from "vitest";
import {
  genreDisplayLabel,
  genreToParams,
  getMixGate,
  hasCompletedMix,
  resolveMixStatus,
} from "@/lib/audioUtils";
import type { SessionData } from "@/lib/api";

describe("genreToParams — perfil urbano", () => {
  const urbanProfile = {
    compression_ratio: 4.0,
    limiter_ceiling_db: -1.0,
    transient_boost_db: 2.0,
    haas_delay_ms: 5,
    stereo_width: 1.2,
    target_lufs_db: -12,
  };

  it('hip_hop (id con underscore del backend) aplica el perfil urbano', () => {
    expect(genreToParams("hip_hop")).toMatchObject(urbanProfile);
  });

  it('hip-hop (con guion) aplica el mismo perfil', () => {
    expect(genreToParams("hip-hop")).toMatchObject(urbanProfile);
  });

  it("reggaeton y urban comparten el perfil", () => {
    expect(genreToParams("reggaeton")).toMatchObject(urbanProfile);
    expect(genreToParams("urban")).toMatchObject(urbanProfile);
  });

  it("null devuelve los defaults (sin perfil urbano)", () => {
    const p = genreToParams(null);
    expect(p.compression_ratio).toBe(2.0);
    expect(p.transient_boost_db).toBe(0.0);
    expect(p.stereo_width).toBe(1.0);
  });
});

describe("genreDisplayLabel", () => {
  it('hip_hop → "Rap / Hip-Hop"', () => {
    expect(genreDisplayLabel("hip_hop")).toBe("Rap / Hip-Hop");
  });

  it("reemplaza underscore por espacio en otros géneros", () => {
    expect(genreDisplayLabel("electronica")).toBe("electronica");
    expect(genreDisplayLabel("rock_alternativo")).toBe("rock alternativo");
  });

  it("null y other → Otro", () => {
    expect(genreDisplayLabel(null)).toBe("Otro");
    expect(genreDisplayLabel("other")).toBe("Otro");
  });
});

describe("hasCompletedMix", () => {
  /** Sesión mínima: solo el campo que decide el estado de mezcla. */
  const session = (mixStatus?: SessionData["mix_status"]) =>
    ({ session_id: "s1", mix_status: mixStatus }) as SessionData;

  it("true solo con mix_status completed (mezcla entregada)", () => {
    expect(hasCompletedMix(session("completed"))).toBe(true);
  });

  it("false con processing / failed / none", () => {
    expect(hasCompletedMix(session("processing"))).toBe(false);
    expect(hasCompletedMix(session("failed"))).toBe(false);
    expect(hasCompletedMix(session("none"))).toBe(false);
  });

  it("false cuando el campo no viene (sesión anterior al contrato T2)", () => {
    expect(hasCompletedMix(session(undefined))).toBe(false);
  });

  it("false sin sesión", () => {
    expect(hasCompletedMix(null)).toBe(false);
    expect(hasCompletedMix(undefined)).toBe(false);
  });
});

describe("resolveMixStatus", () => {
  it("normaliza ausente/null a none (el camino solo-master nunca se bloquea)", () => {
    expect(resolveMixStatus(undefined)).toBe("none");
    expect(resolveMixStatus(null)).toBe("none");
  });

  it("conserva el estado real del backend", () => {
    expect(resolveMixStatus("none")).toBe("none");
    expect(resolveMixStatus("processing")).toBe("processing");
    expect(resolveMixStatus("completed")).toBe("completed");
    expect(resolveMixStatus("failed")).toBe("failed");
  });
});

describe("getMixGate — master NO bloqueado", () => {
  /** Sesión mínima: solo el campo que decide el estado de mezcla. */
  const session = (mixStatus?: SessionData["mix_status"]) =>
    ({ session_id: "s1", mix_status: mixStatus }) as SessionData;

  it('none: el usuario nunca mezcló → master libre (camino solo-master)', () => {
    expect(getMixGate(session("none"))).toEqual({
      mixStatus: "none",
      blocked: false,
    });
  });

  it("completed: mezcla entregada → master libre (y consume source=mix)", () => {
    expect(getMixGate(session("completed"))).toEqual({
      mixStatus: "completed",
      blocked: false,
    });
  });

  it("campo ausente (sesión previa al contrato T2) → master libre", () => {
    expect(getMixGate(session(undefined))).toEqual({
      mixStatus: "none",
      blocked: false,
    });
  });

  it("sin sesión → master libre", () => {
    expect(getMixGate(null)).toEqual({ mixStatus: "none", blocked: false });
    expect(getMixGate(undefined)).toEqual({ mixStatus: "none", blocked: false });
  });
});

describe("getMixGate — master BLOQUEADO", () => {
  const session = (mixStatus: SessionData["mix_status"]) =>
    ({ session_id: "s1", mix_status: mixStatus }) as SessionData;

  it("processing: mezcla en curso → bloqueado", () => {
    expect(getMixGate(session("processing"))).toEqual({
      mixStatus: "processing",
      blocked: true,
    });
  });

  it("failed: mezcla iniciada y no entregada → bloqueado (reintentable)", () => {
    expect(getMixGate(session("failed"))).toEqual({
      mixStatus: "failed",
      blocked: true,
    });
  });

  it("el bloqueo nunca se confunde con una mezcla entregada", () => {
    // El backend rechaza source=mix con 400 en processing/failed: el gate
    // tiene que ser estrictamente disyunto de hasCompletedMix.
    for (const status of ["processing", "failed"] as const) {
      const gate = getMixGate(session(status));
      expect(gate.blocked).toBe(true);
      expect(hasCompletedMix(session(status))).toBe(false);
    }
    expect(getMixGate(session("completed")).blocked).toBe(false);
    expect(hasCompletedMix(session("completed"))).toBe(true);
  });
});