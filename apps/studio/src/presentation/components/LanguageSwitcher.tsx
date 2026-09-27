"use client";

import React, { useCallback, useId } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation, type Locale } from "@/i18n/useTranslation";
import { useIsMounted } from "@/shared/hooks";

interface LanguageSwitcherProps {
  className?: string;
  compact?: boolean;
}

/**
 * Globo terráqueo tridimensional texturizado con la bandera del país,
 * conservando meridianos, paralelos, relieve esférico y brillo 3D.
 */
function FlagGlobeIcon({ locale, size = 19 }: { locale: Locale; size?: number }) {
  const rawId = useId().replace(/:/g, "");
  const clipId = `flag-globe-clip-${rawId}`;
  const shadeId = `flag-globe-shade-${rawId}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="shrink-0 drop-shadow-[0_1px_3px_rgba(0,0,0,0.35)]"
    >
      <defs>
        {/* Recorte esférico de globo terráqueo */}
        <clipPath id={clipId}>
          <circle cx="12" cy="12" r="9" />
        </clipPath>

        {/* Sombreado y brillo especular 3D de esfera de cristal */}
        <radialGradient id={shadeId} cx="30%" cy="26%" r="70%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.55" />
          <stop offset="40%" stopColor="#ffffff" stopOpacity="0" />
          <stop offset="75%" stopColor="#000000" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#000000" stopOpacity="0.65" />
        </radialGradient>
      </defs>

      {/* Bandera base recortada en la esfera */}
      <g clipPath={`url(#${clipId})`}>
        {locale === "es" ? (
          /* Bandera de España con proporción cromática */
          <g>
            <rect x="2" y="2" width="20" height="20" fill="#ffc400" />
            <rect x="2" y="2" width="20" height="5.5" fill="#de1b1b" />
            <rect x="2" y="16.5" width="20" height="5.5" fill="#de1b1b" />
            {/* Detalle heráldico estilizado */}
            <circle cx="7.8" cy="12" r="1.8" fill="#b71c1c" opacity="0.92" />
            <rect x="7.2" y="10.8" width="1.2" height="2.4" rx="0.4" fill="#fff59d" opacity="0.95" />
          </g>
        ) : (
          /* Bandera de EE.UU. / Global English estilizada */
          <g>
            <rect x="2" y="2" width="20" height="20" fill="#ffffff" />
            <rect x="2" y="2" width="20" height="2.6" fill="#b91c1c" />
            <rect x="2" y="7.2" width="20" height="2.6" fill="#b91c1c" />
            <rect x="2" y="12.4" width="20" height="2.6" fill="#b91c1c" />
            <rect x="2" y="17.6" width="20" height="2.6" fill="#b91c1c" />
            {/* Cantón azul con constelación de estrellas */}
            <rect x="2" y="2" width="9" height="8.6" fill="#1e3a8a" />
            <circle cx="4.5" cy="4.5" r="0.65" fill="#ffffff" />
            <circle cx="7.8" cy="4.5" r="0.65" fill="#ffffff" />
            <circle cx="6.15" cy="6.3" r="0.65" fill="#ffffff" />
            <circle cx="4.5" cy="8" r="0.65" fill="#ffffff" />
            <circle cx="7.8" cy="8" r="0.65" fill="#ffffff" />
          </g>
        )}

        {/* Relieve esférico 3D (sombra curva + brillo superior) */}
        <circle cx="12" cy="12" r="9" fill={`url(#${shadeId})`} />
      </g>

      {/* Meridianos y paralelos del globo terráqueo */}
      <g opacity="0.5">
        {/* Meridiano vertical elíptico */}
        <ellipse
          cx="12"
          cy="12"
          rx="4.4"
          ry="9"
          fill="none"
          stroke="#ffffff"
          strokeWidth="0.75"
        />
        {/* Eje central */}
        <line
          x1="12"
          y1="3"
          x2="12"
          y2="21"
          stroke="#ffffff"
          strokeWidth="0.6"
          strokeDasharray="1.2 1.5"
        />
        {/* Línea del Ecuador */}
        <line
          x1="3"
          y1="12"
          x2="21"
          y2="12"
          stroke="#ffffff"
          strokeWidth="0.75"
        />
        {/* Trópico de Cáncer (arco superior) */}
        <path
          d="M 4.5 8.2 Q 12 11 19.5 8.2"
          fill="none"
          stroke="#ffffff"
          strokeWidth="0.6"
        />
        {/* Trópico de Capricornio (arco inferior) */}
        <path
          d="M 4.5 15.8 Q 12 13 19.5 15.8"
          fill="none"
          stroke="#ffffff"
          strokeWidth="0.6"
        />
      </g>

      {/* Borde exterior del planeta */}
      <circle
        cx="12"
        cy="12"
        r="9"
        fill="none"
        stroke="#ffffff"
        strokeWidth="0.9"
        opacity="0.8"
      />
    </svg>
  );
}

export default function LanguageSwitcher({
  className = "",
}: LanguageSwitcherProps) {
  const isMounted = useIsMounted();
  const { locale, setLocale, isEs } = useTranslation();

  const toggleLanguage = useCallback(() => {
    const next: Locale = isEs ? "en" : "es";
    setLocale(next);
  }, [isEs, setLocale]);

  if (!isMounted) {
    return (
      <div
        className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 bg-[var(--bg-glass)] border border-[var(--border-subtle)] ${className}`}
        aria-hidden="true"
      />
    );
  }

  const label = isEs
    ? "Cambiar a idioma inglés (EN)"
    : "Switch to Spanish language (ES)";

  const title = isEs
    ? "Idioma: Español (Clic para English)"
    : "Language: English (Click for Español)";

  return (
    <button
      type="button"
      onClick={toggleLanguage}
      suppressHydrationWarning
      className={`relative w-9 h-9 rounded-full flex items-center justify-center shrink-0
        bg-[var(--bg-glass)] backdrop-blur-xl
        border border-[var(--border-subtle)] hover:border-[var(--border-strong)]
        text-[var(--accent-primary)]
        transition-all duration-200 hover:brightness-110 active:scale-95 ${className}`}
      aria-label={label}
      title={title}
    >
      {/* Levitación ambiental continua + animación elástica al cambiar */}
      <motion.span
        className="flex"
        animate={{ y: [0, -1.2, 0] }}
        transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={locale}
            className="flex items-center justify-center"
            initial={{ y: 4, opacity: 0, rotate: -25, scale: 0.6 }}
            animate={{ y: 0, opacity: 1, rotate: 0, scale: 1 }}
            exit={{ y: -6, opacity: 0, rotate: 25, scale: 0.5 }}
            transition={{ type: "spring", stiffness: 320, damping: 16 }}
          >
            <FlagGlobeIcon locale={locale} size={20} />
          </motion.span>
        </AnimatePresence>
      </motion.span>

      {/* Micro-badge: ES / EN */}
      <span
        className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full flex items-center justify-center
          bg-[var(--bg-glass-elevated)] border border-[var(--border-strong)]
          text-[var(--accent-primary)] text-[8.5px] font-bold tracking-tight shadow-sm select-none"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={locale}
            initial={{ opacity: 0, rotate: -50, scale: 0.4 }}
            animate={{ opacity: 1, rotate: 0, scale: 1 }}
            exit={{ opacity: 0, rotate: 50, scale: 0.4 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="flex items-center justify-center"
          >
            {locale.toUpperCase()}
          </motion.span>
        </AnimatePresence>
      </span>
    </button>
  );
}
