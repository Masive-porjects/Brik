import { Loader2 } from "lucide-react";
import { useTranslation } from "@/i18n/useTranslation";

/**
 * Esqueleto de carga para /mezclas.
 *
 * Se muestra mientras Next.js hidrata el cliente y los primeros datos
 * (sesión, usuario, conteo de tracks) se resuelven. Evita que el usuario
 * vea una pantalla en blanco durante los ~2.7s de TTFB del documento
 * principal y da una señal clara de que la app está viva.
 */
export default function MezclasLoading() {
  const { t } = useTranslation();

  return (
    <div
      className="absolute inset-0 z-50 flex flex-col items-center justify-center p-6 bg-[var(--bg-app)]"
      aria-label={t("mezclas.trackLoading", "Cargando estudio…")}
    >
      <Loader2 size={28} className="mb-3 animate-spin text-[var(--accent-primary)]" aria-hidden="true" />
      <p className="text-sm text-[var(--text-secondary)]">
        {t("mezclas.trackLoading", "Cargando estudio…")}
      </p>
    </div>
  );
}
