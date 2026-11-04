import type { ABMetricDefinition, FaqItem, FounderItem } from "./types";

/**
 * Illustrative A/B metrics for the landing demo.
 *
 * These are educational product-demo values, not measurements of any real
 * file. Mastered targets the streaming sweet spot (-14 LUFS, -1.0 dBTP, tight
 * LRA); Original is quieter on average, peakier and wider in dynamic range.
 */
export const AB_METRICS: ABMetricDefinition[] = [
  {
    id: "lufs",
    labelKey: "meterLufs",
    unitKey: "unitLufs",
    original: -18.6,
    mastered: -14.0,
    min: -24,
    max: -8,
    decimals: 1,
    accent: "primary",
  },
  {
    id: "tp",
    labelKey: "meterTp",
    unitKey: "unitTp",
    original: -0.3,
    mastered: -1.0,
    min: -6,
    max: 0,
    decimals: 2,
    accent: "secondary",
  },
  {
    id: "lra",
    labelKey: "meterLra",
    unitKey: "unitLra",
    original: 11.4,
    mastered: 6.5,
    min: 3,
    max: 15,
    decimals: 1,
    accent: "tertiary",
  },
];

/** Team cards: photo, name, one-line role, and icon links only. */
export const FOUNDERS_LIST: FounderItem[] = [
  {
    id: "brikman",
    name: "Brikman Paul Morales Lancheros",
    roleKey: "landing.founders.brikman.role",
    image: "/images/team/founder_1.jpg",
    socials: {
      linkedin: "https://www.linkedin.com/in/brikman-paul-morales/",
      github: "https://github.com/brikpaul569-cmd",
    },
  },
  {
    id: "miguel",
    name: "Miguel Angel Ariza",
    roleKey: "landing.founders.miguel.role",
    image: "/images/team/founder_2.jpg",
    socials: {
      linkedin:
        "https://www.linkedin.com/in/miguel-ariza-desarrollador?utm_source=share_via&utm_content=profile&utm_medium=member_android",
      github: "https://github.com/MiguelAriza77",
    },
  },
  {
    id: "andres",
    name: "Andrés Villanueva Tabares",
    roleKey: "landing.founders.andres.role",
    image: "/images/team/founder_3.jpg",
    socials: {
      linkedin: "https://www.linkedin.com/in/ingvillanuevat1/",
      github: "https://github.com/drakkomaximo",
    },
  },
];

export const FAQ_ITEMS: FaqItem[] = [
  {
    id: "ip",
    questionKey: "landing.faq.ip.question",
    answerKey: "landing.faq.ip.answer",
  },
  {
    id: "formats",
    questionKey: "landing.faq.formats.question",
    answerKey: "landing.faq.formats.answer",
  },
  {
    id: "deterministic",
    questionKey: "landing.faq.deterministic.question",
    answerKey: "landing.faq.deterministic.answer",
  },
  {
    id: "privacy",
    questionKey: "landing.faq.privacy.question",
    answerKey: "landing.faq.privacy.answer",
  },
  {
    id: "skill",
    questionKey: "landing.faq.skill.question",
    answerKey: "landing.faq.skill.answer",
  },
];
