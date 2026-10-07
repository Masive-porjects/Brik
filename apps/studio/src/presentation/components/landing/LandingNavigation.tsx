"use client";

import { useState, useEffect, createContext, useContext } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "@/i18n";

interface NavLink {
  id: string;
  label: string;
}

const navLinks: NavLink[] = [
  { id: "arquitectura-dsp", label: "landing.nav.stage13" },
  { id: "presets-fantasmagoricos", label: "landing.nav.presets" },
  { id: "comparador", label: "landing.nav.abCompare" },
  { id: "equipo-fundador", label: "landing.nav.founders" },
];

// Context for shared mobile menu state
interface MobileMenuContextType {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  activeSection: string;
  onLinkClick: (id: string) => void;
}

const MobileMenuContext = createContext<MobileMenuContextType | null>(null);

function useMobileMenu() {
  const ctx = useContext(MobileMenuContext);
  if (!ctx) throw new Error("useMobileMenu must be used within MobileMenuProvider");
  return ctx;
}

// Desktop Navigation
function DesktopNav() {
  const { t } = useTranslation();
  const { activeSection, onLinkClick } = useMobileMenu();

  return (
    <nav className="hidden lg:flex items-center gap-1" aria-label="Navegación principal">
      {navLinks.map((link) => {
        const isActive = activeSection === link.id;
        return (
          <Link
            key={link.id}
            href={`#${link.id}`}
            onClick={() => onLinkClick(link.id)}
            className={`px-3.5 py-1.5 rounded-lg font-body-sm text-xs transition-all duration-200 ${
              isActive
                ? "bg-[#292a2e] text-primary font-semibold shadow-sm"
                : "text-[#bcc9c7] hover:text-[#e3e2e8] hover:bg-white/[0.03]"
            }`}
          >
            {t(link.label)}
          </Link>
        );
      })}
    </nav>
  );
}

// Mobile Hamburger Button (for right side of header)
export function MobileMenuButton() {
  const { isOpen, setIsOpen } = useMobileMenu();

  return (
    <button
      type="button"
      className="lg:hidden p-2 rounded-lg text-[#bcc9c7] hover:text-white hover:bg-white/[0.05] transition-colors"
      onClick={() => setIsOpen(!isOpen)}
      aria-expanded={isOpen}
      aria-controls="mobile-menu"
      aria-label={isOpen ? "Cerrar menú" : "Abrir menú"}
    >
      {isOpen ? (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
      ) : (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
      )}
    </button>
  );
}

// Mobile Drawer
function MobileDrawer() {
  const { t } = useTranslation();
  const { isOpen, setIsOpen, activeSection, onLinkClick } = useMobileMenu();

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          id="mobile-menu"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 lg:hidden"
          onClick={() => setIsOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Menú de navegación"
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          {/* Slide Panel - from right */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 400, damping: 35 }}
            className="absolute right-0 top-0 h-full w-full max-w-sm bg-[#121317] border-l border-white/5 shadow-2xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-white/5">
              <span className="font-display-xl text-xl text-primary font-bold">BRIK</span>
              <button
                type="button"
                className="p-1 rounded-lg hover:bg-white/[0.05] transition-colors"
                onClick={() => setIsOpen(false)}
                aria-label="Cerrar menú"
              >
                <svg className="w-5 h-5 text-[#bcc9c7]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            {/* Nav Links */}
            <nav className="flex-1 p-4 space-y-1 overflow-y-auto" aria-label="Navegación móvil">
              {navLinks.map((link) => {
                const isActive = activeSection === link.id;
                return (
                  <Link
                    key={link.id}
                    href={`#${link.id}`}
                    onClick={() => onLinkClick(link.id)}
                    className={`block px-4 py-3 rounded-xl font-body-sm transition-all duration-200 ${
                      isActive
                        ? "bg-primary/15 text-primary border border-primary/30 font-semibold"
                        : "text-[#bcc9c7] hover:text-white hover:bg-white/[0.03]"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span>{t(link.label)}</span>
                      {isActive && (
                        <svg className="w-4 h-4 text-primary flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                      )}
                    </div>
                  </Link>
                );
              })}

              {/* Mobile CTA */}
              <Link
                href="/upload"
                onClick={() => setIsOpen(false)}
                className="mt-6 block w-full px-5 py-3.5 rounded-xl bg-primary text-[#003734] font-body-sm font-bold text-center shadow-[0_0_20px_rgba(110,233,224,0.4)] hover:bg-primary-container transition-all active:scale-[0.98]"
              >
                {t("landing.nav.enterStudio", "Ingresar a Brik Studio")}
              </Link>
            </nav>

            {/* Footer info */}
            <div className="p-4 border-t border-white/5 text-center">
              <p className="font-label-technical text-[10px] text-[#869391] uppercase tracking-wider">
                {t("landing.nav.dspCore", "DSP Core")} v2.4
              </p>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// Main Provider Component
export default function LandingNavigation() {
  const [isOpen, setIsOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<string>("arquitectura-dsp");

  // Scroll spy for active section highlighting (desktop only)
  useEffect(() => {
    const handleScroll = () => {
      const sections = [
        "arquitectura-dsp",
        "presets-fantasmagoricos",
        "comparador",
        "equipo-fundador",
      ];

      for (const sectionId of sections) {
        const el = document.getElementById(sectionId);
        if (el) {
          const rect = el.getBoundingClientRect();
          if (rect.top <= 200 && rect.bottom >= 200) {
            setActiveSection(sectionId);
            break;
          }
        }
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Close mobile menu on link click + smooth scroll
  const handleLinkClick = (id: string) => {
    setIsOpen(false);
    const el = document.getElementById(id);
    if (el) {
      const headerHeight = 72;
      const top = el.getBoundingClientRect().top + window.scrollY - headerHeight;
      window.scrollTo({ top, behavior: "smooth" });
    }
  };

  const contextValue = {
    isOpen,
    setIsOpen,
    activeSection,
    onLinkClick: handleLinkClick,
  };

  return (
    <MobileMenuContext.Provider value={contextValue}>
      <DesktopNav />
      <MobileDrawer />
    </MobileMenuContext.Provider>
  );
}