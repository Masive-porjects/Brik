"use client";

import { useTranslation } from "@/i18n";

export default function LandingFooter() {
  const { t } = useTranslation();

  return (
    <footer className="w-full bg-[#0d0e12] border-t border-white/[0.05] text-[#869391]">
      <div className="w-full max-w-[1440px] mx-auto px-4 sm:px-8 lg:px-12 py-10">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2.5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/brand/mascota-3d.png"
                alt="Brik Logo"
                className="w-6 h-6 rounded-md object-contain"
              />
              <span className="font-headline-sm text-base text-[#e3e2e8] font-bold tracking-tight">
                {t("landing.footer.brand", "BRIK AUDIO")}
              </span>
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              <span className="font-label-technical text-primary text-[10px] tracking-wider uppercase">
                {t("landing.footer.engineOnline", "MOTOR DSP v3.4 EN LÍNEA")}
              </span>
            </div>
            <p className="font-body-sm text-xs text-[#869391]">
              {t(
                "landing.footer.copy",
                "© 2024 Brik Audio DSP Systems. Masterizado bajo conciencia espectral."
              )}
            </p>
          </div>

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
      </div>
    </footer>
  );
}
