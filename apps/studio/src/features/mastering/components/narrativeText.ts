import type { AgentNarrativeItem } from "@/lib/api";

/** Params that are counts, not measurements: a count never shows decimals.
 *
 *  `stems: 4` must read "4 stems", not "4.0 stems", while `lufs: -14` must read
 *  "−14.0 LUFS". The backend sends plain numbers, so the display decides.
 */
const COUNT_PARAMS = new Set(["stems", "flags", "fragments", "iteration", "attempt"]);

/** The subset of `t()` this module needs. */
type Translate = (
  path: string,
  params?: Record<string, string | number>,
  fallback?: string,
) => string;

/** One narrative item rendered in the active language.
 *
 *  The backend sends a stable `code` plus numbers and never prose, so the
 *  dictionary owns the words and the same run reads in Spanish or English.
 *
 *  A code the dictionary does not know yet falls back to the code itself: a
 *  silent gap would hide a step the run really took.
 */
export function narrativeSentence(t: Translate, item: AgentNarrativeItem): string {
  const params: Record<string, string | number> = {};

  for (const [key, value] of Object.entries(item.params)) {
    if (value === null) {
      // Never print 0 for a number the engine did not measure.
      params[key] = t("productor.narrative.notMeasured");
    } else if (typeof value === "number") {
      params[key] = COUNT_PARAMS.has(key)
        ? String(Math.round(value))
        : value.toFixed(1);
    } else if (key === "tool") {
      params[key] = t(`productor.tools.${value}`, undefined, value);
    } else {
      params[key] = value;
    }
  }

  return t(`productor.narrative.${item.code}`, params, item.code);
}
