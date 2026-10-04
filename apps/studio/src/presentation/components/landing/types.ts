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
