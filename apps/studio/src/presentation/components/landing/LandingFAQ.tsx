"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "@/i18n";
import { FAQ_ITEMS } from "./data";
import { easings, transitions } from "@/shared/lib/animations";

/**
 * Accessible accordion: native buttons (Enter/Space), aria-expanded and
 * aria-controls, and region panels labelled by their trigger. One item open
 * at a time; the first answer is open by default.
 */
export default function LandingFAQ() {
  const { t } = useTranslation();
  const [openId, setOpenId] = useState<string | null>(FAQ_ITEMS[0]?.id ?? null);

  return (
    <section
      id="faq"
      className="w-full py-24 lg:py-32 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)]"
    >
      <div className="max-w-2xl mx-auto flex flex-col gap-10">
        <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text-primary)]">
          {t("landing.faq.title", "Preguntas frecuentes")}
        </h2>

        <div className="flex flex-col gap-3">
          {FAQ_ITEMS.map((item) => {
            const isOpen = openId === item.id;
            const triggerId = `faq-trigger-${item.id}`;
            const panelId = `faq-panel-${item.id}`;

            return (
              <div
                key={item.id}
                className="rounded-2xl bg-[var(--bg-glass-elevated)] border border-[var(--border-subtle)] overflow-hidden"
              >
                <h3 className="m-0">
                  <button
                    type="button"
                    id={triggerId}
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    onClick={() => setOpenId(isOpen ? null : item.id)}
                    className="w-full min-h-[44px] flex items-center justify-between gap-4 px-5 sm:px-6 py-5 text-left text-base sm:text-lg font-semibold text-[var(--text-primary)] hover:text-primary transition-colors focus-visible:ring-2 focus-visible:ring-primary/70"
                  >
                    <span>{t(item.questionKey)}</span>
                    <motion.span
                      animate={{ rotate: isOpen ? 180 : 0 }}
                      transition={{ duration: 0.25, ease: easings.power2Out }}
                      className="flex-shrink-0"
                      aria-hidden="true"
                    >
                      <ChevronDown className="w-5 h-5 text-primary" />
                    </motion.span>
                  </button>
                </h3>

                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      id={panelId}
                      role="region"
                      aria-labelledby={triggerId}
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={transitions.presence}
                      className="overflow-hidden"
                    >
                      <p className="px-5 sm:px-6 pb-5 text-sm sm:text-base leading-relaxed text-[var(--text-secondary)]">
                        {t(item.answerKey)}
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
