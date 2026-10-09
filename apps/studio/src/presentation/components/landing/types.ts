export interface DSPStage {
  id: number;
  number: string;
  name: string;
  subtitle: string;
  icon: string;
  substagesCount?: number;
  modulesCount?: number;
  accent: "primary" | "secondary" | "tertiary";
  description: string;
  latency: string;
  thd: string;
  phaseCorrelation: string;
  oversampling: string;
  substages?: {
    tag: string;
    title: string;
    meta: string;
    description: string;
    isWide?: boolean;
    badge?: string;
  }[];
  spatialDetails?: {
    title: string;
    description: string;
    parameters: { label: string; value: string }[];
  };
  telemetryDetails?: {
    engine: string;
    instructionSet: string;
    precision: string;
    bufferSize: string;
  };
}

export interface PresetItem {
  id: string;
  genre: string;
  title: string;
  description: string;
  metric: string;
  icon: string;
  color: "primary" | "secondary" | "tertiary";
}

export interface FounderSocials {
  linkedin?: string;
  github?: string;
  website?: string;
}

/** Metric identifiers shown in the landing A/B demo. */
export type ABMetricId = "lufs" | "tp" | "lra";

/** Design-token accent shared by the landing color mapping. */
export type AccentToken = "primary" | "secondary" | "tertiary";

/**
 * One illustrative metric in the A/B comparator.
 *
 * The values are deliberate product-demo numbers, not measurements: they make
 * the difference between an unmastered mix and the BrikMaster output legible
 * (louder and controlled vs. dynamic and peaky). Keep them clearly illustrative.
 */
export interface ABMetricDefinition {
  id: ABMetricId;
  /** i18n key under `landing.abPlayer` for the metric label. */
  labelKey: string;
  /** i18n key under `landing.abPlayer` for the unit symbol. */
  unitKey: string;
  /** Illustrative Original (bypass) value for this metric. */
  original: number;
  /** Illustrative BrikMaster Mastered value for this metric. */
  mastered: number;
  /** Lower bound of the display scale used to normalize the meter fill. */
  min: number;
  /** Upper bound of the display scale used to normalize the meter fill. */
  max: number;
  /** Decimal places shown in the readout. */
  decimals: number;
  /** Design-token accent used for the readout and meter fill. */
  accent: AccentToken;
}

export interface FounderItem {
  id: string;
  name: string;
  role: string;
  badge: string;
  badgeColor: "primary" | "secondary" | "tertiary";
  bio: string;
  quote: string;
  image: string;
  alt: string;
  socials?: FounderSocials;
}
