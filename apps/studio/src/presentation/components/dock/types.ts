import {
  Activity,
  Drum,
  LayoutGrid,
  Music,
  Music2,
  Radio,
  Scissors,
  type LucideIcon,
} from "lucide-react";

/** Tabs paintable onto the mastering canvas (shared by page + dock). */
export type MasteringTab =
  | "modules"
  | "mezcla"
  | "splitter"
  | "songstarter"
  | "analysis"
  | "stereo"
  | "album";

export interface DockModuleDef {
  key: MasteringTab;
  label: string;
  icon: LucideIcon;
}

/**
 * The dock IS the module navigator: one item per module, exact labels/icons
 * inherited from the old Módulos dropdown. Order defines the two groups
 * separated by the telemetry tiles in the dock center.
 */
export const DOCK_MODULES: readonly DockModuleDef[] = [
  { key: "mezcla", label: "Mezcla de Audio", icon: Music2 },
  { key: "modules", label: "Masterizar Audio", icon: LayoutGrid },
  { key: "splitter", label: "Splitter", icon: Scissors },
  { key: "songstarter", label: "Beats", icon: Drum },
  { key: "analysis", label: "Análisis", icon: Activity },
  { key: "stereo", label: "Estéreo", icon: Radio },
  { key: "album", label: "Álbum", icon: Music },
];
