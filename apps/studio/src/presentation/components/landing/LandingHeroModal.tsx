"use client";

import { useEffect } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { useTranslation } from "@/i18n";
import BigGhostWithNotes from "@/presentation/components/BigGhostWithNotes";

export interface LandingHeroModalProps {
  /** Controls whether the modal is visible. Defaults to `true` when used standalone. */
  isOpen?: boolean;
  /** Callback fired when the user clicks the close ("x") button, backdrop, or presses Escape. */
  onClose?: () => void;
  /** Destination for the primary CTA button. Defaults to `/upload`. */
  ctaHref?: string;
}

/**
 * Responsive dark-theme modal card (~400px max-width) featuring the BRIK brand
 * header, the ghost-with-neon-notes illustration, hero value proposition,
 * pill CTA, and the Benefits summary footer.
 */
export default function LandingHeroModal({
  isOpen = true,
  onClose,
  ctaHref = "/upload",
}: LandingHeroModalProps) {
  const { t } = useTranslation();

  useEffect(() => {
    if (!isOpen || !onClose) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="brik-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 font-sans"
      onClick={onClose}
    >
      <div
        className="relative flex w-full max-w-[400px] flex-col items-center gap-6 rounded-3xl border border-zinc-800 bg-zinc-900 p-7 sm:p-8 text-center text-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Cabecera: BRIK en cyan/menta a la izquierda + botón cerrar ("x") a la derecha */}
        <div className="flex w-full items-center justify-between">
          <span className="text-lg font-extrabold tracking-tight text-[#4EE3D0]">
            {t("landing.nav.brand", "BRIK")}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("landing.nav.closeMenu", "Cerrar menú")}
            className="inline-flex h-8 w-8 items-center justify-center rounded-full text-gray-400 transition-colors hover:bg-zinc-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4EE3D0]/70 cursor-pointer"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {/* Ilustración central: fantasma gris rodeado de notas musicales en tonos neón */}
        <div className="my-2 flex h-36 w-full items-center justify-center">
          <BigGhostWithNotes size={68} radius={58} noteCount={6} />
        </div>

        {/* Título principal */}
        <h2
          id="brik-modal-title"
          className="text-balance text-2xl sm:text-3xl font-bold leading-tight tracking-tight text-white"
        >
          {t("landing.hero.title", "Masters profesionales en segundos.")}
        </h2>

        {/* Subtítulo */}
        <p className="text-sm leading-relaxed text-gray-400">
          {t(
            "landing.hero.subtitle",
            "Sube tu mezcla y obtén un sonido con pegada, dinámica y listo para plataformas de streaming. Sin dañar tu audio original."
          )}
        </p>

        {/* Botón principal (CTA) */}
        <Link
          href={ctaHref}
          onClick={onClose}
          className="inline-flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-[#4EE3D0] px-6 py-3.5 text-sm font-bold text-zinc-950 transition-all hover:brightness-110 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4EE3D0]/70"
        >
          <span>{t("landing.hero.ctaEnter", "Ingresar a Brik Studio")}</span>
          <span aria-hidden="true">→</span>
        </Link>

        {/* Sección inferior: Beneficios */}
        <div className="mt-2 flex flex-col items-center gap-1.5 border-t border-zinc-800/80 pt-5 w-full">
          <h3 className="text-base font-bold text-white">
            {t("landing.benefits.title", "Beneficios")}
          </h3>
          <p className="text-xs leading-relaxed text-gray-400">
            {t(
              "landing.benefits.subtitle",
              "Brik escucha tu audio antes de procesarlo y solo aplica lo que necesita."
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
