"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowUp } from "lucide-react";
import { GhostIcon } from "@/presentation/components/ThemeToggle";
import { useTranslation } from "@/i18n";

export default function LandingScrollToTop() {
  const { t } = useTranslation();
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      // Appear once scrolled past hero (approx. 320px)
      setIsVisible(window.scrollY > 320);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.button
          type="button"
          onClick={scrollToTop}
          initial={{ opacity: 0, scale: 0.6, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.6, y: 20 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
          whileHover={{ scale: 1.12, y: -4 }}
          whileTap={{ scale: 0.92 }}
          className="fixed bottom-7 right-7 z-40 w-12 h-12 rounded-full flex items-center justify-center bg-[#1a1b20]/90 backdrop-blur-2xl border border-primary/40 text-primary shadow-[0_0_25px_rgba(110,233,224,0.35)] hover:shadow-[0_0_35px_rgba(110,233,224,0.6)] hover:border-primary transition-colors cursor-pointer group"
          aria-label={t("landing.scrollToTop", "Volver al inicio")}
          title={t("landing.scrollToTop", "Volver al inicio")}
        >
          {/* Subtle pulsating ghost glow ring */}
          <span className="absolute inset-0 rounded-full bg-primary/10 animate-ping pointer-events-none" />

          {/* Upward chevron / arrow badge on ghost's head */}
          <span className="absolute -top-1.5 w-4 h-4 rounded-full bg-primary text-[#003734] flex items-center justify-center shadow-md">
            <ArrowUp className="w-2.5 h-2.5 stroke-[3]" />
          </span>

          {/* Animated floating ghost mascot */}
          <motion.span
            animate={{ y: [0, -2, 0] }}
            transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
            className="flex items-center justify-center text-primary group-hover:text-primary-container transition-colors"
          >
            <GhostIcon size={22} />
          </motion.span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}
