"use client";

import Image from "next/image";
import { useTranslation } from "@/i18n";
import { BASE_PATH } from "@/lib/basePath";
import { GitHubIcon, LinkedInIcon } from "@/features/auth/components/SocialIcons";
import { FOUNDERS_LIST } from "./data";

/** Minimal team grid: photo, name, one-line role, and icon links. */
export default function LandingFounders() {
  const { t } = useTranslation();

  return (
    <section
      id="equipo"
      className="w-full py-24 lg:py-32 px-4 sm:px-8 lg:px-12 bg-[var(--bg-app)]"
    >
      <div className="max-w-[1000px] mx-auto flex flex-col gap-12">
        <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text-primary)] text-center">
          {t("landing.founders.title", "Conoce al Equipo")}
        </h2>

        <ul className="grid grid-cols-1 md:grid-cols-3 gap-10">
          {FOUNDERS_LIST.map((founder) => (
            <li key={founder.id} className="flex flex-col items-center text-center gap-4">
              <div className="relative w-32 h-32 rounded-full overflow-hidden bg-[var(--surface-active)]">
                <Image
                  src={`${BASE_PATH}${founder.image}`}
                  alt={founder.name}
                  fill
                  sizes="128px"
                  className="object-cover"
                  loading="lazy"
                />
              </div>

              <div className="flex flex-col gap-1 min-w-0 w-full">
                <h3 className="text-base font-semibold text-[var(--text-primary)] truncate">{founder.name}</h3>
                <p className="text-sm text-[var(--text-secondary)] truncate">{t(founder.roleKey)}</p>
              </div>

              <div className="flex items-center gap-3">
                {founder.socials.linkedin && (
                  <a
                    href={founder.socials.linkedin}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${founder.name} — LinkedIn`}
                    className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full text-[var(--text-secondary)] hover:text-primary transition-colors"
                  >
                    <LinkedInIcon className="size-5" />
                  </a>
                )}
                {founder.socials.github && (
                  <a
                    href={founder.socials.github}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${founder.name} — GitHub`}
                    className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full text-[var(--text-secondary)] hover:text-primary transition-colors"
                  >
                    <GitHubIcon className="size-5" />
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
