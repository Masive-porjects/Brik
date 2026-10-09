"use client";

import Image from "next/image";
import Link from "next/link";
import { useTranslation } from "@/i18n";
import { BASE_PATH } from "@/lib/basePath";
import Reveal from "./Reveal";

// Real footer destinations only: the studio route plus the stable landing
// section anchors. No placeholder `#` links.
const FOOTER_NAV = [
  { key: "landing.footer.nav.studio", fallback: "Brik Studio", href: "/upload" },
  {
    key: "landing.footer.nav.engine",
    fallback: "Motor de 13 etapas",
    href: "#arquitectura-dsp",
  },
  {
    key: "landing.footer.nav.presets",
    fallback: "Presets fantasmagóricos",
    href: "#presets-fantasmagoricos",
  },
  { key: "landing.footer.nav.pricing", fallback: "Precios", href: "#precios" },
  {
    key: "landing.footer.nav.faq",
    fallback: "Preguntas frecuentes",
    href: "#faq",
  },
] as const;

export default function LandingFooter() {
  const { t } = useTranslation();

  return (
    <footer className="w-full bg-[#0d0e12] border-t border-white/[0.05] text-[#869391]">
      <Reveal className="w-full max-w-[1440px] mx-auto px-4 sm:px-8 lg:px-12 py-10">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2.5">
              <Image
                src={`${BASE_PATH}/brand/mascota-3d.png`}
                alt=""
                width={24}
                height={24}
                className="w-6 h-6 rounded-md object-contain"
                aria-hidden="true"
              />
              <span className="font-headline-sm text-base text-[#e3e2e8] font-bold tracking-tight">
                {t("landing.footer.brand", "BRIK")}
              </span>
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="font-label-technical text-primary text-[10px] tracking-wider uppercase">
                {t("landing.footer.engineOnline", "MOTOR DSP v3.4 EN LÍNEA")}
              </span>
            </div>
            <p className="font-body-sm text-xs text-[#869391]">
              {t(
                "landing.footer.copy",
                "© 2026 Brik Audio DSP Systems. Masterizado bajo conciencia espectral."
              )}
            </p>
          </div>

          <nav
            aria-labelledby="landing-footer-nav"
            className="flex flex-col gap-2.5"
          >
            <span
              id="landing-footer-nav"
              className="font-label-technical text-[10px] uppercase tracking-widest text-[#e3e2e8]"
            >
              {t("landing.footer.navTitle", "Navegación")}
            </span>
            <ul className="flex flex-wrap items-center gap-x-4 gap-y-2">
              {FOOTER_NAV.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="inline-flex items-center min-h-[44px] sm:min-h-[24px] font-label-technical text-[10px] uppercase tracking-wider text-[#869391] hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 rounded-sm"
                  >
                    {t(item.key, item.fallback)}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          <div className="flex flex-wrap items-center gap-3 font-label-technical text-[10px]">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1a1b20] rounded border border-white/5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              <span>{t("landing.footer.ebu", "EBU R128 (-14.0 LUFS)")}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1a1b20] rounded border border-white/5">
              <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
              <span>{t("landing.footer.truePeak", "TRUE PEAK: -1.0 dBTP")}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1a1b20] rounded border border-white/5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              <span>{t("landing.footer.clock", "RELOJ: 96kHz / 64-bit FP")}</span>
            </div>
          </div>
        </div>
      </Reveal>
    </footer>
  );
}
