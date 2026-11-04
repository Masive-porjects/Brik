/** Metric identifiers shown in the landing A/B demo. */
export type ABMetricId = "lufs" | "tp" | "lra";

/** Design-token accent shared by the landing color mapping. */
export type AccentToken = "primary" | "secondary" | "tertiary";

/**
 * One illustrative metric in the A/B comparator.
 *
 * The values are deliberate product-demo numbers, not measurements: they make
 * the difference between an unmastered mix and the Brik output legible
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
  /** Illustrative Brik master value for this metric. */
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

export interface FounderSocials {
  linkedin?: string;
  github?: string;
}

/** One team member card: photo, name, one-line role, and icon links. */
export interface FounderItem {
  id: string;
  name: string;
  /** i18n key under `landing.founders` for the one-line role. */
  roleKey: string;
  image: string;
  socials: FounderSocials;
}

/** One question/answer pair in the landing FAQ accordion. */
export interface FaqItem {
  id: string;
  /** i18n key under `landing.faq` for the question. */
  questionKey: string;
  /** i18n key under `landing.faq` for the answer. */
  answerKey: string;
}
