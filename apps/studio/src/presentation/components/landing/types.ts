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

/**
 * One commercial offer in the landing pricing section.
 *
 * Every user-visible string is resolved from i18n under `landing.pricing.*`;
 * this record only carries structure (ids, i18n keys, numbers, routing).
 *
 * Prices are business placeholders: they live ONLY in `PRICING_PLANS` in
 * data.ts so the owner can swap them in a single place. See the TODO(owner)
 * note there before changing anything.
 */
export interface PricingPlan {
  id: string;
  /** i18n key under `landing.pricing` for the offer name. */
  nameKey: string;
  /** i18n key under `landing.pricing` for the short positioning line. */
  taglineKey: string;
  /** Placeholder amount — see the TODO(owner) note on `PRICING_PLANS`. */
  price: number;
  /** ISO 4217 currency code rendered next to the price. */
  currency: string;
  /** i18n key under `landing.pricing` for the unit suffix (e.g. "per song"). */
  unitKey: string;
  /** Whether this offer is visually featured. */
  highlighted: boolean;
  /** Design-token accent used for the offer's icon and corner glow. */
  accent: AccentToken;
  /** Feature bullets — each entry is an i18n key under `landing.pricing`. */
  featureKeys: string[];
  /** Existing in-app route the CTA points to (no new routes invented). */
  ctaHref: string;
  /** i18n key under `landing.pricing` for the CTA label. */
  ctaKey: string;
}

/** One question/answer pair in the landing FAQ accordion. */
export interface FaqItem {
  id: string;
  /** i18n key under `landing.faq` for the question. */
  questionKey: string;
  /** i18n key under `landing.faq` for the answer. */
  answerKey: string;
}
