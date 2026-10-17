"use client";

import { useMemo } from "react";

export interface StaggerPart {
  content: string;
  delay: number;
  isWhitespace: boolean;
}

/**
 * Splits text into parts for staggered framer-motion animation.
 * Returns array of { content, delay, isWhitespace } for use with motion.span variants.
 *
 * @param text - The text to split
 * @param splitBy - "words" (default), "chars", or "lines"
 * @param baseDelay - Base delay in seconds before first part starts
 * @param stepDelay - Delay between each part in seconds (default 0.035 ~ GSAP feel)
 */
export function useStaggerText(
  text: string,
  splitBy: "words" | "chars" | "lines" = "words",
  baseDelay: number = 0,
  stepDelay: number = 0.035
): StaggerPart[] {
  return useMemo(() => {
    let parts: string[];

    switch (splitBy) {
      case "words":
        // Split by whitespace but keep the whitespace as separate parts
        parts = text.split(/(\s+)/).filter(Boolean);
        break;
      case "chars":
        parts = text.split("");
        break;
      case "lines":
        parts = text.split("\n");
        break;
      default:
        parts = [text];
    }

    return parts.map((part, i) => ({
      content: part,
      delay: baseDelay + i * stepDelay,
      isWhitespace: /\s/.test(part),
    }));
  }, [text, splitBy, baseDelay, stepDelay]);
}

/**
 * Variant definitions for staggered text animation.
 * Use with <motion.span variants={staggerVariants} /> wrapper and
 * <motion.span variants={childVariants} /> for each part.
 */
export const staggerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.035,
      delayChildren: 0.05,
    },
  },
} as const;

export const staggerChildVariants = {
  hidden: { opacity: 0, y: 10, filter: "blur(4px)" },
  visible: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.5, ease: [0.215, 0.61, 0.355, 1] },
  },
} as const;