"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import { UserMenu, useAuth } from "@/features/auth";
import { useTranslation } from "@/i18n";
import LandingNavigation, { MobileMenuButton } from "./LandingNavigation";

export default function LandingHeader() {
  const { t } = useTranslation();
  const { user } = useAuth();

  return (
    <header className="fixed top-0 w-full z-50 bg-[#121317]/85 backdrop-blur-2xl border-b border-white/5">
      <div className="h-18 w-full px-4 sm:px-8 lg:px-12 max-w-[1440px] mx-auto flex items-center justify-between gap-4">
        {/* Brand Logo - Clean, no pulse, no badge */}
        <Link href="/" className="flex items-center gap-2.5 group" aria-label={t("landing.nav.brand", "BRIK")}>
          <img
            src="/brand/mascota-3d.png"
            alt=""
            className="w-7 h-7 rounded-lg object-contain transition-transform group-hover:scale-110"
            aria-hidden="true"
          />
          <span className="font-display-xl text-2xl text-primary font-bold tracking-tight">
            {t("landing.nav.brand", "BRIK")}
          </span>
        </Link>

        {/* Center: Desktop Navigation */}
        <LandingNavigation />

        {/* Right Actions - CTA + Language + User + Mobile Menu Button */}
        <div className="flex items-center gap-3">
          <Link
            href="/upload"
            className="hidden sm:flex px-4 py-2 rounded-lg bg-primary text-[#003734] font-body-sm font-bold hover:bg-primary-container transition-all flex items-center gap-1.5 shadow-[0_0_20px_rgba(110,233,224,0.3)] hover:scale-[1.02] active:scale-[0.98]"
          >
            <span>{t("landing.nav.enterStudio", "Ingresar a Brik Studio")}</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>

          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            {user ? <UserMenu /> : <ThemeToggle />}
            <MobileMenuButton />
          </div>
        </div>
      </div>
    </header>
  );
}