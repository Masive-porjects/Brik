"use client";

import Link from "next/link";
import { useTranslation } from "@/i18n";

// Real destinations only: the studio route plus the landing section anchors.
const FOOTER_NAV = [
  { key: "landing.footer.nav.studio", fallback: "Brik Studio", href: "/upload" },
  { key: "landing.footer.nav.beneficios", fallback: "Beneficios", href: "#beneficios" },
  { key: "landing.footer.nav.comparador", fallback: "Comparador A/B", href: "#comparador" },
  { key: "landing.footer.nav.perfiles", fallback: "Perfiles de Master", href: "#perfiles" },
  { key: "landing.footer.nav.precios", fallback: "Precios", href: "#precios" },
  { key: "landing.footer.nav.faq", fallback: "FAQ", href: "#faq" },
] as const;

export default function LandingFooter() {
  const { t } = useTranslation();

  return (
    <footer className="w-full bg-[var(--bg-app)] border-t border-[var(--border-subtle)]">
      <div className="max-w-[1200px] mx-auto px-4 sm:px-8 lg:px-12 py-12 flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <nav aria-label={t("landing.footer.navTitle", "Navegación")}>
          <ul className="flex flex-wrap gap-x-6 gap-y-2">
            {FOOTER_NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="inline-flex items-center min-h-[44px] text-sm text-[var(--text-secondary)] hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/70 rounded-sm"
                >
                  {t(item.key, item.fallback)}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <p className="text-xs text-[var(--text-muted)]">
          {t("landing.footer.copy", "© 2026 Brik Audio.")}
        </p>
      </div>
    </footer>
  );
}
