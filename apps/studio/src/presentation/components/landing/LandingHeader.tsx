"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import gsap from "gsap";
import { ArrowRight } from "lucide-react";
import LanguageSwitcher from "@/presentation/components/LanguageSwitcher";
import ThemeToggle from "@/presentation/components/ThemeToggle";
import { UserMenu, useAuth } from "@/features/auth";
import { useTranslation } from "@/i18n";
import { BASE_PATH } from "@/lib/basePath";
import LandingNavigation from "./LandingNavigation";

export default function LandingHeader() {
  const { t } = useTranslation();
  const { user } = useAuth();
  // Magnetic hover on the primary CTA. The wrapper owns the GSAP translate so
  // it never fights the button's CSS scale transition. Desktop only.
  const ctaRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ctaRef.current;
    if (!el) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const xTo = gsap.quickTo(el, "x", { duration: 0.5, ease: "power3.out" });
    const yTo = gsap.quickTo(el, "y", { duration: 0.5, ease: "power3.out" });

    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      xTo(((e.clientX - (rect.left + rect.width / 2)) / (rect.width / 2)) * 8);
      yTo(((e.clientY - (rect.top + rect.height / 2)) / (rect.height / 2)) * 6);
    };
    const onLeave = () => {
      xTo(0);
      yTo(0);
    };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      gsap.set(el, { x: 0, y: 0 });
    };
  }, []);

  return (
    <header className="fixed top-0 w-full z-50 bg-[#121317]/85 backdrop-blur-2xl border-b border-white/[0.08]">
      <div className="h-18 w-full px-4 sm:px-8 lg:px-12 max-w-[1440px] mx-auto flex items-center justify-between gap-4">
        {/* Brand Logo - Clean, no pulse, no badge */}
        <Link href="/" className="flex items-center gap-2.5 min-h-[44px] group" aria-label={t("landing.nav.brand", "BRIK")}>
          <Image
            src={`${BASE_PATH}/brand/mascota-3d.png`}
            alt=""
            width={28}
            height={28}
            priority
            className="w-7 h-7 rounded-lg object-contain transition-transform group-hover:scale-110"
            aria-hidden="true"
          />
          <span className="font-display-xl text-2xl text-primary font-bold tracking-tight">
            {t("landing.nav.brand", "BRIK")}
          </span>
        </Link>

        {/* Center: Desktop Navigation + Mobile Button (inside Provider) */}
        <LandingNavigation />

        {/* Right Actions - CTA + Language + User */}
        <div className="flex items-center gap-3">
          <span ref={ctaRef} className="hidden sm:flex will-change-transform">
            <Link
              href="/upload"
              className="flex min-h-[44px] px-4 py-2 rounded-lg bg-primary text-[#003734] font-body-sm font-bold hover:bg-primary-container transition-all items-center gap-1.5 shadow-[0_0_20px_rgba(110,233,224,0.3)] hover:scale-[1.02] active:scale-[0.98]"
            >
              <span>{t("landing.nav.enterStudio", "Ingresar a Brik Studio")}</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </span>

          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            {user ? <UserMenu /> : <ThemeToggle />}
          </div>
        </div>
      </div>
    </header>
  );
}