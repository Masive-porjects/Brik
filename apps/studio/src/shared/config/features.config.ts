import type { MasteringTab } from "@/presentation/components/dock/types";

export type FeatureKey =
  | MasteringTab
  | "history"
  | "chat"
  | "delivery"
  | "report";

export interface FeatureDefinition {
  id: FeatureKey;
  enabled: boolean;
  labelKey: string;
  defaultLabel: string;
  requiresAuth?: boolean;
  badge?: string;
  descriptionKey?: string;
}

/**
 * Registro central de funcionalidades de WaveAI.
 * Permite apagar, encender o añadir módulos de forma desacoplada
 * sin alterar la lógica interna de los componentes.
 */
export const DEFAULT_FEATURES: Record<FeatureKey, FeatureDefinition> = {
  mezcla: {
    id: "mezcla",
    enabled: true,
    labelKey: "nav.mezcla",
    defaultLabel: "Mezcla de Audio",
  },
  modules: {
    id: "modules",
    enabled: true,
    labelKey: "nav.modules",
    defaultLabel: "Masterizar Audio",
  },
  splitter: {
    id: "splitter",
    enabled: true,
    labelKey: "nav.splitter",
    defaultLabel: "Splitter",
  },
  vocal: {
    id: "vocal",
    enabled: true,
    labelKey: "nav.vocal",
    defaultLabel: "Vocal",
  },
  songstarter: {
    id: "songstarter",
    enabled: true,
    labelKey: "nav.songstarter",
    defaultLabel: "Beats",
  },
  genres: {
    id: "genres",
    enabled: true,
    labelKey: "nav.genres",
    defaultLabel: "Guía de Géneros",
  },
  pipeline: {
    id: "pipeline",
    enabled: true,
    labelKey: "nav.pipeline",
    defaultLabel: "Cadena de Master",
  },
  analysis: {
    id: "analysis",
    enabled: true,
    labelKey: "nav.analysis",
    defaultLabel: "Análisis",
  },
  stereo: {
    id: "stereo",
    enabled: true,
    labelKey: "nav.stereo",
    defaultLabel: "Estéreo",
  },
  live: {
    id: "live",
    enabled: true,
    labelKey: "nav.live",
    defaultLabel: "Live Engine",
  },
  album: {
    id: "album",
    enabled: true,
    labelKey: "nav.album",
    defaultLabel: "Álbum",
  },
  history: {
    id: "history",
    enabled: true,
    labelKey: "nav.history",
    defaultLabel: "Historial",
    requiresAuth: true,
    badge: "Nuevo",
  },
  chat: {
    id: "chat",
    enabled: true,
    labelKey: "nav.chat",
    defaultLabel: "Asistente IA",
  },
  delivery: {
    id: "delivery",
    enabled: true,
    labelKey: "nav.delivery",
    defaultLabel: "Entrega",
  },
  report: {
    id: "report",
    enabled: true,
    labelKey: "nav.report",
    defaultLabel: "Reporte de Cumplimiento",
  },
};
