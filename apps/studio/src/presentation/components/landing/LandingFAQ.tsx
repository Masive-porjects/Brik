"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "@/i18n";
import { FAQ_ITEMS } from "./data";
import { transitions, easings } from "@/shared/lib/animations";

export default function LandingFAQ() {
  const { t } = useTranslation();
  // One item open at a time keeps the section readable; opening the first
  // answer by default gives the accordion a visible resting state.
  const [openId, setOpenId] = useState<string | null>(FAQ_ITEMS[0]?.id ?? null);

  return (
    <section
      id="faq"
      className="w-full py-20 px-4 sm:px-8 lg:px-12 bg-[#0d0e12] relative overflow-x-hidden"
    >
      <div className="max-w-3xl mx-auto flex flex-col gap-10">
        {/* Section header — mirrors the other landing sections' reveal */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.15 }}
          transition={transitions.scrollReveal}
          className="flex flex-col gap-2"
        >
          <span className="font-label-technical text-secondary text-[10px] uppercase tracking-widest">
            {t("landing.faq.badge", "Preguntas Frecuentes")}
          </span>
          <h2 className="font-headline-lg text-2xl sm:text-3xl lg:text-4xl text-[#e3e2e8] font-bold">
            {t("landing.faq.title", "Todo lo que debes saber")}
          </h2>
          <p className="font-body-md text-[#bcc9c7] text-sm sm:text-base leading-relaxed">
            {t(
              "landing.faq.subtitle",
              "Respuestas directas sobre propiedad, formatos de entrega y cómo procesa el motor."
            )}
          </p>
        </motion.div>

        {/* Accessible accordion: native buttons (Enter/Space), aria-expanded
            + aria-controls, and region panels labelled by their trigger. */}
        <div className="flex flex-col gap-3">
          {FAQ_ITEMS.map((item, idx) => {
            const isOpen = openId === item.id;
            const triggerId = `faq-trigger-${item.id}`;
            const panelId = `faq-panel-${item.id}`;

            return (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.2 }}
                transition={{ ...transitions.scrollReveal, delay: idx * 0.05 }}
                className="rounded-2xl bg-[#121317]/95 backdrop-blur-md border border-white/[0.08] overflow-hidden"
              >
                <h3 className="m-0">
                  <button
                    type="button"
                    id={triggerId}
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    onClick={() => setOpenId(isOpen ? null : item.id)}
                    className="w-full min-h-[44px] flex items-center justify-between gap-4 px-5 sm:px-6 py-5 text-left font-headline-sm text-base sm:text-lg text-[#e3e2e8] hover:text-primary transition-colors focus-visible:ring-2 focus-visible:ring-primary/70"
                  >
                    <span>{t(item.questionKey)}</span>
                    <motion.span
                      animate={{ rotate: isOpen ? 180 : 0 }}
                      transition={{ duration: 0.25, ease: easings.power2Out }}
                      className="flex-shrink-0"
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
                      <p className="px-5 sm:px-6 pb-5 font-body-sm text-sm text-[#bcc9c7] leading-relaxed">
                        {t(item.answerKey)}
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
