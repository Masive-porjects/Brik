"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import { UserMenu, useAuth } from "@/features/auth";
import { useTranslation } from "@/i18n";

export default function LandingHeader() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [activeSection, setActiveSection] = useState<string>("arquitectura-dsp");
  const [isScrolled, setIsScrolled] = useState<boolean>(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20);

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
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const navLinks = [
    { id: "arquitectura-dsp", label: t("landing.nav.stage13", "Arquitectura 13 Etapas") },
    { id: "presets-fantasmagoricos", label: t("landing.nav.presets", "Presets Fantasmagóricos") },
    { id: "comparador", label: t("landing.nav.abCompare", "Comparador A/B") },
    { id: "equipo-fundador", label: t("landing.nav.founders", "Equipo Fundador") },
  ];

  return (
    <header
      className={`fixed top-0 w-full z-50 transition-all duration-300 ${
        isScrolled
          ? "bg-[#121317]/85 backdrop-blur-2xl border-b border-white/5 shadow-2xl"
          : "bg-[#121317]/60 backdrop-blur-xl border-b border-white/[0.03]"
      }`}
    >
      <div className="h-20 w-full px-4 sm:px-8 lg:px-12 max-w-[1440px] mx-auto flex items-center justify-between gap-4">
        {/* Brand Logo */}
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2 group">
            <span className="font-display-xl text-2xl lg:text-3xl text-primary font-bold tracking-tight transition-transform group-hover:scale-105">
              {t("landing.nav.brand", "BRIK")}
            </span>
            <span className="font-label-technical text-[10px] text-secondary uppercase bg-[#1a1b20] border border-secondary/30 px-2.5 py-0.5 rounded-full shadow-[0_0_10px_rgba(236,178,255,0.15)]">
              {t("landing.nav.dspCore", "DSP Core")}
            </span>
          </Link>

          {/* Center Navigation */}
          <nav className="hidden xl:flex items-center gap-1.5" aria-label="Navegación principal">
            {navLinks.map((link) => {
              const isActive = activeSection === link.id;
              return (
                <a
                  key={link.id}
                  href={`#${link.id}`}
                  className={`px-3.5 py-1.5 rounded-lg font-body-sm text-xs transition-all duration-200 ${
                    isActive
                      ? "bg-[#292a2e] text-primary font-semibold shadow-sm"
                      : "text-[#bcc9c7] hover:text-[#e3e2e8] hover:bg-white/[0.03]"
                  }`}
                >
                  {link.label}
                </a>
              );
            })}
          </nav>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-3">
          <Link
            href="/upload"
            className="px-4 lg:px-5 py-2 rounded-lg bg-primary text-[#003734] font-body-sm text-xs font-bold hover:bg-primary-container transition-all flex items-center gap-1.5 shadow-[0_0_20px_rgba(110,233,224,0.3)] hover:scale-[1.02] active:scale-[0.98]"
          >
            <span>{t("landing.nav.enterStudio", "Ingresar a Brik Studio")}</span>
            <span className="font-label-technical text-[10px] opacity-75 hidden sm:inline">
              {t("landing.nav.studioBadge", "(/studio)")}
            </span>
            <ArrowRight className="w-3.5 h-3.5 ml-0.5" />
          </Link>

          <div className="flex items-center gap-2 border-l border-white/10 pl-3">
            <LanguageSwitcher />
            <ThemeToggle />
            {user && <UserMenu />}
          </div>
        </div>
      </div>
    </header>
  );
}
